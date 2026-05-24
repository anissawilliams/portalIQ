"""
clean_roster_2026.py — Filter departed players, add incoming transfers
"""

import os
import requests
import pandas as pd
from pathlib import Path
from dotenv import load_dotenv
from rapidfuzz import fuzz

load_dotenv()

CFBD_API_KEY = os.environ.get("CFBD_API_KEY")
if not CFBD_API_KEY:
    raise ValueError("CFBD_API_KEY not found in environment")

DATA_DIR = Path(__file__).parent / "data"
ROSTER_CSV = DATA_DIR / "cfb_rosters_2026_clean.csv"

HEADERS = {
    "Authorization": f"Bearer {CFBD_API_KEY}",
    "Accept": "application/json",
}

FUZZY_THRESHOLD = 88

# ── Manual exclusions: known departures CFBD hasn't logged yet ─
# Format: { "ESPN team_location": ["Player Name", ...] }
MANUAL_EXCLUSIONS = {
    "Florida State": [
        "Tommy Castellanos",
    ],
}

# ── CFBD name → ESPN team_location mapping ─────────────────────
CFBD_TO_ESPN = {
    "Florida State": "Florida State",
    "Auburn": "Auburn",
    "Alabama": "Alabama",
    "Georgia": "Georgia",
    "Ohio State": "Ohio State",
    "Michigan": "Michigan",
    "LSU": "LSU",
    "Texas": "Texas",
    "Oklahoma": "Oklahoma",
    "Notre Dame": "Notre Dame",
    "Clemson": "Clemson",
    "USC": "USC",
    "Penn State": "Penn State",
    "Tennessee": "Tennessee",
    "Texas A&M": "Texas A&M",
    "Oregon": "Oregon",
    "Miami": "Miami",
    "Florida": "Florida",
    "Mississippi": "Ole Miss",
    "Ole Miss": "Ole Miss",
    "Mississippi State": "Mississippi State",
    "Kentucky": "Kentucky",
    "Arkansas": "Arkansas",
    "South Carolina": "South Carolina",
    "Vanderbilt": "Vanderbilt",
    "Missouri": "Missouri",
    "Georgia Tech": "Georgia Tech",
    "NC State": "NC State",
    "North Carolina": "North Carolina",
    "Virginia": "Virginia",
    "Virginia Tech": "Virginia Tech",
    "Duke": "Duke",
    "Wake Forest": "Wake Forest",
    "Boston College": "Boston College",
    "Syracuse": "Syracuse",
    "Pittsburgh": "Pittsburgh",
    "Louisville": "Louisville",
    "UCF": "UCF",
    "Cincinnati": "Cincinnati",
    "West Virginia": "West Virginia",
    "Iowa State": "Iowa State",
    "Kansas": "Kansas",
    "Kansas State": "Kansas State",
    "Oklahoma State": "Oklahoma State",
    "TCU": "TCU",
    "Baylor": "Baylor",
    "Texas Tech": "Texas Tech",
    "BYU": "BYU",
    "Colorado": "Colorado",
    "Utah": "Utah",
    "Washington": "Washington",
    "Washington State": "Washington State",
    "Oregon State": "Oregon State",
    "Arizona": "Arizona",
    "Arizona State": "Arizona State",
    "California": "California",
    "UCLA": "UCLA",
    "Stanford": "Stanford",
    "Iowa": "Iowa",
    "Wisconsin": "Wisconsin",
    "Minnesota": "Minnesota",
    "Nebraska": "Nebraska",
    "Northwestern": "Northwestern",
    "Illinois": "Illinois",
    "Indiana": "Indiana",
    "Purdue": "Purdue",
    "Rutgers": "Rutgers",
    "Maryland": "Maryland",
    "Michigan State": "Michigan State",
    "Boise State": "Boise State",
    "San Diego State": "San Diego State",
    "Fresno State": "Fresno State",
    "Air Force": "Air Force",
    "Army": "Army",
    "Navy": "Navy",
    "UAB": "UAB",
    "Marshall": "Marshall",
    "Western Kentucky": "Western Kentucky",
    "UTSA": "UTSA",
    "North Texas": "North Texas",
    "Rice": "Rice",
    "Tulsa": "Tulsa",
    "Tulane": "Tulane",
    "Memphis": "Memphis",
    "SMU": "SMU",
    "Houston": "Houston",
    "South Florida": "South Florida",
    "Temple": "Temple",
    "East Carolina": "East Carolina",
    "Charlotte": "Charlotte",
    "Florida Atlantic": "Florida Atlantic",
    "Florida International": "Florida International",
    "Middle Tennessee": "Middle Tennessee",
    "Old Dominion": "Old Dominion",
    "Southern Miss": "Southern Miss",
    "Louisiana": "Louisiana",
    "App State": "Appalachian State",
    "Appalachian State": "Appalachian State",
    "Georgia Southern": "Georgia Southern",
    "Coastal Carolina": "Coastal Carolina",
    "South Alabama": "South Alabama",
    "Troy": "Troy",
    "ULM": "Louisiana Monroe",
    "Georgia State": "Georgia State",
    "Texas State": "Texas State",
    "UTEP": "UTEP",
    "New Mexico": "New Mexico",
    "New Mexico State": "New Mexico State",
    "Nevada": "Nevada",
    "UNLV": "UNLV",
    "Hawaii": "Hawaii",
    "Wyoming": "Wyoming",
    "Colorado State": "Colorado State",
    "San Jose State": "San Jose State",
    "Utah State": "Utah State",
    "Ball State": "Ball State",
    "Bowling Green": "Bowling Green",
    "Buffalo": "Buffalo",
    "Central Michigan": "Central Michigan",
    "Eastern Michigan": "Eastern Michigan",
    "Kent State": "Kent State",
    "Miami (OH)": "Miami (OH)",
    "Northern Illinois": "Northern Illinois",
    "Ohio": "Ohio",
    "Toledo": "Toledo",
    "Western Michigan": "Western Michigan",
    "Akron": "Akron",
}

