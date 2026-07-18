"""
seed_schools.py — Populate all 148 FBS schools in Supabase
===========================================================
Reads teams_2026_clean.csv and upserts into public.schools.
Matches existing rows by espn_team_id (update) or inserts new ones.
Safe to re-run.

Run from backend/:
    python3 seed_schools.py
"""

import os
import math
import pandas as pd
from pathlib import Path
from dotenv import load_dotenv
from supabase import create_client, Client

load_dotenv()

SUPABASE_URL = os.environ.get("SUPABASE_URL", "https://fpigpzmgqmzoxdknhetg.supabase.co")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_KEY")
DATA_DIR     = Path(__file__).parent / "data"
TEAMS_CSV    = DATA_DIR / "teams_2026_clean.csv"

if not SUPABASE_KEY:
    raise ValueError("SUPABASE_SERVICE_KEY not found in .env")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# CFBD name mapping — ESPN location → CFBD plain name
# Used so cross-source joins work later
CFBD_NAME_MAP = {
    "Florida State":    "Florida State",
    "Auburn":           "Auburn",
    "UAB":              "UAB",
    "South Alabama":    "South Alabama",
    "Arkansas":         "Arkansas",
    "Arizona State":    "Arizona State",
    "Arizona":          "Arizona",
    "San Diego State":  "San Diego State",
    "Alabama":          "Alabama",
    "Georgia":          "Georgia",
    "Ohio State":       "Ohio State",
    "Michigan":         "Michigan",
    "LSU":              "LSU",
    "Texas":            "Texas",
    "Oklahoma":         "Oklahoma",
    "Notre Dame":       "Notre Dame",
    "Clemson":          "Clemson",
    "USC":              "USC",
    "Penn State":       "Penn State",
    "Tennessee":        "Tennessee",
    "Texas A&M":        "Texas A&M",
    "Oregon":           "Oregon",
    "Miami":            "Miami",
    "Florida":          "Florida",
    "Ole Miss":         "Ole Miss",
    "Mississippi State":"Mississippi State",
    "Kentucky":         "Kentucky",
    "South Carolina":   "South Carolina",
    "Vanderbilt":       "Vanderbilt",
    "Missouri":         "Missouri",
    "Georgia Tech":     "Georgia Tech",
    "NC State":         "NC State",
    "North Carolina":   "North Carolina",
    "Virginia":         "Virginia",
    "Virginia Tech":    "Virginia Tech",
    "Duke":             "Duke",
    "Wake Forest":      "Wake Forest",
    "Boston College":   "Boston College",
    "Syracuse":         "Syracuse",
    "Pittsburgh":       "Pittsburgh",
    "Louisville":       "Louisville",
    "UCF":              "UCF",
    "Cincinnati":       "Cincinnati",
    "West Virginia":    "West Virginia",
    "Iowa State":       "Iowa State",
    "Kansas":           "Kansas",
    "Kansas State":     "Kansas State",
    "Oklahoma State":   "Oklahoma State",
    "TCU":              "TCU",
    "Baylor":           "Baylor",
    "Texas Tech":       "Texas Tech",
    "BYU":              "BYU",
    "Colorado":         "Colorado",
    "Utah":             "Utah",
    "Washington":       "Washington",
    "Washington State": "Washington State",
    "Oregon State":     "Oregon State",
    "California":       "California",
    "UCLA":             "UCLA",
    "Stanford":         "Stanford",
    "Iowa":             "Iowa",
    "Wisconsin":        "Wisconsin",
    "Minnesota":        "Minnesota",
    "Nebraska":         "Nebraska",
    "Northwestern":     "Northwestern",
    "Illinois":         "Illinois",
    "Indiana":          "Indiana",
    "Purdue":           "Purdue",
    "Rutgers":          "Rutgers",
    "Maryland":         "Maryland",
    "Michigan State":   "Michigan State",
    "Boise State":      "Boise State",
    "Fresno State":     "Fresno State",
    "Air Force":        "Air Force",
    "Army":             "Army",
    "Navy":             "Navy",
    "Marshall":         "Marshall",
    "Western Kentucky": "Western Kentucky",
    "UTSA":             "UTSA",
    "North Texas":      "North Texas",
    "Rice":             "Rice",
    "Tulsa":            "Tulsa",
    "Tulane":           "Tulane",
    "Memphis":          "Memphis",
    "SMU":              "SMU",
    "Houston":          "Houston",
    "South Florida":    "South Florida",
    "East Carolina":    "East Carolina",
    "Charlotte":        "Charlotte",
    "Florida Atlantic": "Florida Atlantic",
    "FIU":              "Florida International",
    "Middle Tennessee": "Middle Tennessee",
    "Old Dominion":     "Old Dominion",
    "Southern Miss":    "Southern Miss",
    "Louisiana":        "Louisiana",
    "Appalachian State":"Appalachian State",
    "Georgia Southern": "Georgia Southern",
    "Coastal Carolina": "Coastal Carolina",
    "South Alabama":    "South Alabama",
    "Troy":             "Troy",
    "Louisiana Monroe": "ULM",
    "Georgia State":    "Georgia State",
    "Texas State":      "Texas State",
    "UTEP":             "UTEP",
    "New Mexico":       "New Mexico",
    "New Mexico State": "New Mexico State",
    "Nevada":           "Nevada",
    "UNLV":             "UNLV",
    "Hawaii":           "Hawaii",
    "Wyoming":          "Wyoming",
    "Colorado State":   "Colorado State",
    "San José State":   "San Jose State",
    "Utah State":       "Utah State",
    "Ball State":       "Ball State",
    "Bowling Green":    "Bowling Green",
    "Buffalo":          "Buffalo",
    "Central Michigan": "Central Michigan",
    "Eastern Michigan": "Eastern Michigan",
    "Kent State":       "Kent State",
    "Miami (OH)":       "Miami (OH)",
    "Northern Illinois":"Northern Illinois",
    "Ohio":             "Ohio",
    "Toledo":           "Toledo",
    "Western Michigan": "Western Michigan",
    "Akron":            "Akron",
    "Sacramento State": "Sacramento State",
}


