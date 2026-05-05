"""
routers/projections.py — Player comps and class-level win projections

The intelligence layer of PortalIQ:
  - Find historical comparable transfers
  - Project individual player impact
  - Project full portal class impact on next season wins/SP+
  - Flag retention risks
"""

from fastapi import APIRouter, Query, HTTPException
from typing import Optional
import numpy as np
import pandas as pd
from data_loader import (
    get_enriched_transfers, get_master, get_nil_estimates, get_cbs_2026
)

router = APIRouter(prefix="/projections", tags=["projections"])

FBS_CONFERENCES = [
    "SEC", "Big Ten", "ACC", "Big 12", "Pac-12",
    "Mountain West", "American Athletic", "American",
    "Conference USA", "Sun Belt", "Mid-American", "FBS Independents",
]


def clean(obj):
    if isinstance(obj, dict):
        return {k: (None if (isinstance(v, float) and np.isnan(v)) else v)
                for k, v in obj.items()}
    if isinstance(obj, list):
        return [clean(i) for i in obj]
    if isinstance(obj, float) and np.isnan(obj):
        return None
    return obj


def find_comps(
    position: str,
    stars: float,
    origin_sp: float,
    dest_sp: float,
    before_season: int,
    n: int = 8,
) -> pd.DataFrame:
    """
    Find historical transfers comparable to a given player move.
    Similarity scored on: star rating proximity, origin SP+ match, dest SP+ match.
    Only uses transfers BEFORE before_season (no data leakage).
    """
    transfers = get_enriched_transfers()
    master    = get_master()

    # Filter to same position, similar stars, historical only
    t = transfers[
        (transfers["position"] == position) &
        (transfers["stars"].between(max(2, stars - 1), stars + 1)) &
        (transfers["destination_school"].notna()) &
        (transfers["season"] < before_season)
    ].copy()

    if t.empty:
        # Broaden to position group if no exact position matches
        pos_group = transfers[transfers["position"] == position]["pos_group"].iloc[0] \
            if not transfers[transfers["position"] == position].empty else None
        if pos_group:
            t = transfers[
                (transfers["pos_group"] == pos_group) &
                (transfers["stars"].between(max(2, stars - 1), stars + 1)) &
                (transfers["destination_school"].notna()) &
                (transfers["season"] < before_season)
            ].copy()

    if t.empty:
        return pd.DataFrame()

    # Similarity score: closer SP+ = better comp
    t["origin_sp_val"]  = t["origin_sp"].fillna(0)
    t["dest_sp_val"]    = t["dest_sp"].fillna(0)
    t["sim_origin"]     = 1 / (1 + abs(t["origin_sp_val"] - (origin_sp or 0)))
    t["sim_dest"]       = 1 / (1 + abs(t["dest_sp_val"]   - (dest_sp   or 0)))
    t["sim_stars"]      = 1 / (1 + abs(t["stars"] - stars))
    t["sim_score"]      = (
        t["sim_origin"] * 0.35 +
        t["sim_dest"]   * 0.35 +
        t["sim_stars"]  * 0.30
    )

    top = t.nlargest(n * 2, "sim_score").copy()

    # Join next-season outcomes for destination team
    results = []
    for _, row in top.iterrows():
        dest = row["destination_school"]
        yr   = int(row["season"])

        curr    = master[(master["team"] == dest) & (master["season"] == yr)]
        next_yr = master[(master["team"] == dest) & (master["season"] == yr + 1)]

        if curr.empty or next_yr.empty:
            continue

        win_delta = float(next_yr["wins"].iloc[0]) - float(curr["wins"].iloc[0])
        sp_curr   = curr["sp_overall"].iloc[0]
        sp_next   = next_yr["sp_overall"].iloc[0]
        sp_delta  = float(sp_next - sp_curr) if pd.notna(sp_curr) and pd.notna(sp_next) else None

        results.append({
            "player_name":       row["player_name"],
            "position":          row["position"],
            "stars":             float(row["stars"]),
            "origin_school":     row["origin_school"],
            "destination_school": dest,
            "season":            yr,
            "origin_sp":         float(row["origin_sp_val"]),
            "dest_sp":           float(row["dest_sp_val"]),
            "dest_wins":         float(curr["wins"].iloc[0]),
            "dest_wins_next":    float(next_yr["wins"].iloc[0]),
            "win_delta":         win_delta,
            "sp_delta":          sp_delta,
            "sim_score":         float(row["sim_score"]),
        })

        if len(results) >= n:
            break

    return pd.DataFrame(results)


# =============================================================================
# ENDPOINTS
# =============================================================================

