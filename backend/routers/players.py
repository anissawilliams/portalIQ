"""
routers/players.py — Transfer portal player endpoints
"""

from fastapi import APIRouter, Query
from typing import Optional
from collections import defaultdict
import numpy as np
from data_loader import get_enriched_transfers, get_cbs_2026
from volatility import score_volatility

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


@router.get("/roster/{team}")
def team_roster(
    team: str,
    sport: str = Query(default="football"),
    season: Optional[int] = None,
):
    """
    Current roster view for a team — most recent portal additions
    with NIL estimates, position groups, and value scores.
    Grouped by position for depth chart rendering.
    """
    df = get_enriched_transfers()
    df = df[df["destination_school"] == team].copy()

    if season:
        df = df[df["season"] == season]
    else:
        latest = df["season"].max()
        df = df[df["season"] == latest]

    df = df.sort_values(
        ["pos_group", "position", "transfer_value_score"],
        ascending=[True, True, False]
    )

    df["depth_rank"] = df.groupby("position")["transfer_value_score"] \
                         .rank(ascending=False, method="first").astype(int)

    cols = [
        "player_name", "position", "pos_group", "depth_rank",
        "stars", "rating", "origin_school", "season",
        "transfer_value_score", "est_player_nil_cost",
        "is_upgrade", "eligibility",
    ]

    roster = clean(df[cols])
    grouped = {}
    for pos_group, group in roster.groupby("pos_group"):
        positions = {}
        for pos, players in group.groupby("position"):
            positions[pos] = players.to_dict(orient="records")
        grouped[pos_group] = positions

    return {
        "team": team,
        "season": int(df["season"].iloc[0]) if not df.empty else None,
        "total_players": len(df),
        "roster": grouped,
        "flat": roster.to_dict(orient="records"),
    }


@router.get("/volatility/{team}")
def team_volatility(
    team: str,
    sport: str = Query(default="football"),
    season: Optional[int] = None,
    min_score: float = Query(default=0, description="Minimum volatility score 0-100"),
):
    """
    Roster Volatility Model — predicts which players are at risk
    of entering the transfer portal.

    Volatility Score 0-100:
      CRITICAL (70+) — very likely to transfer, act now
      HIGH (50-69)   — elevated risk, monitor closely
      MEDIUM (30-49) — some risk factors, keep engaged
      LOW (<30)      — likely to stay

    Also returns:
      - Position group volatility summaries
      - Team Volatility Index (your signature metric)
      - Estimated NIL retention cost for at-risk players
    """
    df = get_enriched_transfers()
    df = df[df["destination_school"] == team].copy()

    if season:
        df = df[df["season"] == season]
    else:
        latest = df["season"].max()
        df = df[df["season"] == latest]

    if df.empty:
        return {"team": team, "error": "No roster data found"}

    # Add depth rank
    df["depth_rank"] = df.groupby("position")["transfer_value_score"] \
                         .rank(ascending=False, method="first").astype(int)

    # Position counts for depth pressure
    position_counts = df.groupby("position").size().to_dict()

    # Score every player
    players_out = []
    for _, row in df.iterrows():
        player = row.to_dict()
        vol = score_volatility(player, position_counts)
        players_out.append({
            "player_name":          player.get("player_name"),
            "position":             player.get("position"),
            "pos_group":            player.get("pos_group"),
            "depth_rank":           player.get("depth_rank"),
            "stars":                player.get("stars"),
            "origin_school":        player.get("origin_school"),
            "est_player_nil_cost":  player.get("est_player_nil_cost"),
            "transfer_value_score": player.get("transfer_value_score"),
            **vol,
        })

    # Filter by minimum score
    if min_score > 0:
        players_out = [p for p in players_out if p["volatility_score"] >= min_score]

    # Sort by volatility score descending
    players_out.sort(key=lambda p: p["volatility_score"], reverse=True)

    # ── Position group summaries ───────────────────────────────
    group_scores = defaultdict(list)
    for p in players_out:
        group_scores[p["pos_group"]].append(p["volatility_score"])

    def risk_label_from_avg(avg):
        if avg >= 70: return "CRITICAL"
        if avg >= 50: return "HIGH"
        if avg >= 30: return "MEDIUM"
        return "LOW"

    position_volatility = {
        group: {
            "avg_volatility": round(sum(scores) / len(scores), 1),
            "max_volatility": round(max(scores), 1),
            "player_count":   len(scores),
            "risk_label":     risk_label_from_avg(sum(scores) / len(scores)),
        }
        for group, scores in group_scores.items()
    }

    # ── Team Volatility Index ──────────────────────────────────
    all_scores = [p["volatility_score"] for p in players_out]
    tvi = round(sum(all_scores) / len(all_scores), 1) if all_scores else 0

    # ── Risk summary ──────────────────────────────────────────
    risk_summary = {
        "critical": sum(1 for p in players_out if p["risk_label"] == "CRITICAL"),
        "high":     sum(1 for p in players_out if p["risk_label"] == "HIGH"),
        "medium":   sum(1 for p in players_out if p["risk_label"] == "MEDIUM"),
        "low":      sum(1 for p in players_out if p["risk_label"] == "LOW"),
    }

    # ── Estimated NIL retention cost ──────────────────────────
    retention_cost = sum(
        p.get("est_player_nil_cost", 0)
        for p in players_out
        if p["risk_label"] in ("CRITICAL", "HIGH")
    )

    return {
        "team":                     team,
        "season":                   int(df["season"].iloc[0]),
        "team_volatility_index":    tvi,
        "risk_summary":             risk_summary,
        "estimated_retention_cost": retention_cost,
        "position_volatility":      position_volatility,
        "players":                  players_out,
    }