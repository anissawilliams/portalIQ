"""
ingest_portal_2026.py — Push CFBD portal entries into Supabase
==============================================================
Fetches 2026 transfer portal data from CFBD API and inserts into
public.portal_entries, linking to schools and athletes where possible.

Run from backend/:
    python3 ingest_portal_2026.py
"""

import os
import requests
import pandas as pd
from datetime import datetime, timezone
from dotenv import load_dotenv
from supabase import create_client, Client
from rapidfuzz import fuzz

load_dotenv()

SUPABASE_URL = os.environ.get("SUPABASE_URL", "https://fpigpzmgqmzoxdknhetg.supabase.co")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_KEY")
CFBD_API_KEY = os.environ.get("CFBD_API_KEY")
SEASON = 2026
BATCH_SIZE = 100
FUZZY_THRESHOLD = 88

if not SUPABASE_KEY:
    raise ValueError("SUPABASE_SERVICE_KEY not found in .env")
if not CFBD_API_KEY:
    raise ValueError("CFBD_API_KEY not found in .env")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

CFBD_HEADERS = {
    "Authorization": f"Bearer {CFBD_API_KEY}",
    "Accept": "application/json",
}


def batches(lst, n):
    for i in range(0, len(lst), n):
        yield lst[i:i + n]


# ── Load reference maps ───────────────────────────────────────

def load_school_map() -> dict:
    """{ cfbd_name -> { id, espn_team_id } }"""
    resp = supabase.table("schools").select("id, cfbd_name, espn_team_id").execute()
    return {
        row["cfbd_name"]: row
        for row in resp.data
        if row["cfbd_name"]
    }


def load_athlete_map() -> dict:
    """{ full_name.lower() -> athlete UUID } for fuzzy matching"""
    all_rows = []
    page = 0
    page_size = 1000
    while True:
        resp = supabase.table("athletes").select("id, full_name")\
            .range(page * page_size, (page + 1) * page_size - 1).execute()
        all_rows.extend(resp.data)
        if len(resp.data) < page_size:
            break
        page += 1
    return {
        row["full_name"].lower(): row["id"]
        for row in all_rows
        if row["full_name"]
    }

# ── Fetch CFBD portal data ────────────────────────────────────

def fetch_portal(year: int) -> list:
    resp = requests.get(
        "https://api.collegefootballdata.com/player/portal",
        headers=CFBD_HEADERS,
        params={"year": year}
    )
    resp.raise_for_status()
    data = resp.json()
    print(f"  CFBD returned {len(data):,} portal entries")
    return data


# ── Fuzzy athlete matching ────────────────────────────────────

def find_athlete_id(full_name: str, athlete_map: dict) -> str | None:
    """Fuzzy match portal player name to athletes table."""
    name_lower = full_name.lower()

    # Exact match first
    if name_lower in athlete_map:
        return athlete_map[name_lower]

    # Fuzzy fallback
    best_score = 0
    best_id = None
    for db_name, uid in athlete_map.items():
        score = fuzz.token_sort_ratio(name_lower, db_name)
        if score > best_score:
            best_score = score
            best_id = uid

    return best_id if best_score >= FUZZY_THRESHOLD else None


# ── Build portal entry records ────────────────────────────────

