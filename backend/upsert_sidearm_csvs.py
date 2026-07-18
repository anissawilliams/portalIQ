"""
upsert_sidearm_csvs.py — Load scraped Sidearm CSVs into Supabase
=================================================================
Reads all data/sidearm_*_2026.csv files and upserts into:
  - athletes (name, position, height, weight)
  - athlete_teams (school_id, season=2026, position, class)

ESPN headshots are preserved — this script never touches headshot fields.
Coaches are filtered out (no jersey number).

Run from backend/:
    python upsert_sidearm_csvs.py              # all CSVs in data/
    python upsert_sidearm_csvs.py --teams fsu alabama
    python upsert_sidearm_csvs.py --dry-run    # print stats only
"""

import os
import re
import argparse
import pandas as pd
from pathlib import Path
from dotenv import load_dotenv
from supabase import create_client, Client

load_dotenv()

SUPABASE_URL = os.environ.get("SUPABASE_URL", "https://fpigpzmgqmzoxdknhetg.supabase.co")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_KEY")
SEASON = 2026
DATA_DIR = Path("data")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# Slug → full team name (must match schools.name in DB)
TEAM_NAMES = {
    "fsu":            "Florida State Seminoles",
    "alabama":        "Alabama Crimson Tide",
    "georgia":        "Georgia Bulldogs",
    "clemson":        "Clemson Tigers",
    "ohio-state":     "Ohio State Buckeyes",
    "michigan":       "Michigan Wolverines",
    "lsu":            "LSU Tigers",
    "texas":          "Texas Longhorns",
    "penn-state":     "Penn State Nittany Lions",
    "tennessee":      "Tennessee Volunteers",
    "auburn":         "Auburn Tigers",
    "florida":        "Florida Gators",
    "miami":          "Miami Hurricanes",
    "notre-dame":     "Notre Dame Fighting Irish",
    "north-carolina": "North Carolina Tar Heels",
}


def get_school_uuid(team_name: str) -> str | None:
    resp = (
        supabase.table("schools")
        .select("id, name")
        .ilike("name", f"%{team_name.split()[0]}%")
        .execute()
    )
    if not resp.data:
        return None
    for row in resp.data:
        if row["name"].lower() == team_name.lower():
            return row["id"]
    return resp.data[0]["id"]


def upsert_player(row: dict, school_id: str) -> bool:
    name = str(row.get("full_name", "")).strip()
    if not name or len(name) < 2:
        return False

    # Skip coaches — no jersey
    jersey = str(row.get("jersey", "")).strip()
    if not jersey:
        return False

    parts = name.split(" ", 1)
    first = parts[0]
    last = parts[1] if len(parts) > 1 else ""

    position = str(row.get("position", "ATH")).strip() or "ATH"
    cls = str(row.get("class", "")).strip() or "Sophomore"
    height = str(row.get("height", "")).strip() or None
    weight = str(row.get("weight", "")).strip() or None

    # Strip "POSITION " prefix (some Sidearm schools)
    if position.upper().startswith("POSITION "):
        position = position[9:].strip()

    # Normalize position abbreviations
    POSITION_MAP = {
        "DEFENSIVE LINE": "DL", "DEFENSIVE LINEMAN": "DL",
        "LINEBACKER": "LB", "DEFENSIVE BACK": "S",
        "WIDE RECEIVER": "WR", "RUNNING BACK": "RB",
        "QUARTERBACK": "QB", "TIGHT END": "TE",
        "OFFENSIVE LINE": "IOL", "OFFENSIVE LINEMAN": "IOL",
        "OFFENSIVE TACKLE": "OT", "LONG SNAPPER": "LS",
        "PUNTER": "P", "KICKER": "K", "SAFETY": "S",
        "CORNERBACK": "CB", "EDGE": "EDGE", "JACK": "EDGE",
    }
    position = POSITION_MAP.get(position.upper(), position.upper())

    # Strip "Academic Year " prefix and normalize class
    if cls.upper().startswith("ACADEMIC YEAR "):
        cls = cls[14:].strip()

    CLASS_MAP = {
        "FR": "Freshman", "R-FR": "Freshman", "SO": "Sophomore",
        "R-SO": "Sophomore", "JR": "Junior", "R-JR": "Junior",
        "SR": "Senior", "R-SR": "Senior", "GR": "Graduate",
        "5TH": "Graduate", "GRADUATE": "Graduate",
    }
    cls = CLASS_MAP.get(cls.upper().replace(".", "").replace("-", "-"), cls)

    # Clean height/weight
    if height and not re.match(r"^\d+$", height):
        height = None
    if weight and not re.match(r"^\d+$", weight):
        weight = None

    athlete_data = {
        "full_name":    name,
        "first_name":   first,
        "last_name":    last,
        "short_name":   f"{first[0]}. {last}" if last else name,
        "position":     position,
        "data_source":  "manual",
        "is_active":    True,
    }
    if height:
        athlete_data["height"] = height
    if weight:
        athlete_data["weight"] = weight

    # Check if athlete exists
    existing = (
        supabase.table("athletes")
        .select("id")
        .ilike("full_name", name)
        .execute()
    )

    if existing.data:
        athlete_id = existing.data[0]["id"]
        supabase.table("athletes").update(athlete_data).eq("id", athlete_id).execute()
    else:
        result = supabase.table("athletes").insert(athlete_data).execute()
        if not result.data:
            return False
        athlete_id = result.data[0]["id"]

    # Upsert athlete_teams
    at_data = {
        "athlete_id":   athlete_id,
        "school_id":    school_id,
        "season":       SEASON,
        "position":     position,
        "jersey":       jersey or None,
        "class":        cls,
        "data_source":  "manual",
        "is_homegrown": True,
        "status":       "enrolled",
    }

    existing_at = (
        supabase.table("athlete_teams")
        .select("id")
        .eq("athlete_id", athlete_id)
        .eq("school_id", school_id)
        .eq("season", SEASON)
        .execute()
    )

    if existing_at.data:
        supabase.table("athlete_teams").update(at_data).eq("id", existing_at.data[0]["id"]).execute()
    else:
        supabase.table("athlete_teams").insert(at_data).execute()

    return True


