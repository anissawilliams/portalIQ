"""
routers/teams.py — Team NIL budgets and program analytics
"""

from fastapi import APIRouter, Query, HTTPException
from typing import Optional
import numpy as np
from data_loader import get_nil_estimates, get_master, get_team_portal_history

router = APIRouter(prefix="/teams", tags=["teams"])


def clean(df):
    return df.replace({np.nan: None})


@router.get("/")
def list_teams(
    sport: str = Query(default="football"),
    conference: Optional[str] = None,
    season: int = Query(default=2024),
):
    """All FBS teams with NIL estimates for a given season."""
    df = get_nil_estimates()
    df = df[df["season"] == season]

    if conference:
        df = df[df["conference"] == conference]

    df = df.sort_values("nil_final", ascending=False)

    cols = ["team", "conference", "nil_final", "nil_is_actual",
            "adj_nil_value", "nil_pred_ensemble"]
    available = [c for c in cols if c in df.columns]

    return {
        "season": season,
        "count": len(df),
        "teams": clean(df[available]).to_dict(orient="records"),
    }


@router.get("/nil-rankings")
def nil_rankings(
    sport: str = Query(default="football"),
    season: int = Query(default=2024),
    conference: Optional[str] = None,
    limit: int = Query(default=50, le=200),
):
    """NIL budget rankings with context."""
    df = get_nil_estimates()
    master = get_master()

    df = df[df["season"] == season]
    if conference:
        df = df[df["conference"] == conference]

    # Join wins/SP+ for context
    perf = master[master["season"] == season][
        ["team", "wins", "losses", "sp_overall", "recruiting_rank"]
    ]
    df = df.merge(perf, on="team", how="left")
    df = df.sort_values("nil_final", ascending=False).head(limit)

    # Add rank
    df = df.reset_index(drop=True)
    df["nil_rank"] = df.index + 1

    # NIL per win (efficiency metric)
    df["nil_per_win"] = (df["nil_final"] / df["wins"].replace(0, np.nan)).round(0)

    cols = [
        "nil_rank", "team", "conference", "wins", "losses",
        "sp_overall", "recruiting_rank", "nil_final",
        "nil_is_actual", "nil_per_win",
    ]
    available = [c for c in cols if c in df.columns]

    return {
        "season": season,
        "count": len(df),
        "teams": clean(df[available]).to_dict(orient="records"),
    }


@router.get("/{team}")
def team_profile(team: str, sport: str = Query(default="football")):
    """Full program profile — performance history, portal history, NIL history."""
    master = get_master()
    if team not in master["team"].values:
        raise HTTPException(status_code=404, detail=f"Team '{team}' not found")

    return get_team_portal_history(team)


@router.get("/{team}/nil")
def team_nil_history(team: str, sport: str = Query(default="football")):
    """NIL spend history for a specific team."""
    df = get_nil_estimates()
    df = df[df["team"] == team].sort_values("season")

    if df.empty:
        raise HTTPException(status_code=404, detail=f"No NIL data for '{team}'")

    cols = ["season", "nil_final", "adj_nil_value", "nil_pred_ensemble", "nil_is_actual"]
    available = [c for c in cols if c in df.columns]

    return {
        "team": team,
        "nil_history": df[available].replace({np.nan: None}).to_dict(orient="records"),
    }


@router.get("/{team}/seasons")
def team_seasons(team: str, sport: str = Query(default="football")):
    """Year-by-year performance for a team."""
    master = get_master()
    df = master[master["team"] == team].sort_values("season")

    if df.empty:
        raise HTTPException(status_code=404, detail=f"No data for '{team}'")

    cols = [
        "season", "conference", "wins", "losses", "win_pct",
        "sp_overall", "recruiting_rank", "talent_composite",
        "transfers_in", "transfers_out", "avg_stars_in", "net_transfers",
        "ppg", "ppg_allowed", "point_differential",
    ]
    available = [c for c in cols if c in df.columns]

    return {
        "team": team,
        "seasons": df[available].replace({np.nan: None}).to_dict(orient="records"),
    }
