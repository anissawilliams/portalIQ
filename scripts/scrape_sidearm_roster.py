"""
scrape_sidearm_roster.py — Scrape FBS rosters from Sidearm Sports sites
========================================================================
Uses Playwright to render JavaScript before scraping.

Run from backend/:
    python scrape_sidearm_roster.py              # FSU only (test)
    python scrape_sidearm_roster.py --teams fsu alabama georgia
    python scrape_sidearm_roster.py --all
"""

import os
import re
import time
import argparse
from dotenv import load_dotenv
from supabase import create_client, Client
from playwright.sync_api import sync_playwright

load_dotenv()

SUPABASE_URL = os.environ.get("SUPABASE_URL", "https://fpigpzmgqmzoxdknhetg.supabase.co")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_KEY")
SEASON = 2026

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

SCHOOLS = {
    "fsu":           ("Florida State Seminoles",  "https://seminoles.com/sports/football/roster"),
    "alabama":       ("Alabama Crimson Tide",      "https://rolltide.com/sports/football/roster"),
    "georgia":       ("Georgia Bulldogs",          "https://georgiadogs.com/sports/football/roster"),
    "clemson":       ("Clemson Tigers",            "https://clemsontigers.com/sports/football/roster"),
    "ohio-state":    ("Ohio State Buckeyes",       "https://ohiostatebuckeyes.com/sports/football/roster"),
    "michigan":      ("Michigan Wolverines",       "https://mgoblue.com/sports/football/roster"),
    "lsu":           ("LSU Tigers",               "https://lsusports.net/sports/football/roster"),
    "texas":         ("Texas Longhorns",           "https://texassports.com/sports/football/roster"),
    "penn-state":    ("Penn State Nittany Lions",  "https://gopsusports.com/sports/football/roster"),
    "tennessee":     ("Tennessee Volunteers",      "https://utsports.com/sports/football/roster"),
    "auburn":        ("Auburn Tigers",             "https://auburntigers.com/sports/football/roster"),
    "florida":       ("Florida Gators",            "https://floridagators.com/sports/football/roster"),
    "miami":         ("Miami Hurricanes",          "https://hurricanesports.com/sports/football/roster"),
    "notre-dame":    ("Notre Dame Fighting Irish", "https://und.com/sports/football/roster"),
    "north-carolina":("North Carolina Tar Heels",  "https://goheels.com/sports/football/roster"),
}

POSITION_MAP = {
    "QB": "QB", "RB": "RB", "WR": "WR", "TE": "TE",
    "OL": "IOL", "OG": "IOL", "C": "IOL", "IOL": "IOL",
    "OT": "OT", "T": "OT",
    "DE": "EDGE", "EDGE": "EDGE",
    "DL": "DL", "DT": "DL", "NT": "DL",
    "LB": "LB", "ILB": "LB", "OLB": "LB",
    "CB": "CB", "S": "S", "SS": "S", "FS": "S", "DB": "S",
    "K": "K", "P": "P", "LS": "LS", "PK": "K",
    "ATH": "ATH",
}

CLASS_MAP = {
    "fr": "Freshman", "r-fr": "Freshman", "so": "Sophomore", "r-so": "Sophomore",
    "jr": "Junior", "r-jr": "Junior", "sr": "Senior", "r-sr": "Senior",
    "gr": "Graduate", "5th": "Graduate", "graduate": "Graduate",
}

def normalize_position(raw):
    if not raw:
        return "ATH"
    return POSITION_MAP.get(raw.upper().strip(), raw.upper().strip())

def normalize_class(raw):
    if not raw:
        return "Sophomore"
    key = raw.lower().strip().replace(".", "").replace(" ", "-")
    return CLASS_MAP.get(key, raw.strip().title())

def parse_height_to_inches(raw):
    if not raw:
        return None
    m = re.search(r"(\d+)['\-\s]+(\d+)", str(raw))
    if m:
        return str(int(m.group(1)) * 12 + int(m.group(2)))
    return None