@router.get("/player")
def player_projection(
    sport: str = Query(default="football"),
    player_name: Optional[str] = None,
    position: str = Query(...),
    stars: float = Query(...),
    origin_school: Optional[str] = None,
    destination_school: Optional[str] = None,
    season: int = Query(default=2025),
    n_comps: int = Query(default=6, le=20),
):
    """
    Project a player's impact by finding historical comparable transfers.

    Pass either a player_name (we look them up) or manually supply
    position/stars/origin_school/destination_school.
    """
    master = get_master()

    # Resolve SP+ for origin and destination
    def get_sp(team, yr):
        row = master[(master["team"] == team) & (master["season"] == yr)]
        if row.empty:
            row = master[(master["team"] == team)].sort_values("season").tail(1)
        return float(row["sp_overall"].iloc[0]) if not row.empty and pd.notna(row["sp_overall"].iloc[0]) else 0.0

    origin_sp = get_sp(origin_school, season - 1) if origin_school else 0.0
    dest_sp   = get_sp(destination_school, season - 1) if destination_school else 0.0

    comps = find_comps(
        position=position,
        stars=stars,
        origin_sp=origin_sp,
        dest_sp=dest_sp,
        before_season=season,
        n=n_comps,
    )

    if comps.empty:
        return {
            "player_name":        player_name,
            "position":           position,
            "stars":              stars,
            "origin_school":      origin_school,
            "destination_school": destination_school,
            "season":             season,
            "comps_found":        0,
            "projection":         None,
            "comps":              [],
            "message":            "Not enough historical comps found for this profile.",
        }

    # Aggregate projection
    avg_win_delta = float(comps["win_delta"].mean())
    med_win_delta = float(comps["win_delta"].median())
    avg_sp_delta  = float(comps["sp_delta"].dropna().mean()) if comps["sp_delta"].notna().any() else None
    pct_improved  = float((comps["win_delta"] > 0).mean() * 100)

    # Confidence: based on n comps and avg similarity score
    confidence = min(0.95, comps["sim_score"].mean() * len(comps) / n_comps)
    confidence_label = (
        "High" if confidence > 0.7 else
        "Medium" if confidence > 0.4 else
        "Low"
    )

    # Impact tier
    if avg_win_delta >= 2:
        impact = "Game Changer"
    elif avg_win_delta >= 0.5:
        impact = "Meaningful Contributor"
    elif avg_win_delta >= -0.5:
        impact = "Neutral"
    else:
        impact = "Risk"

    return {
        "player_name":        player_name,
        "position":           position,
        "stars":              stars,
        "origin_school":      origin_school,
        "origin_sp":          origin_sp,
        "destination_school": destination_school,
        "dest_sp":            dest_sp,
        "season":             season,
        "comps_found":        len(comps),
        "projection": clean({
            "avg_win_delta":   round(avg_win_delta, 2),
            "median_win_delta": round(med_win_delta, 2),
            "avg_sp_delta":    round(avg_sp_delta, 2) if avg_sp_delta else None,
            "pct_improved":    round(pct_improved, 1),
            "impact_tier":     impact,
            "confidence":      confidence_label,
            "confidence_score": round(confidence, 3),
            "summary": (
                f"Based on {len(comps)} comparable transfers, "
                f"destination teams averaged {avg_win_delta:+.1f} wins the following season. "
                f"{pct_improved:.0f}% of comps saw improvement."
            ),
        }),
        "comps": clean(comps.to_dict(orient="records")),
    }


