"""
data_loader.py — Loads and caches all dataframes at startup.
All routers import from here — one source of truth.
"""

from pathlib import Path
from functools import lru_cache
import pandas as pd
import numpy as np

DATA_DIR = Path(__file__).parent / "data"

FBS_CONFERENCES = [
    "SEC", "Big Ten", "ACC", "Big 12", "Pac-12",
    "Mountain West", "American Athletic", "American",
    "Conference USA", "Sun Belt", "Mid-American", "FBS Independents",
]

POS_GROUP = {
    "QB": "Offense", "RB": "Offense", "WR": "Offense", "TE": "Offense",
    "OT": "Offense", "OG": "Offense", "IOL": "Offense", "C": "Offense",
    "DL": "Defense", "DT": "Defense", "DE": "Defense", "EDGE": "Defense",
    "LB": "Defense", "OLB": "Defense", "ILB": "Defense",
    "CB": "Defense", "S": "Defense", "SAF": "Defense",
    "K": "Special", "P": "Special", "LS": "Special", "ATH": "Flex",
}

POS_MARKET_RATE = {
    "QB": 1.0, "EDGE": 0.65, "DL": 0.55, "DT": 0.55,
    "WR": 0.60, "CB": 0.55, "S": 0.45, "SAF": 0.45,
    "OT": 0.50, "LB": 0.40, "RB": 0.35, "TE": 0.30,
    "IOL": 0.25, "OG": 0.25, "ILB": 0.35, "OLB": 0.35,
    "K": 0.10, "P": 0.08, "LS": 0.07, "ATH": 0.40,
}

STAR_MULT = {5.0: 3.0, 4.0: 1.5, 3.0: 0.6, 2.0: 0.2, 1.0: 0.1}


@lru_cache(maxsize=1)
def get_transfers() -> pd.DataFrame:
    df = pd.read_csv(DATA_DIR / "transfers_raw.csv")
    df["stars"] = df["stars"].fillna(3.0)
    df["pos_group"] = df["position"].map(POS_GROUP).fillna("Other")
    df["pos_rate_idx"] = df["position"].map(POS_MARKET_RATE).fillna(0.3)
    df["star_mult"] = df["stars"].map(STAR_MULT).fillna(0.6)

    # Impute missing ratings from stars median
    rating_by_stars = df.groupby("stars")["rating"].median()
    df["rating"] = df.apply(
        lambda r: r["rating"] if pd.notna(r["rating"])
        else rating_by_stars.get(r["stars"], 0.85),
        axis=1,
    )
    return df


@lru_cache(maxsize=1)
def get_master() -> pd.DataFrame:
    df = pd.read_csv(DATA_DIR / "master_team_seasons.csv")
    return df[df["conference"].isin(FBS_CONFERENCES)].copy()


@lru_cache(maxsize=1)
def get_nil_estimates() -> pd.DataFrame:
    return pd.read_csv(DATA_DIR / "nil_estimates_all.csv")


@lru_cache(maxsize=1)
def get_cbs_2026() -> pd.DataFrame:
    return pd.read_csv(DATA_DIR / "cbs_transfers_2026.csv")


@lru_cache(maxsize=1)
def get_enriched_transfers() -> pd.DataFrame:
    """Transfers joined with destination team context and NIL estimates."""
    transfers = get_transfers()
    master = get_master()
    nil_est = get_nil_estimates()

    dest_ctx = master[["team", "season", "conference", "wins", "sp_overall"]].rename(
        columns={
            "team": "destination_school",
            "wins": "dest_wins",
            "sp_overall": "dest_sp",
            "conference": "dest_conference",
        }
    )
    origin_ctx = master[["team", "season", "wins", "sp_overall"]].rename(
        columns={"team": "origin_school", "wins": "origin_wins", "sp_overall": "origin_sp"}
    )
    nil_dest = nil_est[["team", "season", "nil_final"]].rename(
        columns={"team": "destination_school", "nil_final": "dest_nil_budget"}
    )

    t = transfers.copy()
    t = t.merge(dest_ctx, on=["season", "destination_school"], how="left")
    t = t.merge(origin_ctx, on=["season", "origin_school"], how="left")
    t = t.merge(nil_dest, on=["season", "destination_school"], how="left")

    t["transfer_value_score"] = (
        t["rating"]
        * t["pos_rate_idx"]
        * (1 + t["dest_sp"].fillna(0) / 50)
    )
    t["est_player_nil_cost"] = (
        t["dest_nil_budget"].fillna(2_000_000)
        * t["pos_rate_idx"]
        * 0.04
        * t["star_mult"]
    ).clip(50_000, 8_000_000)
    t["is_upgrade"] = (t["dest_sp"].fillna(0) > t["origin_sp"].fillna(0)).astype(int)

    return t


def get_team_portal_history(team: str) -> dict:
    """Full portal + performance history for a specific team."""
    transfers = get_enriched_transfers()
    master = get_master()
    nil_est = get_nil_estimates()

    team_master = master[master["team"] == team].sort_values("season")
    team_nil = nil_est[nil_est["team"] == team].sort_values("season")
    transfers_in = transfers[transfers["destination_school"] == team].sort_values(
        ["season", "transfer_value_score"], ascending=[True, False]
    )
    transfers_out = transfers[transfers["origin_school"] == team].sort_values(
        ["season", "stars"], ascending=[True, False]
    )

    return {
        "team": team,
        "seasons": team_master.replace({np.nan: None}).to_dict(orient="records"),
        "nil_history": team_nil.replace({np.nan: None}).to_dict(orient="records"),
        "transfers_in": transfers_in.replace({np.nan: None}).to_dict(orient="records"),
        "transfers_out": transfers_out.replace({np.nan: None}).to_dict(orient="records"),
    }


# =============================================================================
# SPORT ROUTING
# =============================================================================

SUPPORTED_SPORTS = ['football', 'basketball', 'soccer']

def validate_sport(sport: str) -> str:
    """Normalize and validate sport parameter."""
    sport = sport.lower().strip()
    aliases = {
        'cfb': 'football', 'nfl': 'football',
        'cbb': 'basketball', 'ncaab': 'basketball',
    }
    sport = aliases.get(sport, sport)
    if sport not in SUPPORTED_SPORTS:
        raise ValueError(f"Sport '{sport}' not supported. Choose from: {SUPPORTED_SPORTS}")
    return sport


def get_transfers_for_sport(sport: str = 'football') -> pd.DataFrame:
    """
    Returns transfer data for the given sport.
    Football: uses CFBD pipeline data.
    Basketball/Soccer: placeholder — wire in data source when ready.
    """
    sport = validate_sport(sport)
    if sport == 'football':
        return get_enriched_transfers()
    else:
        raise NotImplementedError(
            f"Sport '{sport}' data pipeline not yet connected. "
            f"Football is fully operational."
        )


def get_master_for_sport(sport: str = 'football') -> pd.DataFrame:
    """Returns team season data for the given sport."""
    sport = validate_sport(sport)
    if sport == 'football':
        return get_master()
    else:
        raise NotImplementedError(f"Sport '{sport}' data pipeline not yet connected.")
