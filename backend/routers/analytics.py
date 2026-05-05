"""
routers/analytics.py — Budget optimizer, ROI analysis, program comparisons
"""

from fastapi import APIRouter, Query
from typing import Optional, List
import numpy as np
import pandas as pd
from data_loader import get_enriched_transfers, get_nil_estimates, get_master

router = APIRouter(prefix="/analytics", tags=["analytics"])


def clean(df):
    return df.replace({np.nan: None})


@router.get("/budget-optimizer")
def budget_optimizer(
    sport: str = Query(default="football"),
    budget: float = Query(..., description="Total NIL budget in dollars"),
    positions: Optional[str] = Query(
        default=None,
        description="Comma-separated positions to prioritize e.g. QB,WR,EDGE"
    ),
    min_stars: float = Query(default=3.0),
    season: Optional[int] = None,
    strategy: str = Query(
        default="value",
        pattern="^(value|stars|balanced)$",
        description="value=moneyball, stars=best available, balanced=mix"
    ),
):
    """
    Given a budget, return the optimal portal class.
    Strategies:
      value    — maximize transfer_value_score per dollar (moneyball)
      stars    — maximize total star rating
      balanced — mix of value and stars
    """
    df = get_enriched_transfers()

    if min_stars:
        df = df[df["stars"] >= min_stars]
    if season:
        df = df[df["season"] == season]
    if positions:
        pos_list = [p.strip() for p in positions.split(",")]
        df = df[df["position"].isin(pos_list)]

    df = df[df["est_player_nil_cost"] <= budget].copy()

    # Scoring by strategy
    if strategy == "value":
        df["sort_score"] = df["transfer_value_score"] / np.log10(
            df["est_player_nil_cost"] + 10
        )
    elif strategy == "stars":
        df["sort_score"] = df["stars"] * 10 + df["transfer_value_score"]
    else:  # balanced
        max_val = df["transfer_value_score"].max() or 1
        max_cost = df["est_player_nil_cost"].max() or 1
        df["sort_score"] = (
            0.5 * df["transfer_value_score"] / max_val +
            0.5 * (1 - df["est_player_nil_cost"] / max_cost)
        )

    df = df.sort_values("sort_score", ascending=False)

    # Greedy selection within budget
    selected = []
    remaining = budget
    used_names = set()

    for _, row in df.iterrows():
        cost = row["est_player_nil_cost"]
        name = row["player_name"]
        if cost <= remaining and name not in used_names:
            selected.append(row)
            remaining -= cost
            used_names.add(name)

    result = pd.DataFrame(selected)

    cols = [
        "player_name", "position", "pos_group", "stars",
        "origin_school", "destination_school", "season",
        "transfer_value_score", "est_player_nil_cost", "sort_score",
    ]
    available = [c for c in cols if c in result.columns]

    return {
        "budget": budget,
        "strategy": strategy,
        "players_selected": len(result),
        "total_cost": round(budget - remaining, 0),
        "remaining_budget": round(remaining, 0),
        "avg_stars": round(result["stars"].mean(), 2) if not result.empty else 0,
        "avg_value_score": round(result["transfer_value_score"].mean(), 3) if not result.empty else 0,
        "class": clean(result[available]).to_dict(orient="records"),
    }


@router.get("/program-comparison")
def program_comparison(
    sport: str = Query(default="football"),
    teams: str = Query(..., description="Comma-separated team names e.g. 'Florida State,Miami,Clemson'"),
    season: int = Query(default=2024),
):
    """Side-by-side program comparison for recruiting, portal, NIL, and performance."""
    team_list = [t.strip() for t in teams.split(",")]

    master = get_master()
    nil_est = get_nil_estimates()
    transfers = get_enriched_transfers()

    results = []
    for team in team_list:
        m = master[(master["team"] == team) & (master["season"] == season)]
        n = nil_est[(nil_est["team"] == team) & (nil_est["season"] == season)]
        t_in = transfers[
            (transfers["destination_school"] == team) &
            (transfers["season"] == season)
        ]
        t_out = transfers[
            (transfers["origin_school"] == team) &
            (transfers["season"] == season)
        ]

        results.append({
            "team": team,
            "season": season,
            "wins": int(m["wins"].iloc[0]) if not m.empty else None,
            "losses": int(m["losses"].iloc[0]) if not m.empty else None,
            "sp_overall": float(m["sp_overall"].iloc[0]) if not m.empty and pd.notna(m["sp_overall"].iloc[0]) else None,
            "recruiting_rank": float(m["recruiting_rank"].iloc[0]) if not m.empty and pd.notna(m["recruiting_rank"].iloc[0]) else None,
            "nil_budget": float(n["nil_final"].iloc[0]) if not n.empty else None,
            "nil_is_actual": bool(n["nil_is_actual"].iloc[0]) if not n.empty else False,
            "transfers_in": len(t_in),
            "transfers_out": len(t_out),
            "avg_stars_in": round(t_in["stars"].mean(), 2) if not t_in.empty else None,
            "avg_value_score_in": round(t_in["transfer_value_score"].mean(), 3) if not t_in.empty else None,
            "est_portal_spend": round(t_in["est_player_nil_cost"].sum(), 0) if not t_in.empty else None,
            "top_transfer_in": t_in.sort_values("transfer_value_score", ascending=False)["player_name"].iloc[0] if not t_in.empty else None,
        })

    return {
        "season": season,
        "teams": results,
    }


@router.get("/nil-roi")
def nil_roi(
    sport: str = Query(default="football"),
    season: int = Query(default=2024),
    conference: Optional[str] = None,
):
    """NIL spend vs wins — who's getting the best return on investment."""
    nil_est = get_nil_estimates()
    master = get_master()

    df = nil_est[nil_est["season"] == season].copy()
    perf = master[master["season"] == season][["team", "wins", "losses", "sp_overall"]]
    # Drop overlapping cols to avoid _x/_y suffix conflicts
    for col in ["wins", "losses", "sp_overall"]:
        if col in df.columns:
            df = df.drop(columns=[col])
    df = df.merge(perf, on="team", how="inner")

    if conference:
        df = df[df["conference"] == conference]

    df = df[df["wins"] > 0].copy()
    df["nil_per_win"] = (df["nil_final"] / df["wins"]).round(0)
    df["roi_score"] = (df["wins"] / (df["nil_final"] / 1_000_000)).round(2)

    df = df.sort_values("roi_score", ascending=False)
    df["roi_rank"] = range(1, len(df) + 1)

    cols = [
        "roi_rank", "team", "conference", "wins", "losses",
        "nil_final", "nil_per_win", "roi_score", "nil_is_actual",
    ]
    available = [c for c in cols if c in df.columns]

    return {
        "season": season,
        "metric": "wins per $1M NIL spend",
        "teams": clean(df[available]).to_dict(orient="records"),
    }