@router.get("/class/{team}")
def class_projection(
    team: str,
    sport: str = Query(default="football"),
    season: int = Query(default=2025),
    include_2026_cbs: bool = Query(default=False),
):
    """
    Project next-season impact of a team's full portal class.
    Runs player_projection for each incoming transfer and aggregates.
    """
    transfers = get_enriched_transfers()
    master    = get_master()
    cbs_2026  = get_cbs_2026()

    # Get this team's incoming class
    team_class = transfers[
        (transfers["destination_school"] == team) &
        (transfers["season"] == season)
    ].copy()

    # Optionally include 2026 CBS portal moves
    if include_2026_cbs:
        cbs_team = cbs_2026[cbs_2026["destination_school"] == team].copy()
        if not cbs_team.empty:
            cbs_team["season"] = 2026
            cbs_team["stars"]  = (cbs_team["cbs_portal_rating"] / 20).clip(3, 5).round(0)
            cbs_team = cbs_team.rename(columns={"player_name": "player_name"})
            team_class = pd.concat([team_class, cbs_team], ignore_index=True)

    if team_class.empty:
        raise HTTPException(
            status_code=404,
            detail=f"No incoming transfers found for {team} in {season}"
        )

    # Get current team performance
    curr_perf = master[(master["team"] == team) & (master["season"] == season)]
    curr_wins = float(curr_perf["wins"].iloc[0]) if not curr_perf.empty else None
    curr_sp   = float(curr_perf["sp_overall"].iloc[0]) if not curr_perf.empty and pd.notna(curr_perf["sp_overall"].iloc[0]) else None

    def get_sp(t, yr):
        row = master[(master["team"] == t) & (master["season"] == yr)]
        if row.empty:
            row = master[master["team"] == t].sort_values("season").tail(1)
        return float(row["sp_overall"].iloc[0]) if not row.empty and pd.notna(row["sp_overall"].iloc[0]) else 0.0

    # Project each player
    player_projections = []
    win_deltas         = []
    sp_deltas          = []

    for _, player in team_class.iterrows():
        origin_sp = get_sp(player.get("origin_school", ""), season - 1) \
            if pd.notna(player.get("origin_school")) else 0.0
        dest_sp = get_sp(team, season - 1)

        comps = find_comps(
            position=str(player["position"]),
            stars=float(player.get("stars", 3.0)),
            origin_sp=origin_sp,
            dest_sp=dest_sp,
            before_season=season,
            n=6,
        )

        if not comps.empty:
            wd = float(comps["win_delta"].mean())
            sd = float(comps["sp_delta"].dropna().mean()) if comps["sp_delta"].notna().any() else None
            win_deltas.append(wd)
            if sd:
                sp_deltas.append(sd)

            player_projections.append(clean({
                "player_name":    player.get("player_name", "Unknown"),
                "position":       player["position"],
                "stars":          float(player.get("stars", 3.0)),
                "origin_school":  player.get("origin_school"),
                "comps_found":    len(comps),
                "proj_win_delta": round(wd, 2),
                "proj_sp_delta":  round(sd, 2) if sd else None,
                "impact_tier": (
                    "Game Changer" if wd >= 2 else
                    "Meaningful" if wd >= 0.5 else
                    "Neutral" if wd >= -0.5 else "Risk"
                ),
            }))

    # Class-level projection
    # Note: wins aren't purely additive — we use a dampened aggregate
    # Individual win deltas overlap; class effect ≈ sum * dampening factor
    DAMPENING = 0.35  # accounts for overlap between player contributions
    raw_win_delta = sum(win_deltas)
    proj_win_delta = raw_win_delta * DAMPENING
    proj_sp_delta  = np.mean(sp_deltas) if sp_deltas else None

    proj_wins = round(curr_wins + proj_win_delta, 1) if curr_wins is not None else None

    # Class grade
    avg_stars    = float(team_class["stars"].mean()) if "stars" in team_class.columns else None
    n_4star_plus = int((team_class["stars"] >= 4).sum()) if "stars" in team_class.columns else 0

    if proj_win_delta >= 3:
        class_grade = "A"
    elif proj_win_delta >= 1.5:
        class_grade = "B+"
    elif proj_win_delta >= 0.5:
        class_grade = "B"
    elif proj_win_delta >= -0.5:
        class_grade = "C"
    else:
        class_grade = "D"

    return clean({
        "team":   team,
        "season": season,
        "current_performance": {
            "wins":       curr_wins,
            "sp_overall": curr_sp,
        },
        "portal_class": {
            "players_in":     len(team_class),
            "players_projected": len(player_projections),
            "avg_stars":      round(avg_stars, 2) if avg_stars else None,
            "n_4star_plus":   n_4star_plus,
        },
        "projection": {
            "proj_win_delta":  round(proj_win_delta, 1),
            "proj_wins":       proj_wins,
            "proj_sp_delta":   round(proj_sp_delta, 1) if proj_sp_delta else None,
            "class_grade":     class_grade,
            "summary": (
                f"{team}'s {season} portal class projects to "
                f"{proj_win_delta:+.1f} wins vs prior season "
                f"(projected {proj_wins} wins). "
                f"Class grade: {class_grade}."
            ),
        },
        "players": sorted(
            player_projections,
            key=lambda x: x.get("proj_win_delta", 0),
            reverse=True
        ),
    })


