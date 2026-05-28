"""
routers/rosters.py — 2026 ESPN Full Roster Endpoints
=====================================================
Full FBS roster data — all 13,765 players across all programs.
Unlike /players which covers portal additions only,
/rosters covers every player on every roster.
"""

from fastapi import APIRouter, Query, HTTPException
from typing import Optional
from collections import defaultdict
import numpy as np
from data_loader_2026 import get_team_roster_2026, get_rosters_2026, get_teams_2026
from volatility import score_volatility

router = APIRouter(prefix="/rosters", tags=["rosters"])


def clean(df):
    return df.where(df.notna(), None)

def clean_dict(d):
    return {k: (None if isinstance(v, float) and v != v else v)
            for k, v in d.items()}

@router.get("/teams")
def list_teams(
    conference: Optional[str] = None,
):
    """List all FBS teams with colors and metadata."""
    df = get_teams_2026()
    if conference:
        df = df[df.get("conference", "").str.lower() == conference.lower()]
    return {
        "count": len(df),
        "teams": clean(df).to_dict(orient="records"),
    }


@router.get("/{team}")
def team_roster_2026(
    team: str,
    pos_group: Optional[str] = None,
    cls: Optional[str] = Query(
        default=None,
        alias="class",
        description="Filter by class: Freshman, Sophomore, Junior, Senior, Graduate"
    ),
):
    """
    Full 2026 roster for a team — all players, not just portal additions.
    Includes headshots, class year, NIL estimates, depth ranks.
    Grouped by position group → position for depth chart rendering.
    """
    df = get_team_roster_2026(team)

    if df.empty:
        raise HTTPException(404, f"No roster found for '{team}'")

    if pos_group:
        df = df[df["pos_group"].str.lower() == pos_group.lower()]
    if cls:
        df = df[df["class"].str.lower() == cls.lower()]

    # Sort by position then transfer value (proxy for starter likelihood)
    df = df.sort_values(
        ["pos_group", "position", "transfer_value_score"],
        ascending=[True, True, False]
    )

    # Depth rank within each position
    df["depth_rank"] = (
        df.groupby("position")["transfer_value_score"]
          .rank(ascending=False, method="first")
          .astype(int)
    )

    # Team color info (from first row)
    team_color     = df["color"].iloc[0]     if "color"           in df.columns else None
    team_alt_color = df["alternate_color"].iloc[0] if "alternate_color" in df.columns else None

    cols = [
        "player_name", "short_name", "headshot", "jersey",
        "position", "position_name", "pos_group",
        "class", "class_abbreviation", "experience_years",
        "height", "weight", "depth_rank",
        "est_player_nil_cost", "transfer_value_score",
        "team", "team_abbreviation", "team_id",
        "athlete_id", "season",
    ]
    # Only include cols that exist
    cols = [c for c in cols if c in df.columns]

    roster = clean(df[cols])

    # Group by position group → position
    grouped = {}
    for pg, pg_group in roster.groupby("pos_group"):
        grouped[pg] = {}
        for pos, pos_players in pg_group.groupby("position"):
            grouped[pg][pos] = pos_players.to_dict(orient="records")

    # Class breakdown
    class_breakdown = df["class"].value_counts().to_dict()

    return {
        "team":            df["team"].iloc[0],
        "team_id":         df["team_id"].iloc[0],
        "team_color":      team_color,
        "team_alt_color":  team_alt_color,
        "season":          2026,
        "total_players":   len(df),
        "class_breakdown": class_breakdown,
        "roster":          grouped,
        "flat":            roster.to_dict(orient="records"),
    }


