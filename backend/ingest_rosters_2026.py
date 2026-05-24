"""
ingest_rosters_2026.py — Push 2026 roster data into Supabase
=============================================================
Reads cfb_rosters_2026_clean.csv and inserts into:
  - athletes (master identity, one row per person)
  - athlete_teams (school affiliation for 2026 season)
  - data_provenance (audit log)

Safe to re-run — upserts on espn_athlete_id for athletes,
and on (athlete_id, school_id, season) for athlete_teams.

Run from backend/:
    python ingest_rosters_2026.py
"""

import os
import math
import pandas as pd
from pathlib import Path
from datetime import datetime, timezone
from dotenv import load_dotenv
from supabase import create_client, Client

load_dotenv()

SUPABASE_URL     = os.environ.get("SUPABASE_URL", "https://fpigpzmgqmzoxdknhetg.supabase.co")
SUPABASE_KEY     = os.environ.get("SUPABASE_SERVICE_KEY")
DATA_DIR         = Path(__file__).parent / "data"
ROSTER_CSV       = DATA_DIR / "cfb_rosters_2026_clean.csv"
SEASON           = 2026
BATCH_SIZE       = 100   # rows per upsert call

if not SUPABASE_KEY:
    raise ValueError("SUPABASE_SERVICE_KEY not found in .env")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)


# ── Helpers ───────────────────────────────────────────────────

def clean_val(v):
    """Convert NaN/float NaN to None for JSON compliance."""
    if v is None:
        return None
    if isinstance(v, float) and math.isnan(v):
        return None
    if isinstance(v, str) and v.strip() in ("", "nan", "NaN", "None"):
        return None
    return v

def clean_row(d: dict) -> dict:
    return {k: clean_val(v) for k, v in d.items()}

def batches(lst, n):
    for i in range(0, len(lst), n):
        yield lst[i:i + n]


# ── Step 1: Load school UUID map ──────────────────────────────

def load_school_map() -> dict:
    """Returns { espn_team_id (int) -> school UUID }"""
    resp = supabase.table("schools").select("id, espn_team_id").execute()
    return {
        row["espn_team_id"]: row["id"]
        for row in resp.data
        if row["espn_team_id"] is not None
    }


# ── Step 2: Ingest athletes ───────────────────────────────────

def ingest_athletes(df: pd.DataFrame) -> dict:
    """
    Upsert athletes master records.
    Returns { espn_athlete_id -> athlete UUID }
    """
    print("  Building athlete records...")

    records = []
    for _, row in df.iterrows():
        espn_id = clean_val(row.get("athlete_id"))
        if espn_id is None:
            continue
        try:
            espn_id = int(float(espn_id))
        except (ValueError, TypeError):
            continue

        records.append(clean_row({
            "espn_athlete_id":  espn_id,
            "espn_headshot":    row.get("headshot"),
            "full_name":        row.get("display_name") or row.get("player_name"),
            "first_name":       row.get("first_name"),
            "last_name":        row.get("last_name"),
            "short_name":       row.get("short_name"),
            "position":         row.get("position"),
            "position_raw":     row.get("position_raw"),
            "position_name":    row.get("position_name"),
            "pos_group":        row.get("pos_group"),
            "height":           row.get("height"),
            "weight":           row.get("weight"),
            "birth_city":       row.get("birth_city"),
            "birth_state":      row.get("birth_state"),
            "athlete_type":     "college",
            "data_source":      "espn",
            "source_confidence": 0.85,  # ESPN data, some lag expected
            "is_active":        True,
        }))

    # Deduplicate on espn_athlete_id
    seen = set()
    unique = []
    for r in records:
        if r["espn_athlete_id"] not in seen:
            seen.add(r["espn_athlete_id"])
            unique.append(r)

    print(f"  Upserting {len(unique):,} athletes in batches of {BATCH_SIZE}...")
    inserted = 0
    for batch in batches(unique, BATCH_SIZE):
        supabase.table("athletes").upsert(
            batch,
            on_conflict="espn_athlete_id"
        ).execute()
        inserted += len(batch)
        print(f"    {inserted:,} / {len(unique):,}", end="\r")

    print(f"\n  Done — {len(unique):,} athletes upserted")

    # Fetch back UUIDs
    print("  Fetching athlete UUIDs...")
    id_map = {}
    espn_ids = list(seen)
    for batch in batches(espn_ids, 500):
        resp = supabase.table("athletes").select("id, espn_athlete_id").in_(
            "espn_athlete_id", batch
        ).execute()
        for row in resp.data:
            id_map[row["espn_athlete_id"]] = row["id"]

    print(f"  Retrieved {len(id_map):,} UUIDs")
    return id_map


# ── Step 3: Ingest athlete_teams ──────────────────────────────

