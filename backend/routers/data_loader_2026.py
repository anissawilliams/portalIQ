"""
data_loader_2026.py — ESPN 2026 Roster Data Loader
====================================================
Loads and enriches the full FBS roster dataset (13,765 players)
from ESPN data pulled Wednesday May 2026.

Key differences from portal data:
  - Covers ENTIRE roster, not just transfers
  - Has class year (FR/SO/JR/SR) — critical for volatility
  - Has real headshots from ESPN CDN
  - Has real team colors via teams_2026.csv join
  - Has experience_years — how long in program
"""

import os
import pandas as pd
import numpy as np
from functools import lru_cache
from pathlib import Path

DATA_DIR = Path(__file__).parent / "data"

# ── Position mapping (ESPN → PortalIQ standard) ───────────────
POSITION_MAP = {
    # Offense
    "QB":  "QB",
    "RB":  "RB",
    "WR":  "WR",
    "TE":  "TE",
    "OT":  "OT",
    "OL":  "IOL",
    "C":   "IOL",
    "G":   "IOL",
    "OG":  "IOL",
    "LS":  "LS",
    # Defense
    "DE":  "EDGE",
    "DL":  "DL",
    "DT":  "DL",
    "NT":  "DL",
    "LB":  "LB",
    "ILB": "LB",
    "OLB": "LB",
    "CB":  "CB",
    "S":   "S",
    "SS":  "S",
    "FS":  "S",
    "DB":  "S",
    # Special teams
    "K":   "K",
    "P":   "P",
    "ATH": "ATH",
}

# ── NIL market rates by position ──────────────────────────────
POSITION_NIL = {
    "QB":   180000,
    "WR":    95000,
    "EDGE":  95000,
    "OT":    90000,
    "CB":    85000,
    "S":     70000,
    "LB":    65000,
    "DL":    65000,
    "IOL":   60000,
    "RB":    60000,
    "TE":    55000,
    "K":     30000,
    "P":     30000,
    "LS":    20000,
    "ATH":   50000,
}

# ── Class year modifiers ───────────────────────────────────────
CLASS_NIL_MODIFIER = {
    "Senior":    1.20,
    "Junior":    1.00,
    "Sophomore": 0.80,
    "Freshman":  0.65,
    "Graduate":  1.30,
}

# ── Position group normalization ──────────────────────────────
POS_GROUP_MAP = {
    "OFF": "Offense",
    "DEF": "Defense",
    "ST":  "Special Teams",
}


def _enrich_player(row: pd.Series) -> pd.Series:
    """Enrich a single ESPN roster row with NIL estimates and value scores."""
    pos      = POSITION_MAP.get(str(row.get("position", "")).upper(), row.get("position", "ATH"))
    cls      = str(row.get("class", "Sophomore"))
    exp      = int(row.get("experience_years") or 1)

    base_nil  = POSITION_NIL.get(pos, 55000)
    class_mod = CLASS_NIL_MODIFIER.get(cls, 1.0)
    est_nil   = round(base_nil * class_mod, 0)

    # Transfer value score — proxy from position value + experience
    # Senior starter at premium position = high value = high poaching risk
    nil_norm = base_nil / 180000
    tvs      = round(min(nil_norm * (exp / 4.0) * 1.2, 1.5), 4)

    # Position group
    pos_group_raw = str(row.get("position_group", "OFF"))
    pos_group     = POS_GROUP_MAP.get(pos_group_raw, pos_group_raw)

    return pd.Series({
        "player_name":          row.get("display_name", ""),
        "short_name":           row.get("short_name", ""),
        "first_name":           row.get("first_name", ""),
        "last_name":            row.get("last_name", ""),
        "athlete_id":           row.get("athlete_id", ""),
        "headshot":             row.get("headshot", ""),
        "jersey":               str(row.get("jersey", "")),
        "height":               row.get("display_height", ""),
        "weight":               row.get("display_weight", ""),
        "position":             pos,
        "position_raw":         row.get("position", ""),
        "position_name":        row.get("position_name", ""),
        "pos_group":            pos_group,
        "class":                cls,
        "class_abbreviation":   row.get("class_abbreviation", ""),
        "experience_years":     exp,
        "season":               int(row.get("season", 2026)),
        "team":                 row.get("team", ""),
        "team_abbreviation":    row.get("team_abbreviation", ""),
        "team_id":              str(row.get("team_id", "")),
        "team_location":        row.get("team_location", ""),
        "team_nickname":        row.get("team_nickname", ""),
        "birth_city":           row.get("birth_city", ""),
        "birth_state":          row.get("birth_state", ""),
        "status":               row.get("status", "Active"),
        "est_player_nil_cost":  est_nil,
        "transfer_value_score": tvs,
        "eligibility":          cls,
        "is_homegrown":         1,   # on roster = not a portal addition
    })


@lru_cache(maxsize=1)
def get_rosters_2026() -> pd.DataFrame:
    """
    Load and enrich the full 2026 FBS roster.
    Cached after first load — fast on subsequent calls.
    """
    roster_path = DATA_DIR / "cfb_rosters_2026.csv"
    teams_path  = DATA_DIR / "teams_2026.csv"

    if not roster_path.exists():
        raise FileNotFoundError(f"Roster file not found: {roster_path}")

    print(f"Loading 2026 rosters from {roster_path}...")
    df = pd.read_csv(roster_path, low_memory=False)
    print(f"  Loaded {len(df):,} players")

    # Enrich each player
    enriched = df.apply(_enrich_player, axis=1)

    # Join team colors/logos if teams file exists
    if teams_path.exists():
        teams = pd.read_csv(teams_path, sep="\t")
        teams = teams.rename(columns={"team_id": "team_id_str"})
        teams["team_id_str"] = teams["team_id_str"].astype(str)
        enriched["team_id"] = enriched["team_id"].astype(str)

        enriched = enriched.merge(
            teams[["team_id_str", "color", "alternate_color", "abbreviation"]],
            left_on="team_id",
            right_on="team_id_str",
            how="left",
            suffixes=("", "_teams")
        ).drop(columns=["team_id_str"], errors="ignore")

    print(f"  Enriched {len(enriched):,} players across "
          f"{enriched['team'].nunique()} teams")
    return enriched


def get_team_roster_2026(team_name: str) -> pd.DataFrame:
    """
    Get enriched roster for a specific team.
    Matches on team name, location, or abbreviation.
    """
    df = get_rosters_2026()

    # Try multiple match strategies
    mask = (
        (df["team"].str.lower() == team_name.lower()) |
        (df["team_location"].str.lower() == team_name.lower()) |
        (df["team_abbreviation"].str.lower() == team_name.lower()) |
        (df["team_nickname"].str.lower() == team_name.lower())
    )
    result = df[mask].copy()

    if result.empty:
        # Fuzzy fallback — contains match
        mask2 = df["team"].str.lower().str.contains(team_name.lower(), na=False)
        result = df[mask2].copy()

    return result


def get_teams_2026() -> pd.DataFrame:
    """Get all teams with colors and metadata."""
    teams_path = DATA_DIR / "teams_2026.csv"
    if not teams_path.exists():
        raise FileNotFoundError(f"Teams file not found: {teams_path}")
    df = pd.read_csv(teams_path, sep="\t")
    return df