@router.get("/{team}/volatility")
def roster_volatility_2026(
    team: str,
    min_score: float = Query(default=0),
    pos_group: Optional[str] = None,
):
    """
    Full roster volatility model using 2026 ESPN data.
    Class-aware: Senior buried on depth chart = CRITICAL.
    Freshman buried = MEDIUM (still developing).
    Includes headshots for UI rendering.
    """
    df = get_team_roster_2026(team)

    if df.empty:
        raise HTTPException(404, f"No roster found for '{team}'")

    if pos_group:
        df = df[df["pos_group"].str.lower() == pos_group.lower()]

    # Depth rank
    df = df.copy()
    df["depth_rank"] = (
        df.groupby("position")["transfer_value_score"]
          .rank(ascending=False, method="first")
          .astype(int)
    )

    # Position counts for depth pressure
    position_counts = df.groupby("position").size().to_dict()

    # Score every player — class-aware
    players_out = []
    for _, row in df.iterrows():
        player   = row.to_dict()
        vol      = score_volatility(player, position_counts)

        # ── Class modifier ────────────────────────────────────
        # Seniors buried = amplify risk
        # Freshmen buried = reduce risk (developing is normal)
        cls        = str(player.get("class", "Sophomore"))
        depth_rank = int(player.get("depth_rank", 1))

        class_modifier = {
            "Senior":    1.25 if depth_rank >= 3 else 1.10,
            "Graduate":  1.30 if depth_rank >= 3 else 1.15,
            "Junior":    1.10 if depth_rank >= 3 else 1.00,
            "Sophomore": 0.90 if depth_rank >= 3 else 0.95,
            "Freshman":  0.65 if depth_rank >= 3 else 0.75,
        }.get(cls, 1.0)

        adjusted_score = round(
            min(vol["volatility_score"] * class_modifier, 100), 1
        )

        # Re-label after adjustment
        if adjusted_score >= 70:
            risk_label = "CRITICAL"
            risk_color = "#ef4444"
        elif adjusted_score >= 50:
            risk_label = "HIGH"
            risk_color = "#f97316"
        elif adjusted_score >= 30:
            risk_label = "MEDIUM"
            risk_color = "#eab308"
        else:
            risk_label = "LOW"
            risk_color = "#22c55e"

        players_out.append({
            "player_name":          player.get("player_name"),
            "short_name":           player.get("short_name"),
            "headshot":             player.get("headshot"),
            "jersey":               player.get("jersey"),
            "position":             player.get("position"),
            "pos_group":            player.get("pos_group"),
            "class":                cls,
            "class_abbreviation":   player.get("class_abbreviation"),
            "experience_years":     player.get("experience_years"),
            "depth_rank":           depth_rank,
            "est_player_nil_cost":  player.get("est_player_nil_cost"),
            "transfer_value_score": player.get("transfer_value_score"),
            "volatility_score":     adjusted_score,
            "risk_label":           risk_label,
            "risk_color":           risk_color,
            "breakdown":            vol["breakdown"],
        })

    # Filter
    if min_score > 0:
        players_out = [p for p in players_out if p["volatility_score"] >= min_score]

    # Sort
    players_out.sort(key=lambda p: p["volatility_score"], reverse=True)

    # Position group summaries
    group_scores = defaultdict(list)
    for p in players_out:
        group_scores[p["pos_group"]].append(p["volatility_score"])

    def risk_from_avg(avg):
        if avg >= 70: return "CRITICAL"
        if avg >= 50: return "HIGH"
        if avg >= 30: return "MEDIUM"
        return "LOW"

    position_volatility = {
        group: {
            "avg_volatility": round(sum(s) / len(s), 1),
            "max_volatility": round(max(s), 1),
            "player_count":   len(s),
            "risk_label":     risk_from_avg(sum(s) / len(s)),
        }
        for group, s in group_scores.items()
    }

    # Team Volatility Index
    all_scores = [p["volatility_score"] for p in players_out]
    tvi = round(sum(all_scores) / len(all_scores), 1) if all_scores else 0

    risk_summary = {
        "critical": sum(1 for p in players_out if p["risk_label"] == "CRITICAL"),
        "high":     sum(1 for p in players_out if p["risk_label"] == "HIGH"),
        "medium":   sum(1 for p in players_out if p["risk_label"] == "MEDIUM"),
        "low":      sum(1 for p in players_out if p["risk_label"] == "LOW"),
    }

    retention_cost = sum(
        p.get("est_player_nil_cost", 0)
        for p in players_out
        if p["risk_label"] in ("CRITICAL", "HIGH")
    )

    # Team color
    team_color    = df["color"].iloc[0]           if "color"           in df.columns else None
    team_alt      = df["alternate_color"].iloc[0] if "alternate_color" in df.columns else None

    return {
        "team":                     df["team"].iloc[0],
        "team_color":               team_color,
        "team_alt_color":           team_alt,
        "season":                   2026,
        "team_volatility_index":    tvi,
        "risk_summary":             risk_summary,
        "estimated_retention_cost": retention_cost,
        "position_volatility":      position_volatility,
        "players":                  players_out,
    }


@router.get("/search/players")
def search_roster_2026(
    team: Optional[str] = None,
    position: Optional[str] = None,
    cls: Optional[str] = Query(default=None, alias="class"),
    min_experience: int = Query(default=0),
    limit: int = Query(default=50, le=200),
):
    """Search across all 2026 FBS rosters."""
    df = get_rosters_2026()

    if team:
        mask = (
            df["team"].str.lower().str.contains(team.lower(), na=False) |
            df["team_abbreviation"].str.lower() == team.lower()
        )
        df = df[mask]
    if position:
        df = df[df["position"].str.upper() == position.upper()]
    if cls:
        df = df[df["class"].str.lower() == cls.lower()]
    if min_experience:
        df = df[df["experience_years"] >= min_experience]

    df = df.head(limit)

    cols = [
        "player_name", "headshot", "jersey", "position",
        "pos_group", "class", "experience_years",
        "team", "team_abbreviation", "est_player_nil_cost",
    ]
    cols = [c for c in cols if c in df.columns]

    return {
        "count": len(df),
        "players": clean(df[cols]).to_dict(orient="records"),
    }