def clean_color(c):
    if not c or (isinstance(c, float) and math.isnan(c)):
        return None
    c = str(c).strip()
    if not c.startswith("#"):
        c = f"#{c}"
    return c.upper()


def main():
    print(f"Loading {TEAMS_CSV}...")
    df = pd.read_csv(TEAMS_CSV)
    print(f"  {len(df)} teams loaded")

    records = []
    for _, row in df.iterrows():
        location = str(row.get("location", "")).strip()
        name     = str(row.get("display_name", "")).strip()
        abbrev   = str(row.get("abbreviation", "")).strip()
        nickname = str(row.get("nickname", "")).strip()
        team_id  = row.get("team_id")

        try:
            espn_id = int(float(team_id))
        except (ValueError, TypeError):
            print(f"  Skipping {name} — bad team_id: {team_id}")
            continue

        records.append({
            "name":           name,
            "location":       location,
            "abbreviation":   abbrev,
            "nickname":       nickname,
            "espn_team_id":   espn_id,
            "cfbd_name":      CFBD_NAME_MAP.get(location, location),
            "primary_color":  clean_color(row.get("color")),
            "secondary_color": clean_color(row.get("alternate_color")),
            "classification": "FBS",
            "league":         "NCAA",
            "sport":          "football",
            "is_active":      True,
        })

    print(f"  Built {len(records)} school records")
    print(f"\nUpserting into Supabase...")

    # Upsert on espn_team_id
    # For existing rows (FSU, Miami, Clemson, Alabama) this will update them
    # For new rows it will insert
    batch_size = 50
    inserted = 0
    for i in range(0, len(records), batch_size):
        batch = records[i:i + batch_size]
        supabase.table("schools").upsert(
            batch,
            on_conflict="espn_team_id"
        ).execute()
        inserted += len(batch)
        print(f"  {inserted} / {len(records)}", end="\r")

    print(f"\n  Done — {len(records)} spchools upserted")

    # Verify
    resp = supabase.table("schools").select("id, name, espn_team_id, cfbd_name").order("name").execute()
    print(f"\n  Schools in DB: {len(resp.data)}")
    print("\n  Sample:")
    for r in resp.data[:8]:
        print(f"    ESPN {r['espn_team_id']:>4} | {r['name']:<35} | CFBD: {r['cfbd_name']}")


if __name__ == "__main__":
    main()