POSITION_GROUPS = {
    "QB": "QB", "RB": "RB", "WR": "WR", "TE": "TE",
    "OT": "OL", "OL": "OL", "OG": "OL", "C": "OL", "IOL": "OL",
    "DE": "DL", "DT": "DL", "DL": "DL", "NT": "DL", "EDGE": "DL",
    "LB": "LB", "ILB": "LB", "OLB": "LB",
    "CB": "DB", "S": "DB", "SS": "DB", "FS": "DB", "DB": "DB",
    "K": "ST", "P": "ST", "LS": "ST", "PK": "ST",
}

def pos_group(pos):
    return POSITION_GROUPS.get(str(pos).upper().strip(), "?")

def fuzzy_match(n1, n2):
    return fuzz.token_sort_ratio(str(n1).lower(), str(n2).lower()) >= FUZZY_THRESHOLD

def get_portal_2026():
    resp = requests.get(
        "https://api.collegefootballdata.com/player/portal",
        headers=HEADERS,
        params={"year": 2026}
    )
    resp.raise_for_status()
    data = resp.json()
    df = pd.DataFrame(data)
    df["full_name"] = df["firstName"].str.strip() + " " + df["lastName"].str.strip()
    df["pos_group"] = df["position"].apply(pos_group)
    print(f"  CFBD portal: {len(df):,} entries")
    return df