def ingest_athlete_teams(
    df: pd.DataFrame,
    athlete_id_map: dict,
    school_map: dict
) -> int:
    """
    Upsert athlete_teams records for 2026 season.
    Returns count of records processed.
    """
    print("  Building athlete_teams records...")

    records = []
    skipped = 0

    for _, row in df.iterrows():
        espn_id = clean_val(row.get("athlete_id"))
        if espn_id is None:
            skipped += 1
            continue
        try:
            espn_id = int(float(espn_id))
        except (ValueError, TypeError):
            skipped += 1
            continue

        athlete_uuid = athlete_id_map.get(espn_id)
        if not athlete_uuid:
            skipped += 1
            continue

        team_id_raw = clean_val(row.get("team_id"))
        school_uuid = None
        if team_id_raw is not None:
            try:
                school_uuid = school_map.get(int(float(team_id_raw)))
            except (ValueError, TypeError):
                pass

        class_val = clean_val(row.get("class"))
        if class_val == "nan":
            class_val = None

        records.append(clean_row({
            "athlete_id":        athlete_uuid,
            "school_id":         school_uuid,
            "season":            SEASON,
            "status":            "enrolled",
            "position":          row.get("position"),
            "jersey": str(int(float(row["jersey"]))) if clean_val(row.get("jersey")) is not None else None,
            "class":             class_val,
            "class_abbreviation": clean_val(row.get("class_abbreviation")),
            "experience_years": int(float(row["experience_years"])) if clean_val(
                row.get("experience_years")) is not None else None,
            "is_homegrown":      bool(row.get("is_homegrown", 1)),
            "data_source":       "espn",
        }))

    if skipped:
        print(f"  Skipped {skipped} rows (no ESPN ID or athlete UUID)")

    print(f"  Upserting {len(records):,} athlete_teams in batches of {BATCH_SIZE}...")
    inserted = 0
    for batch in batches(records, BATCH_SIZE):
        supabase.table("athlete_teams").upsert(batch).execute()
        inserted += len(batch)
        print(f"    {inserted:,} / {len(records):,}", end="\r")

    print(f"\n  Done — {len(records):,} athlete_teams upserted")
    return len(records)


# ── Step 4: Log to data_provenance ───────────────────────────

def log_provenance(records_fetched, records_inserted, notes=""):
    supabase.table("data_provenance").insert({
        "source":           "espn",
        "entity_type":      "athletes",
        "season":           SEASON,
        "records_fetched":  records_fetched,
        "records_inserted": records_inserted,
        "records_updated":  0,
        "records_removed":  0,
        "pulled_at":        datetime.now(timezone.utc).isoformat(),
        "notes":            notes,
        "raw_config":       {"csv": str(ROSTER_CSV), "batch_size": BATCH_SIZE},
    }).execute()
    print("  Provenance logged")


# ── Main ──────────────────────────────────────────────────────

def main():
    print(f"Loading {ROSTER_CSV}...")
    df = pd.read_csv(ROSTER_CSV, low_memory=False)
    print(f"  {len(df):,} rows loaded")

    print("\nLoading school UUID map from Supabase...")
    school_map = load_school_map()
    print(f"  {len(school_map)} schools with ESPN IDs mapped")

    print("\n── Ingesting athletes ────────────────────────────────")
    athlete_id_map = ingest_athletes(df)

    print("\n── Ingesting athlete_teams ───────────────────────────")
    at_count = ingest_athlete_teams(df, athlete_id_map, school_map)

    print("\n── Logging provenance ────────────────────────────────")
    log_provenance(
        records_fetched=len(df),
        records_inserted=len(athlete_id_map),
        notes=f"2026 roster ingestion. {at_count} athlete_team rows. School map: {len(school_map)} teams matched."
    )

    print(f"""
── Summary ───────────────────────────────────────────
  Rows in CSV:        {len(df):,}
  Athletes upserted:  {len(athlete_id_map):,}
  Athlete_teams:      {at_count:,}
  Schools mapped:     {len(school_map)}
──────────────────────────────────────────────────────
""")

    # FSU sanity check
    print("── FSU sanity check ──────────────────────────────────")
    fsu_school = next((v for k, v in {52: school_map.get(52)}.items() if v), None)
    if fsu_school:
        resp = supabase.table("athlete_teams").select(
            "athlete_id, position, class, athletes(full_name)"
        ).eq("school_id", fsu_school).eq("season", SEASON).limit(5).execute()
        for r in resp.data:
            name = r.get("athletes", {}).get("full_name", "?") if r.get("athletes") else "?"
            print(f"  {name} | {r.get('position')} | {r.get('class')}")
    else:
        print("  FSU not in school map — add espn_team_id=52 to schools table")


if __name__ == "__main__":
    main()