def build_records(portal_data: list, school_map: dict, athlete_map: dict) -> list:
    records = []
    unmatched_schools = set()
    matched_athletes = 0

    for entry in portal_data:
        first = str(entry.get("firstName", "")).strip()
        last = str(entry.get("lastName", "")).strip()
        full_name = f"{first} {last}".strip()
        origin = str(entry.get("origin", "")).strip()
        dest = str(entry.get("destination") or "").strip()
        position = entry.get("position")
        stars = entry.get("stars")
        rating = entry.get("rating")
        eligibility = entry.get("eligibility")
        transfer_date = entry.get("transferDate")

        # School matching
        origin_school = school_map.get(origin)
        dest_school = school_map.get(dest) if dest else None

        if origin and not origin_school:
            unmatched_schools.add(origin)

        # Portal status
        if dest:
            status = "committed"
        else:
            status = "entered"

        # Athlete matching
        athlete_id = find_athlete_id(full_name, athlete_map)
        if athlete_id:
            matched_athletes += 1

        # Transfer date
        parsed_date = None
        if transfer_date:
            try:
                parsed_date = datetime.fromisoformat(
                    transfer_date.replace("Z", "+00:00")
                ).isoformat()
            except Exception:
                pass

        records.append({
            "season": SEASON,
            "athlete_id": athlete_id,
            "full_name": full_name,
            "position": position,
            "origin_school_id": origin_school["id"] if origin_school else None,
            "origin_school_name": origin or "",
            "dest_school_id": dest_school["id"] if dest_school else None,
            "dest_school_name": dest or None,
            "status": status,
            "transfer_date": parsed_date,
            "stars": int(stars) if stars else None,
            "rating": float(rating) if rating else None,
            "eligibility": eligibility,
            "data_source": "cfbd",
            "last_verified": datetime.now(timezone.utc).isoformat(),
        })

    print(f"  Athletes matched: {matched_athletes:,} / {len(portal_data):,}")
    if unmatched_schools:
        print(f"  Unmatched origin schools (FCS/D2): {len(unmatched_schools)}")

    return records


# ── Ingest ────────────────────────────────────────────────────

def ingest(records: list) -> int:
    print(f"\n  Inserting {len(records):,} portal entries in batches of {BATCH_SIZE}...")

    # Clear existing 2026 portal entries first (clean re-run)
    supabase.table("portal_entries").delete().eq("season", SEASON).execute()
    print("  Cleared existing 2026 portal entries")

    inserted = 0
    for batch in batches(records, BATCH_SIZE):
        supabase.table("portal_entries").insert(batch).execute()
        inserted += len(batch)
        print(f"    {inserted:,} / {len(records):,}", end="\r")

    print(f"\n  Done — {inserted:,} portal entries inserted")
    return inserted


# ── Log provenance ────────────────────────────────────────────

def log_provenance(fetched, inserted):
    supabase.table("data_provenance").insert({
        "source": "cfbd",
        "entity_type": "portal_entries",
        "season": SEASON,
        "records_fetched": fetched,
        "records_inserted": inserted,
        "records_updated": 0,
        "records_removed": 0,
        "pulled_at": datetime.now(timezone.utc).isoformat(),
        "notes": f"CFBD 2026 transfer portal. {inserted} entries ingested.",
        "raw_config": {"year": SEASON, "batch_size": BATCH_SIZE},
    }).execute()
    print("  Provenance logged")


# ── Main ──────────────────────────────────────────────────────

def main():
    print("Loading reference maps from Supabase...")
    school_map = load_school_map()
    athlete_map = load_athlete_map()
    print(f"  {len(school_map)} schools, {len(athlete_map):,} athletes loaded")

    print(f"\nFetching CFBD {SEASON} portal data...")
    portal_data = fetch_portal(SEASON)

    print("\nBuilding portal entry records...")
    records = build_records(portal_data, school_map, athlete_map)

    print("\n── Ingesting portal entries ──────────────────────────")
    inserted = ingest(records)

    print("\n── Logging provenance ────────────────────────────────")
    log_provenance(len(portal_data), inserted)

    # Sanity check — FSU departures
    print("\n── FSU departure sanity check ────────────────────────")
    fsu = next((v for k, v in school_map.items() if k == "Florida State"), None)
    if fsu:
        resp = supabase.table("portal_entries") \
            .select("full_name, position, dest_school_name, status") \
            .eq("origin_school_id", fsu["id"]) \
            .eq("season", SEASON) \
            .order("full_name") \
            .execute()
        print(f"  FSU departures: {len(resp.data)}")
        for r in resp.data[:10]:
            print(f"    {r['full_name']:<25} | {r['position']:<6} | → {r['dest_school_name'] or 'uncommitted'}")
    else:
        print("  FSU not found in school map")

    print(f"""
── Summary ───────────────────────────────────────────
  CFBD entries fetched:   {len(portal_data):,}
  Portal entries inserted:{inserted:,}
  Schools mapped:         {len(school_map)}
  Athletes matched:       see above
──────────────────────────────────────────────────────
""")


if __name__ == "__main__":
    main()