def clean_roster():
    print(f"Loading roster...")
    df = pd.read_csv(ROSTER_CSV, low_memory=False)
    print(f"  {len(df):,} players, {df['team_location'].nunique()} teams")

    print("\nFetching CFBD 2026 portal data...")
    portal = get_portal_2026()

    # Confirmed departures only (have a destination)
    departures = portal[
        portal["destination"].notna() &
        (portal["destination"].str.strip() != "") &
        (portal["origin"].notna())
    ].copy()
    print(f"  Confirmed departures: {len(departures):,}")

    # Build departure lookup: espn_team_location → list of {name, pos_group}
    departure_lookup = {}
    unmapped = set()
    for _, dep in departures.iterrows():
        cfbd_origin = str(dep["origin"]).strip()
        espn_loc = CFBD_TO_ESPN.get(cfbd_origin)
        if not espn_loc:
            unmapped.add(cfbd_origin)
            continue
        if espn_loc not in departure_lookup:
            departure_lookup[espn_loc] = []
        departure_lookup[espn_loc].append({
            "name": dep["full_name"],
            "pos_group": dep["pos_group"],
        })

    print(f"  Teams with departures in lookup: {len(departure_lookup)}")
    print(f"  FSU departures in lookup: {len(departure_lookup.get('Florida State', []))}")
    if unmapped:
        print(f"  Unmapped CFBD origins (not in CFBD_TO_ESPN): {sorted(unmapped)[:10]}")

    # ── Step 1: Remove departed players ───────────────────────
    print("\nRemoving departed players...")
    remove_indices = set()

    for idx, row in df.iterrows():
        team_loc = str(row["team_location"]).strip()
        player_name = str(row["display_name"]).strip()
        player_pos = pos_group(row.get("position", ""))

        # Check manual exclusions first
        manual = MANUAL_EXCLUSIONS.get(team_loc, [])
        if any(fuzzy_match(player_name, excl) for excl in manual):
            remove_indices.add(idx)
            continue

        # Check CFBD departures
        team_deps = departure_lookup.get(team_loc, [])
        for dep in team_deps:
            name_match = fuzzy_match(player_name, dep["name"])
            pos_match = (
                dep["pos_group"] == "?" or
                player_pos == "?" or
                dep["pos_group"] == player_pos
            )
            if name_match and pos_match:
                remove_indices.add(idx)
                break

    df_clean = df.drop(index=list(remove_indices)).copy()
    print(f"  Removed {len(remove_indices):,} departed players")

    # ── Step 2: Add incoming transfers ────────────────────────
    print("\nAdding incoming transfers...")

    arrivals = portal[
        portal["destination"].notna() &
        (portal["destination"].str.strip() != "")
    ].copy()

    added = []
    for _, arr in arrivals.iterrows():
        cfbd_dest = str(arr["destination"]).strip()
        espn_loc = CFBD_TO_ESPN.get(cfbd_dest)
        if not espn_loc:
            continue

        arr_name = arr["full_name"]
        arr_pos  = arr["pos_group"]

        team_roster = df_clean[df_clean["team_location"] == espn_loc]
        if team_roster.empty:
            continue

        # Check if already on roster
        already_there = any(
            fuzzy_match(arr_name, str(name))
            for name in team_roster["display_name"].values
        )
        if already_there:
            continue

        first = str(arr["firstName"]).strip()
        last  = str(arr["lastName"]).strip()
        sample = team_roster.iloc[0]

        new_row = {col: None for col in df.columns}
        new_row.update({
            "display_name":      arr_name,
            "first_name":        first,
            "last_name":         last,
            "full_name":         arr_name,
            "short_name":        f"{first[:1]}. {last}" if first else arr_name,
            "position":          str(arr["position"]),
            "season":            2026,
            "status":            "Active",
            "team":              sample["team"],
            "team_location":     espn_loc,
            "team_abbreviation": sample["team_abbreviation"],
            "team_id":           sample["team_id"],
            "team_nickname":     sample["team_nickname"],
            "headshot":          "",
            "is_homegrown":      0,
        })
        added.append(new_row)

    if added:
        additions_df = pd.DataFrame(added)
        df_clean = pd.concat([df_clean, additions_df], ignore_index=True)
        print(f"  Added {len(added):,} incoming transfers")
    else:
        print("  No new incoming transfers added")

    # ── Step 3: Save ──────────────────────────────────────────
    print(f"\nSaving...")
    print(f"  Before: {len(df):,}")
    print(f"  After:  {len(df_clean):,}")
    df_clean.to_csv(ROSTER_CSV, index=False)
    print(f"  Saved → {ROSTER_CSV}")

    # ── FSU sanity check ──────────────────────────────────────
    fsu = df_clean[df_clean["team_location"] == "Florida State"]
    print(f"\n── FSU sanity check: {len(fsu)} players ──")
    names = fsu["display_name"].tolist()
    checks = ["castellanos", "daniels", "kennedy", "weinberg", "chiumento", "blackwell", "robinson"]
    for c in checks:
        matches = [n for n in names if c in str(n).lower()]
        print(f"  '{c}': {matches if matches else 'NOT FOUND ✓'}")


if __name__ == "__main__":
    clean_roster()