def upsert_csv(csv_path: Path, dry_run: bool = False) -> tuple[int, int]:
    """Returns (attempted, succeeded)."""
    slug = csv_path.stem.replace("sidearm_", "").replace("_2026", "")
    team_name = TEAM_NAMES.get(slug)

    if not team_name:
        print(f"  WARNING: No team name mapping for slug '{slug}' — skipping")
        return 0, 0

    df = pd.read_csv(csv_path)
    # Filter out coaches (no jersey)
    df = df[df["jersey"].notna() & (df["jersey"].astype(str).str.strip() != "")]
    df = df[df["full_name"].notna() & (df["full_name"].astype(str).str.len() > 2)]

    print(f"\n── {team_name} ({slug}) ──────────────────────────")
    print(f"  CSV rows after filtering: {len(df)}")

    if dry_run:
        print(f"  DRY RUN — skipping upsert")
        print(f"  Sample:")
        print(df[["full_name", "jersey", "position", "class"]].head(5).to_string())
        return len(df), 0

    school_id = get_school_uuid(team_name)
    if not school_id:
        print(f"  WARNING: No school UUID found for '{team_name}' — skipping")
        return len(df), 0

    success = 0
    for _, row in df.iterrows():
        if upsert_player(row.to_dict(), school_id):
            success += 1

    print(f"  Upserted: {success}/{len(df)}")
    return len(df), success


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--teams", nargs="+", help="Team slugs to process (e.g. fsu alabama)")
    parser.add_argument("--dry-run", action="store_true", help="Print stats without writing to DB")
    args = parser.parse_args()

    if args.teams:
        csv_files = [DATA_DIR / f"sidearm_{slug}_2026.csv" for slug in args.teams]
        csv_files = [f for f in csv_files if f.exists()]
    else:
        csv_files = sorted(DATA_DIR.glob("sidearm_*_2026.csv"))

    if not csv_files:
        print("No sidearm CSV files found in data/. Run scrape_sidearm_roster.py first.")
        return

    print(f"Found {len(csv_files)} CSV files to process")
    if args.dry_run:
        print("DRY RUN mode — no DB writes\n")

    total_attempted = 0
    total_succeeded = 0

    for csv_path in csv_files:
        attempted, succeeded = upsert_csv(csv_path, dry_run=args.dry_run)
        total_attempted += attempted
        total_succeeded += succeeded

    print(f"\n── Complete ──────────────────────────────────────")
    if not args.dry_run:
        print(f"  Total upserted: {total_succeeded}/{total_attempted}")
    else:
        print(f"  Total rows found: {total_attempted}")
        print(f"  Run without --dry-run to write to DB")


if __name__ == "__main__":
    main()