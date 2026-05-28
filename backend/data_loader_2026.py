"""
data_loader_2026.py — ESPN 2026 Roster Data Loader
====================================================
Loads and enriches the full FBS roster dataset from Supabase.
Joins: athletes + athlete_teams + schools

All enrichment logic (NIL estimates, transfer value scores,
position mapping) is preserved from the CSV version.
"""

import os
import pandas as pd
import numpy as np
from functools import lru_cache
from db_client import get_service_client

# ── Position mapping (ESPN → PortalIQ standard) ───────────────
POSITION_MAP = {
    "QB":  "QB",  "RB":  "RB",  "WR":  "WR",  "TE":  "TE",
    "OT":  "OT",  "OL":  "IOL", "C":   "IOL", "G":   "IOL",
    "OG":  "IOL", "LS":  "LS",  "DE":  "EDGE","DL":  "DL",
    "DT":  "DL",  "NT":  "DL",  "LB":  "LB",  "ILB": "LB",
    "OLB": "LB",  "CB":  "CB",  "S":   "S",   "SS":  "S",
    "FS":  "S",   "DB":  "S",   "K":   "K",   "P":   "P",
    "ATH": "ATH",
}

POSITION_NIL = {
    "QB":  180000, "WR":   95000, "EDGE": 95000, "OT":  90000,
    "CB":   85000, "S":    70000, "LB":   65000, "DL":  65000,
    "IOL":  60000, "RB":   60000, "TE":   55000, "K":   30000,
    "P":    30000, "LS":   20000, "ATH":  50000,
}

CLASS_NIL_MODIFIER = {
    "Senior": 1.20, "Junior": 1.00, "Sophomore": 0.80,
    "Freshman": 0.65, "Graduate": 1.30,
}

POS_GROUP_MAP = {
    "OFF": "Offense", "DEF": "Defense", "ST": "Special Teams",
}


def _fetch_all_rosters() -> list[dict]:
    """
    Pull athletes + athlete_teams + schools from Supabase.
    Pages through all records (Supabase default limit is 1000).
    """
    client = get_service_client()
    all_rows = []
    page_size = 1000
    offset = 0

    while True:
        resp = (
            client.table("athlete_teams")
            .select(
                "season, position, jersey, class, class_abbreviation, "
                "experience_years, is_homegrown, status, "
                "athletes(id, espn_athlete_id, full_name, first_name, last_name, "
                "         short_name, espn_headshot, height, weight, "
                "         position, position_raw, position_name, pos_group, "
                "         birth_city, birth_state), "
                "schools(id, name, abbreviation, espn_team_id, "
                "        location, nickname, primary_color, secondary_color, conference)"
            )
            .range(offset, offset + page_size - 1)
            .execute()
        )

        batch = resp.data or []
        all_rows.extend(batch)

        if len(batch) < page_size:
            break
        offset += page_size

    return all_rows


def _flatten_row(row: dict) -> dict:
    athlete = row.get("athletes") or {}
    school = row.get("schools") or {}

    # Handle if Supabase returns nested joins as a list
    if isinstance(athlete, list):
        athlete = athlete[0] if athlete else {}
    if isinstance(school, list):
        school = school[0] if school else {}

    # Position — prefer athlete_teams.position, fall back to athletes.position
    raw_pos = (row.get("position") or athlete.get("position") or "ATH").upper()
    pos     = POSITION_MAP.get(raw_pos, raw_pos)

    # Class
    cls     = row.get("class") or "Sophomore"
    exp_raw = row.get("experience_years")
    exp     = int(exp_raw) if exp_raw is not None else 1

    # NIL estimate
    base_nil  = POSITION_NIL.get(pos, 55000)
    class_mod = CLASS_NIL_MODIFIER.get(cls, 1.0)
    est_nil   = round(base_nil * class_mod, 0)

    # Transfer value score
    nil_norm = base_nil / 180000
    tvs      = round(min(nil_norm * (exp / 4.0) * 1.2, 1.5), 4)

    # Position group
    pg_raw    = athlete.get("pos_group") or "OFF"
    pos_group = POS_GROUP_MAP.get(pg_raw, pg_raw)

    return {
        "athlete_id":           str(athlete.get("id", "")),
        "espn_athlete_id":      athlete.get("espn_athlete_id"),
        "player_name":          athlete.get("full_name", ""),
        "short_name":           athlete.get("short_name", ""),
        "first_name":           athlete.get("first_name", ""),
        "last_name":            athlete.get("last_name", ""),
        "headshot":             athlete.get("espn_headshot", ""),
        "jersey":               str(row.get("jersey") or athlete.get("jersey") or ""),
        "height":               athlete.get("height", ""),
        "weight":               athlete.get("weight", ""),
        "position":             pos,
        "position_raw":         raw_pos,
        "position_name":        athlete.get("position_name", ""),
        "pos_group":            pos_group,
        "class":                cls,
        "class_abbreviation":   row.get("class_abbreviation", ""),
        "experience_years":     exp,
        "season":               row.get("season"),
        "birth_city":           athlete.get("birth_city", ""),
        "birth_state":          athlete.get("birth_state", ""),
        "status":               str(row.get("status") or "Active"),
        "is_homegrown":         row.get("is_homegrown", True),
        "team":                 school.get("name", ""),
        "team_abbreviation":    school.get("abbreviation", ""),
        "team_id":              str(school.get("id", "")),
        "team_location":        school.get("location", ""),
        "team_nickname":        school.get("nickname", ""),
        "color":                school.get("primary_color", ""),
        "alternate_color":      school.get("secondary_color", ""),
        "conference":           school.get("conference", ""),
        "est_player_nil_cost":  est_nil,
        "transfer_value_score": tvs,
        "eligibility":          cls,
    }


@lru_cache(maxsize=1)
def get_rosters_2026() -> pd.DataFrame:
    """
    Load and enrich the full FBS roster from Supabase.
    Cached after first call — fast on subsequent requests.
    """
    print("Loading 2026 rosters from Supabase...")
    rows = _fetch_all_rosters()
    print(f"  Fetched {len(rows):,} athlete_team rows")

    flat = [_flatten_row(r) for r in rows]
    df   = pd.DataFrame(flat)

    # Drop rows with no player name (bad joins)
    df = df[df["player_name"].str.strip() != ""].copy()

    # Nuclear NaN sweep
    df = df.fillna("").replace({float("nan"): None})

    print(f"  Ready: {len(df):,} players across {df['team'].nunique()} teams")
    print(f"  Sample teams: {df['team'].value_counts().head(10).to_dict()}")
    return df


def get_team_roster_2026(team_name: str) -> pd.DataFrame:
    """
    Get enriched roster for a specific team.
    Matches on full name, location, abbreviation, or nickname.
    """
    df = get_rosters_2026()

    name = team_name.lower()
    mask = (
        (df["team"].str.lower() == name) |
        (df["team_location"].str.lower() == name) |
        (df["team_abbreviation"].str.lower() == name) |
        (df["team_nickname"].str.lower() == name)
    )
    result = df[mask].copy()

    # Fuzzy fallback
    if result.empty:
        mask2  = df["team"].str.lower().str.contains(name, na=False)
        result = df[mask2].copy()

    return result


def get_teams_2026() -> pd.DataFrame:
    """Get all distinct teams from the loaded roster."""
    df = get_rosters_2026()
    teams = (
        df[["team", "team_abbreviation", "team_id",
            "team_location", "team_nickname",
            "color", "alternate_color", "conference"]]
        .drop_duplicates(subset=["team_id"])
        .reset_index(drop=True)
    )
    return teams