def scrape_with_playwright(url: str, team_name: str) -> list[dict]:
    """Render the page with Playwright and extract player data."""
    print(f"  Launching browser for {team_name}...")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        try:
            page.goto(url, wait_until="networkidle", timeout=30000)
        except Exception as e:
            print(f"  Timeout/error loading page: {e}")
            # Try with just domcontentloaded
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=20000)
                page.wait_for_timeout(3000)
            except Exception as e2:
                print(f"  Failed completely: {e2}")
                browser.close()
                return []

        # Wait a bit for Vue/React to render
        page.wait_for_timeout(2000)

        # Debug: find roster-related elements
        html = page.content()
        print(f"  Page rendered: {len(html):,} chars")

        # Try to find player cards via various selectors
        selectors_to_try = [
            "[data-test-id='s-person-card-list__root']",
            "li.s-person-details",
            "[class*='s-person-card--list']",
            "[class*='roster'][class*='player']",
            "li[class*='roster']",
            "div[class*='roster'][class*='item']",
            "li.roster__item",
        ]

        players_html = []
        for sel in selectors_to_try:
            els = page.query_selector_all(sel)
            if els:
                print(f"  Found {len(els)} elements with selector: {sel}")
                # Print outer HTML of first 2 elements to understand structure
                print("  Sample element HTML:")
                for el in els[:2]:
                    try:
                        print(el.evaluate("el => el.outerHTML")[:600])
                        print("---")
                    except:
                        pass
                players_html = els
                break

        if not players_html:
            # Last resort: dump class names to help debug
            print("  No player elements found. Dumping sample classes...")
            classes = page.evaluate("""
                () => {
                    const els = document.querySelectorAll('[class]');
                    const seen = new Set();
                    const out = [];
                    for (const el of els) {
                        const c = el.className;
                        if (typeof c === 'string' && !seen.has(c)) {
                            seen.add(c);
                            if (c.toLowerCase().includes('roster') ||
                                c.toLowerCase().includes('player') ||
                                c.toLowerCase().includes('athlete') ||
                                c.toLowerCase().includes('person')) {
                                out.push(el.tagName + ': ' + c.substring(0, 100));
                            }
                        }
                        if (out.length > 30) break;
                    }
                    return out;
                }
            """)
            for c in classes:
                print(f"    {c}")
            browser.close()
            return []

        players = []
        for el in players_html:
            try:
                name_el = el.query_selector("[data-test-id='s-person-details__personal-single-line-person-link'] h3")
                pos_el  = el.query_selector("[data-test-id='s-person-details__bio-stats-person-position-short']")
                yr_el   = el.query_selector("[data-test-id='s-person-details__bio-stats-person-title']")
                ht_el   = el.query_selector("[data-test-id='s-person-details__bio-stats-person-season']")
                wt_el   = el.query_selector("[data-test-id='s-person-details__bio-stats-person-weight']")
                home_el = el.query_selector("[data-test-id='s-person-card-list__content-location-person-hometown']")
                jsy_el  = el.query_selector("[data-test-id='s-stamp__root']")

                name_text = name_el.inner_text().strip() if name_el else ""
                pos_text  = pos_el.inner_text().strip()  if pos_el  else ""
                yr_text   = yr_el.inner_text().strip()   if yr_el   else ""
                ht_text   = ht_el.inner_text().strip()   if ht_el   else ""
                wt_text   = wt_el.inner_text().strip()   if wt_el   else ""
                home_text = home_el.inner_text().strip() if home_el else ""
                jsy_text  = jsy_el.inner_text().strip()  if jsy_el  else ""

                # Clean up — each field has a sr-only label prefix, strip it
                # e.g. "Position\nDB" → "DB", "Academic Year\nSr." → "Sr."
                def strip_label(text):
                    parts = text.strip().split("\n")
                    return parts[-1].strip() if parts else text.strip()

                pos_text  = strip_label(pos_text)
                yr_text   = strip_label(yr_text)
                ht_text   = strip_label(ht_text)
                wt_text   = strip_label(wt_text)
                home_text = strip_label(home_text)
                jsy_text  = re.sub(r"[^\d]", "", jsy_text)

                if not name_text or len(name_text) < 2:
                    continue
                if any(w in name_text.lower() for w in ["coach", "staff", "coordinator", "full bio", "jersey"]):
                    continue
                # Skip coaches — they have no jersey number
                if not jsy_text:
                    continue

                players.append({
                    "full_name":    name_text,
                    "jersey":       jsy_text,
                    "position_raw": pos_text,
                    "position":     normalize_position(pos_text),
                    "class_raw":    yr_text,
                    "class":        normalize_class(yr_text),
                    "height":       parse_height_to_inches(ht_text),
                    "weight":       re.sub(r"[^\d]", "", wt_text) or None,
                    "hometown":     home_text,
                    "team_name":    team_name,
                })
            except Exception as e:
                continue

        browser.close()
        print(f"  Extracted {len(players)} players")
        return players


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


