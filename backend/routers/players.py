"""
routers/players.py — Transfer portal player endpoints
"""

from fastapi import APIRouter, Query
from typing import Optional
import numpy as np
from data_loader import get_enriched_transfers, get_cbs_2026

router = APIRouter(prefix="/players", tags=["players"])


def clean(df):
    return df.replace({np.nan: None})


@router.get("/search")
def search_players(
    sport: str = Query(default="football"),
    position: Optional[str] = None,
    min_stars: float = Query(default=0),
    dest_conference: Optional[str] = None,
    origin_school: Optional[str] = None,
    dest_school: Optional[str] = None,
    season: Optional[int] = None,
    max_cost: Optional[float] = None,
    min_value_score: float = Query(default=0),
    limit: int = Query(default=50, le=200),
):
    """Search and filter transfer portal players."""
    df = get_enriched_transfers()

    if position:
        df = df[df["position"] == position]
    if min_stars:
        df = df[df["stars"] >= min_stars]
    if dest_conference:
        df = df[df["dest_conference"] == dest_conference]
    if origin_school:
        df = df[df["origin_school"] == origin_school]
    if dest_school:
        df = df[df["destination_school"] == dest_school]
    if season:
        df = df[df["season"] == season]
    if max_cost:
        df = df[df["est_player_nil_cost"] <= max_cost]
    if min_value_score:
        df = df[df["transfer_value_score"] >= min_value_score]

    df = df.sort_values("transfer_value_score", ascending=False).head(limit)

    cols = [
        "player_name", "position", "pos_group", "stars", "rating",
        "origin_school", "destination_school", "dest_conference",
        "season", "transfer_value_score", "est_player_nil_cost",
        "is_upgrade", "eligibility",
    ]
    return {
        "count": len(df),
        "players": clean(df[cols]).to_dict(orient="records"),
    }


@router.get("/moneyball")
def moneyball(
    sport: str = Query(default="football"),
    pos_group: Optional[str] = None,
    max_cost: Optional[float] = None,
    min_stars: float = Query(default=3.0),
    season: Optional[int] = None,
    limit: int = Query(default=30, le=100),
):
    """Highest value-to-cost ratio transfers — the underpriced plays."""
    df = get_enriched_transfers()

    if pos_group:
        # Accept either a position group ("Offense") or specific positions ("QB,WR")
        pos_list = [p.strip() for p in pos_group.split(",")]
        mask = df["pos_group"].isin(pos_list) | df["position"].isin(pos_list)
        df = df[mask]
    if max_cost:
        df = df[df["est_player_nil_cost"] <= max_cost]
    if min_stars:
        df = df[df["stars"] >= min_stars]
    if season:
        df = df[df["season"] == season]

    df = df[df["transfer_value_score"] > 0].copy()
    df["mb_score"] = df["transfer_value_score"] / np.log10(
        df["est_player_nil_cost"] + 10
    )
    df = df.sort_values("mb_score", ascending=False).head(limit)

    cols = [
        "player_name", "position", "pos_group", "stars", "rating",
        "origin_school", "destination_school", "dest_conference",
        "season", "transfer_value_score", "est_player_nil_cost",
        "mb_score", "is_upgrade",
    ]
    return {
        "count": len(df),
        "players": clean(df[cols]).to_dict(orient="records"),
    }


@router.get("/portal-2026")
def portal_2026(
    sport: str = Query(default="football"),
    position: Optional[str] = None,
    dest_school: Optional[str] = None,
    min_rating: Optional[int] = None,
):
    """2026 CBS Top 100 transfer portal rankings."""
    df = get_cbs_2026()

    if position:
        df = df[df["position"] == position]
    if dest_school:
        df = df[df["destination_school"] == dest_school]
    if min_rating:
        df = df[df["cbs_portal_rating"] >= min_rating]

    df = df.sort_values("rank")
    return {
        "count": len(df),
        "players": clean(df).to_dict(orient="records"),
    }


@router.get("/team/{team}")
def team_transfers(
    team: str,
    sport: str = Query(default="football"),
    direction: str = Query(default="in", pattern="^(in|out|both)$"),
    season: Optional[int] = None,
):
    """All transfers for a specific team."""
    df = get_enriched_transfers()

    if direction == "in":
        df = df[df["destination_school"] == team]
    elif direction == "out":
        df = df[df["origin_school"] == team]
    else:
        mask = (df["destination_school"] == team) | (df["origin_school"] == team)
        df = df[mask]

    if season:
        df = df[df["season"] == season]

    df = df.sort_values(["season", "transfer_value_score"], ascending=[False, False])

    cols = [
        "player_name", "position", "pos_group", "stars", "rating",
        "origin_school", "destination_school", "season",
        "transfer_value_score", "est_player_nil_cost", "is_upgrade",
    ]
    return {
        "team": team,
        "direction": direction,
        "count": len(df),
        "players": clean(df[cols]).to_dict(orient="records"),
    }