@router.get("/retention-risk/{team}")
def retention_risk(
    team: str,
    sport: str = Query(default="football"),
    season: int = Query(default=2025),
):
    """
    Flag players on a team's roster who are flight risks based on:
    - Portal activity patterns for similar players
    - NIL market rate vs estimated current deal
    - Program trajectory (SP+ trend)
    """
    transfers = get_enriched_transfers()
    master    = get_master()
    nil_est   = get_nil_estimates()

    # Players who came IN to this team — are they likely to stay?
    incoming = transfers[
        (transfers["destination_school"] == team) &
        (transfers["season"].between(season - 2, season))
    ].copy()

    if incoming.empty:
        raise HTTPException(
            status_code=404,
            detail=f"No recent incoming transfers for {team}"
        )

    # Team SP+ trend — declining programs lose more players
    team_seasons = master[master["team"] == team].sort_values("season").tail(3)
    sp_trend = 0.0
    if len(team_seasons) >= 2:
        sp_vals = team_seasons["sp_overall"].dropna()
        if len(sp_vals) >= 2:
            sp_trend = float(sp_vals.iloc[-1] - sp_vals.iloc[0])

    # NIL budget trend
    team_nil = nil_est[nil_est["team"] == team].sort_values("season").tail(2)
    nil_trend = 0.0
    if len(team_nil) >= 2:
        nil_trend = float(team_nil["nil_final"].iloc[-1] - team_nil["nil_final"].iloc[0])

    # For each player, compute risk score
    risks = []
    for _, player in incoming.iterrows():
        risk_score = 0.0
        risk_flags = []

        # Factor 1: multi-year transferrer (has transferred before)
        prev_transfers = transfers[
            (transfers["player_name"] == player["player_name"]) &
            (transfers["season"] < player["season"])
        ]
        if not prev_transfers.empty:
            risk_score += 0.3
            risk_flags.append("Previous transfer history")

        # Factor 2: declining program SP+
        if sp_trend < -3:
            risk_score += 0.25
            risk_flags.append(f"Program SP+ declining ({sp_trend:+.1f})")

        # Factor 3: high star players at programs with flat/declining NIL
        if float(player.get("stars", 3)) >= 4 and nil_trend < 0:
            risk_score += 0.2
            risk_flags.append("4★+ player, NIL budget declining")

        # Factor 4: position market — some positions transfer more
        high_portal_positions = ["QB", "WR", "CB", "EDGE"]
        if player["position"] in high_portal_positions:
            risk_score += 0.1
            risk_flags.append(f"{player['position']} — high portal position")

        # Factor 5: how long ago they transferred — recent transfers more stable
        seasons_ago = season - int(player["season"])
        if seasons_ago >= 2:
            risk_score += 0.15
            risk_flags.append(f"Transferred {seasons_ago} seasons ago")

        risk_level = (
            "High"   if risk_score >= 0.55 else
            "Medium" if risk_score >= 0.30 else
            "Low"
        )

        risks.append(clean({
            "player_name":    player.get("player_name", "Unknown"),
            "position":       player["position"],
            "stars":          float(player.get("stars", 3.0)),
            "origin_school":  player.get("origin_school"),
            "transfer_season": int(player["season"]),
            "risk_score":     round(risk_score, 2),
            "risk_level":     risk_level,
            "risk_flags":     risk_flags,
        }))

    risks = sorted(risks, key=lambda x: x["risk_score"], reverse=True)

    high   = [r for r in risks if r["risk_level"] == "High"]
    medium = [r for r in risks if r["risk_level"] == "Medium"]
    low    = [r for r in risks if r["risk_level"] == "Low"]

    return {
        "team":   team,
        "season": season,
        "program_context": clean({
            "sp_trend_3yr":  round(sp_trend, 1),
            "nil_trend":     round(nil_trend, 0),
            "risk_environment": (
                "High Risk" if sp_trend < -5 else
                "Moderate Risk" if sp_trend < 0 else
                "Stable"
            ),
        }),
        "summary": {
            "players_assessed": len(risks),
            "high_risk":        len(high),
            "medium_risk":      len(medium),
            "low_risk":         len(low),
        },
        "players": risks,
    }


@router.get("/compare-classes")
def compare_classes(
    sport: str = Query(default="football"),
    teams: str = Query(..., description="Comma-separated teams"),
    season: int = Query(default=2025),
):
    """Compare portal class projections across multiple programs."""
    team_list = [t.strip() for t in teams.split(",")]
    results   = []

    transfers = get_enriched_transfers()
    master    = get_master()

    for team in team_list:
        team_class = transfers[
            (transfers["destination_school"] == team) &
            (transfers["season"] == season)
        ]
        curr = master[(master["team"] == team) & (master["season"] == season)]

        results.append({
            "team":          team,
            "players_in":    len(team_class),
            "avg_stars":     round(float(team_class["stars"].mean()), 2) if not team_class.empty else None,
            "n_4star_plus":  int((team_class["stars"] >= 4).sum()) if not team_class.empty else 0,
            "avg_value_score": round(float(team_class["transfer_value_score"].mean()), 3) if not team_class.empty and "transfer_value_score" in team_class.columns else None,
            "curr_wins":     float(curr["wins"].iloc[0]) if not curr.empty else None,
            "curr_sp":       float(curr["sp_overall"].iloc[0]) if not curr.empty and pd.notna(curr["sp_overall"].iloc[0]) else None,
        })

    return clean({
        "season":  season,
        "classes": sorted(results, key=lambda x: x.get("avg_stars") or 0, reverse=True),
    })