def upsert_player(player: dict, school_id: str) -> bool:
    name = player["full_name"]
    parts = name.split(" ", 1)
    first = parts[0]
    last = parts[1] if len(parts) > 1 else ""

    athlete_data = {
        "full_name":    name,
        "first_name":   first,
        "last_name":    last,
        "short_name":   f"{first[0]}. {last}" if last else name,
        "position":     player["position"],
        "position_raw": player["position_raw"],
        "data_source":  "manual",
        "is_active":    True,
    }
    if player.get("height"):
        athlete_data["height"] = player["height"]
    if player.get("weight"):
        athlete_data["weight"] = player["weight"]

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

    at_data = {
        "athlete_id":   athlete_id,
        "school_id":    school_id,
        "season":       SEASON,
        "position":     player["position"],
        "jersey":       player["jersey"] or None,
        "class":        player["class"],
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


def scrape_team(slug: str, dry_run: bool = True):
    team_name, url = SCHOOLS[slug]
    print(f"\n── {team_name} ──────────────────────────────────")

    players = scrape_with_playwright(url, team_name)
    if not players:
        print(f"  No players scraped")
        return 0

    # Always save to CSV first
    import pandas as pd
    from pathlib import Path
    out_path = Path(f"data/sidearm_{slug}_2026.csv")
    df = pd.DataFrame(players)
    df.to_csv(out_path, index=False)
    print(f"  Saved {len(players)} rows → {out_path}")
    print(f"\n  Sample (first 10):")
    print(df[["full_name", "jersey", "position", "class", "height", "weight"]].head(10).to_string())

    if dry_run:
        print(f"\n  DRY RUN — not upserting. Run with --upsert to write to DB.")
        return 0

    school_id = get_school_uuid(team_name)
    if not school_id:
        print(f"  WARNING: No school UUID found for '{team_name}' — skipping upsert")
        return 0

    print(f"\n  Upserting {len(players)} players...")
    success = sum(1 for p in players if upsert_player(p, school_id))
    print(f"  Done: {success}/{len(players)} upserted")
    return success


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--teams", nargs="+", choices=list(SCHOOLS.keys()))
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--upsert", action="store_true",
                        help="Write to Supabase (default is dry run — CSV only)")
    args = parser.parse_args()

    if args.list:
        for slug, (name, url) in SCHOOLS.items():
            print(f"  {slug:<20} {name}")
        return

    teams = list(SCHOOLS.keys()) if args.all else (args.teams or ["fsu"])
    dry_run = not args.upsert

    if dry_run:
        print("DRY RUN mode — saving CSV only. Use --upsert to write to DB.\n")

    total = 0
    for slug in teams:
        total += scrape_team(slug, dry_run=dry_run)
        time.sleep(1)

    print(f"\n── Done. Check data/sidearm_*_2026.csv ──")


if __name__ == "__main__":
    main()