"""
scrape_ea_ratings.py — Scrape CF27 player ratings from cfblabs.com
===================================================================
Scrapes the CFBLabs player ratings database (11,728 players, full OVR + attributes).
Uses Playwright for JS-rendered content. YOSO pattern - run once, cache the CSV.

Output: data/ea_cf27_ratings.csv
  Columns: name, team, position, ovr, spd, str, agi, awr, acc, jmp, cod

Usage:
    pip install playwright
    playwright install chromium
    python3 scrape_ea_ratings.py
    python3 scrape_ea_ratings.py --team "Florida State"  # filter full database
    python3 scrape_ea_ratings.py --legacy-team-page --team "Florida State"
"""

import argparse
import re
import time
import pandas as pd
from pathlib import Path
from playwright.sync_api import Page, sync_playwright, TimeoutError as PlaywrightTimeout

OUTPUT = Path(__file__).parent / "data" / "ea_cf27_ratings.csv"
GLOBAL_ROSTER_URL = "https://www.cfblabs.com/cfb-roster"
RATING_COLUMNS = ("ovr", "spd", "str", "agi", "awr", "acc", "jmp", "cod")
BASE_COLUMNS = ("name", "team", "position")
VALID_POSITIONS = {
    "QB", "HB", "RB", "FB", "WR", "TE", "LT", "LG", "C", "RG", "RT", "OL",
    "LE", "RE", "DE", "DT", "NT", "LOLB", "MLB", "ROLB", "LB", "EDGE",
    "CB", "FS", "SS", "S", "DB", "K", "P", "PK", "LS", "ATH", "SAM", "MIKE",
    "WILL",
}

HEADER_ALIASES = {
    "name": "name",
    "team": "team",
    "position": "position",
    "pos": "position",
    "overall": "ovr",
    "ovr": "ovr",
    "speed": "spd",
    "spd": "spd",
    "strength": "str",
    "str": "str",
    "agility": "agi",
    "agi": "agi",
    "awareness": "awr",
    "awr": "awr",
    "acceleration": "acc",
    "accel": "acc",
    "acc": "acc",
    "jumping": "jmp",
    "jmp": "jmp",
    "jump": "jmp",
    "change of dir": "cod",
    "change of direction": "cod",
    "cod": "cod",
    "class": "class",
    "year": "class",
    "height": "height",
    "weight": "weight",
    "hometown": "hometown",
    "state": "state",
}

# CFBLabs team slug mapping — URL path for each team
# format: team_location -> cfblabs slug
TEAM_SLUGS = {
    'Air Force': 'air-force', 'Akron': 'akron', 'Alabama': 'alabama',
    'App State': 'appalachian-state', 'Arizona': 'arizona',
    'Arizona State': 'arizona-state', 'Arkansas': 'arkansas',
    'Arkansas State': 'arkansas-state', 'Army': 'army', 'Auburn': 'auburn',
    'BYU': 'byu', 'Ball State': 'ball-state', 'Baylor': 'baylor',
    'Boise State': 'boise-state', 'Boston College': 'boston-college',
    'Bowling Green': 'bowling-green', 'Buffalo': 'buffalo',
    'California': 'california', 'Central Michigan': 'central-michigan',
    'Charlotte': 'charlotte', 'Cincinnati': 'cincinnati',
    'Clemson': 'clemson', 'Coastal Carolina': 'coastal-carolina',
    'Colorado': 'colorado', 'Colorado State': 'colorado-state',
    'Connecticut': 'uconn', 'Duke': 'duke', 'East Carolina': 'east-carolina',
    'Eastern Michigan': 'eastern-michigan', 'FIU': 'fiu',
    'Florida': 'florida', 'Florida Atlantic': 'florida-atlantic',
    'Florida State': 'florida-state', 'Fresno State': 'fresno-state',
    'Georgia': 'georgia', 'Georgia Southern': 'georgia-southern',
    'Georgia State': 'georgia-state', 'Georgia Tech': 'georgia-tech',
    'Hawaii': 'hawaii', 'Houston': 'houston', 'Illinois': 'illinois',
    'Indiana': 'indiana', 'Iowa': 'iowa', 'Iowa State': 'iowa-state',
    'Jacksonville State': 'jacksonville-state', 'James Madison': 'james-madison',
    'Kansas': 'kansas', 'Kansas State': 'kansas-state',
    'Kent State': 'kent-state', 'Kentucky': 'kentucky',
    'LSU': 'lsu', 'Liberty': 'liberty', 'Louisiana': 'louisiana',
    'Louisiana Monroe': 'louisiana-monroe', 'Louisville': 'louisville',
    'Marshall': 'marshall', 'Maryland': 'maryland', 'Memphis': 'memphis',
    'Miami': 'miami-fl', 'Miami (OH)': 'miami-oh', 'Michigan': 'michigan',
    'Michigan State': 'michigan-state', 'Middle Tennessee': 'middle-tennessee',
    'Minnesota': 'minnesota', 'Mississippi State': 'mississippi-state',
    'Missouri': 'missouri', 'Navy': 'navy', 'Nebraska': 'nebraska',
    'Nevada': 'nevada', 'New Mexico': 'new-mexico',
    'New Mexico State': 'new-mexico-state', 'North Carolina': 'north-carolina',
    'North Carolina State': 'nc-state', 'North Texas': 'north-texas',
    'Northern Illinois': 'northern-illinois', 'Northwestern': 'northwestern',
    'Notre Dame': 'notre-dame', 'Ohio': 'ohio', 'Ohio State': 'ohio-state',
    'Oklahoma': 'oklahoma', 'Oklahoma State': 'oklahoma-state',
    'Ole Miss': 'ole-miss', 'Oregon': 'oregon', 'Oregon State': 'oregon-state',
    'Penn State': 'penn-state', 'Pittsburgh': 'pittsburgh', 'Purdue': 'purdue',
    'Rice': 'rice', 'Rutgers': 'rutgers', 'Sam Houston': 'sam-houston',
    'San Diego State': 'san-diego-state', 'San Jose State': 'san-jose-state',
    'South Alabama': 'south-alabama', 'South Carolina': 'south-carolina',
    'South Florida': 'south-florida', 'Southern Miss': 'southern-miss',
    'Stanford': 'stanford', 'Syracuse': 'syracuse',
    'TCU': 'tcu', 'Temple': 'temple', 'Tennessee': 'tennessee',
    'Texas': 'texas', 'Texas AM': 'texas-am', 'Texas State': 'texas-state',
    'Texas Tech': 'texas-tech', 'Toledo': 'toledo', 'Troy': 'troy',
    'Tulane': 'tulane', 'Tulsa': 'tulsa', 'UAB': 'uab',
    'UCF': 'ucf', 'UCLA': 'ucla', 'UNLV': 'unlv', 'USC': 'usc',
    'UTEP': 'utep', 'UTSA': 'utsa', 'Utah': 'utah',
    'Utah State': 'utah-state', 'Vanderbilt': 'vanderbilt',
    'Virginia': 'virginia', 'Virginia Tech': 'virginia-tech',
    'Wake Forest': 'wake-forest', 'Washington': 'washington',
    'Washington State': 'washington-state', 'West Virginia': 'west-virginia',
    'Western Kentucky': 'western-kentucky', 'Western Michigan': 'western-michigan',
    'Wisconsin': 'wisconsin', 'Wyoming': 'wyoming',
}


def clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def normalize_header(value: str) -> str:
    text = clean_text(value).lower()
    text = re.sub(r"[↕↓↑]+", "", text)
    text = re.sub(r"\bmin\b", "", text)
    text = re.sub(r"[^a-z0-9]+", " ", text).strip()
    return HEADER_ALIASES.get(text, text.replace(" ", "_"))


def parse_rating(value: str) -> int | None:
    match = re.search(r"\d+", clean_text(value))
    if not match:
        return None
    rating = int(match.group())
    return rating if 0 <= rating <= 100 else None


def looks_like_position(value: str) -> bool:
    return clean_text(value).upper() in VALID_POSITIONS


def looks_like_name(value: str) -> bool:
    text = clean_text(value)
    if not text or text.lower() == "total":
        return False
    return bool(re.search(r"[A-Za-z]", text)) and not looks_like_position(text)


def parse_cells(cells: list[str], team_name: str) -> dict | None:
    """Parse one rendered CFBLabs row.

    CFBLabs has changed table column order at least once. This parser handles
    both name-first and position-first rows and rejects aggregate/stat rows.
    """
    cells = [clean_text(c) for c in cells if clean_text(c)]
    if len(cells) < 4:
        return None

    if looks_like_position(cells[0]) and looks_like_name(cells[1]):
        position_idx, name_idx, rating_start = 0, 1, 2
    elif looks_like_name(cells[0]) and looks_like_position(cells[1]):
        name_idx, position_idx, rating_start = 0, 1, 2
    else:
        return None

    ratings = [parse_rating(c) for c in cells[rating_start:rating_start + len(RATING_COLUMNS)]]
    if not ratings or ratings[0] is None:
        return None

    row = {
        "name": cells[name_idx].title(),
        "position": cells[position_idx].upper(),
        "team": team_name,
    }
    row.update(dict(zip(RATING_COLUMNS, ratings)))
    return row


def extract_table_rows(page: Page) -> list[dict]:
    rows = []
    tables = page.query_selector_all("table")
    for table in tables:
        table_rows = table.evaluate(
            """table => Array.from(table.querySelectorAll('tr')).map(tr =>
                Array.from(tr.querySelectorAll('th, td')).map(cell => cell.innerText || cell.textContent || '')
            )"""
        )
        headers = []
        data_start = 0
        for i, raw_cells in enumerate(table_rows):
            cells = [normalize_header(cell) for cell in raw_cells]
            if {"name", "team", "position", "ovr"}.issubset(set(cells)):
                headers = cells
                data_start = i + 1
                break
        if not headers:
            continue

        for raw_cells in table_rows[data_start:]:
            cells = [clean_text(cell) for cell in raw_cells]
            if len(cells) < len(headers):
                continue
            record = {}
            for header, value in zip(headers, cells):
                if not header or header in record:
                    continue
                record[header] = value

            if "name" not in record or "team" not in record or "position" not in record:
                continue
            if not looks_like_name(record["name"]) or not record["position"]:
                continue

            record["name"] = clean_text(record["name"]).title()
            record["team"] = clean_text(record["team"]).upper()
            record["position"] = clean_text(record["position"]).upper()
            for col in RATING_COLUMNS:
                if col in record:
                    record[col] = parse_rating(record[col])
            if record.get("ovr") is None:
                continue
            rows.append(record)
    return rows


def get_page_status(page: Page) -> str:
    try:
        text = page.locator("body").inner_text(timeout=3000)
    except PlaywrightTimeout:
        return ""
    showing = re.search(r"Showing\s+\d+\s+of\s+[\d,]+\s+players", text, flags=re.I)
    page_num = re.search(r"Page\s+\d+\s+of\s+\d+", text, flags=re.I)
    return " | ".join(m.group(0) for m in (page_num, showing) if m)


def click_button_by_text(page: Page, label: str, timeout: int = 3000) -> bool:
    controls = page.locator("button, a", has_text=re.compile(rf"^\s*{re.escape(label)}\s*$", re.I))
    for i in range(controls.count()):
        control = controls.nth(i)
        try:
            if control.is_visible(timeout=timeout) and control.is_enabled(timeout=timeout):
                control.scroll_into_view_if_needed(timeout=timeout)
                control.click(timeout=timeout)
                return True
        except PlaywrightTimeout:
            continue
    return False


def set_rows_per_page(page: Page, rows_per_page: int) -> None:
    target = "25" if rows_per_page >= 25 else str(rows_per_page)
    current = get_page_status(page)
    try:
        page.locator("select.cfbr-select").first.select_option(value=target, timeout=3000)
        try:
            page.wait_for_function(
                "(oldStatus) => oldStatus && !document.body.innerText.includes(oldStatus)",
                arg=current,
                timeout=5000,
            )
        except PlaywrightTimeout:
            page.wait_for_timeout(1000)
        return
    except PlaywrightTimeout:
        pass

    selects = page.locator("select")
    try:
        count = selects.count()
    except PlaywrightTimeout:
        return
    for i in range(count):
        select = selects.nth(i)
        try:
            select.locator("option").first.wait_for(timeout=1000)
            options = select.locator("option").all_inner_texts()
        except PlaywrightTimeout:
            continue
        normalized = [clean_text(option) for option in options]
        if target not in normalized:
            continue
        try:
            select.select_option(label=target, timeout=3000)
            page.wait_for_timeout(1000)
            return
        except PlaywrightTimeout:
            continue

    try:
        current = get_page_status(page)
        option = page.get_by_text(target, exact=True).first
        if option.count() and option.is_visible(timeout=1000):
            option.click(timeout=3000)
            try:
                page.wait_for_function(
                    "(oldStatus) => oldStatus && !document.body.innerText.includes(oldStatus)",
                    arg=current,
                    timeout=5000,
                )
            except PlaywrightTimeout:
                page.wait_for_timeout(1000)
    except PlaywrightTimeout:
        return


def filter_global_team(page: Page, team_filter: str | None) -> None:
    if not team_filter:
        return
    try:
        current = get_page_status(page)
        input_box = page.get_by_label("Filter by team").first
        input_box.click(timeout=3000)
        input_box.fill(team_filter.upper(), timeout=3000)
        page.wait_for_timeout(500)
        input_box.press("Enter", timeout=3000)
        try:
            page.wait_for_function(
                "(oldStatus) => oldStatus && !document.body.innerText.includes(oldStatus)",
                arg=current,
                timeout=5000,
            )
        except PlaywrightTimeout:
            page.wait_for_timeout(1500)
    except PlaywrightTimeout:
        return


def scrape_roster_database(page: Page, team_filter=None, rows_per_page=100, max_pages=None) -> list[dict]:
    page.goto(GLOBAL_ROSTER_URL, wait_until="networkidle", timeout=30000)
    page.wait_for_selector("table tbody tr", timeout=20000)
    set_rows_per_page(page, rows_per_page)
    filter_global_team(page, team_filter)

    players = []
    seen_pages = set()
    page_num = 1
    while True:
        page.wait_for_selector("table tbody tr", timeout=20000)
        page.wait_for_timeout(500)
        status = get_page_status(page)
        if status in seen_pages:
            break
        seen_pages.add(status or f"page-{page_num}")

        page_players = extract_table_rows(page)
        players.extend(page_players)
        print(
            f"  roster page {page_num}: {len(page_players)} players ({status or 'status unavailable'})",
            flush=True,
        )

        if max_pages and page_num >= max_pages:
            break
        old_status = status
        if not click_button_by_text(page, "Next"):
            break
        page_num += 1
        try:
            page.wait_for_function(
                "(oldStatus) => oldStatus && !document.body.innerText.includes(oldStatus)",
                arg=old_status,
                timeout=5000,
            )
        except PlaywrightTimeout:
            page.wait_for_timeout(1200)

    return players


def inspect_roster_database(page: Page) -> None:
    page.goto(GLOBAL_ROSTER_URL, wait_until="networkidle", timeout=30000)
    page.wait_for_selector("body", timeout=20000)
    page.wait_for_timeout(1500)
    print(get_page_status(page) or "No roster status text found")
    body_text = page.locator("body").inner_text(timeout=3000)
    rows_idx = body_text.lower().find("rows per page")
    if rows_idx >= 0:
        print("\nRows-per-page text:")
        print(clean_text(body_text[max(0, rows_idx - 200):rows_idx + 500]))
    print("\nSelects:")
    for i in range(page.locator("select").count()):
        select = page.locator("select").nth(i)
        options = []
        try:
            select.locator("option").first.wait_for(timeout=1000)
            options = [clean_text(o) for o in select.locator("option").all_inner_texts()]
        except PlaywrightTimeout:
            pass
        print(f"  select {i}: {options[:20]}")

    print("\nTables:")
    for i, table in enumerate(page.query_selector_all("table")[:5]):
        text = clean_text(table.inner_text())
        print(f"  table {i}: {text[:1000]}")

    print("\nCandidate row elements:")
    snippets = page.locator("tr, [role='row'], [data-player], .player-row").all_inner_texts()
    for i, snippet in enumerate(snippets[:20]):
        print(f"  row {i}: {clean_text(snippet)[:500]}")

    print("\nButtons and links:")
    locator = page.locator("button, a")
    controls = locator.all_inner_texts()
    for i, control in enumerate(controls[:140]):
        text = clean_text(control)
        if text:
            print(f"  control {i}: {text[:200]}")
            if text.lower() == "next":
                element = locator.nth(i).evaluate(
                    """el => ({
                        tag: el.tagName,
                        text: el.innerText,
                        aria: el.getAttribute('aria-label'),
                        disabled: el.disabled || el.getAttribute('aria-disabled'),
                        cls: el.className,
                        html: el.outerHTML.slice(0, 500)
                    })"""
                )
                print(f"    next debug: {element}")

    print("\nCombobox/listbox-ish elements:")
    combo_locator = page.locator("[role='combobox'], [role='listbox'], [aria-haspopup='listbox']")
    for i in range(combo_locator.count()):
        element = combo_locator.nth(i).evaluate(
            """el => ({
                tag: el.tagName,
                text: el.innerText,
                aria: el.getAttribute('aria-label'),
                expanded: el.getAttribute('aria-expanded'),
                cls: el.className,
                html: el.outerHTML.slice(0, 500)
            })"""
        )
        print(f"  combo {i}: {element}")

    print("\nRows-per-page option elements:")
    option_elements = page.locator("text=/^(10|25)$/")
    for i in range(option_elements.count()):
        element = option_elements.nth(i).evaluate(
            """el => ({
                tag: el.tagName,
                text: el.innerText || el.textContent,
                cls: el.className,
                parentTag: el.parentElement && el.parentElement.tagName,
                parentText: el.parentElement && (el.parentElement.innerText || el.parentElement.textContent),
                parentClass: el.parentElement && el.parentElement.className,
                html: el.outerHTML.slice(0, 500),
                parentHtml: el.parentElement && el.parentElement.outerHTML.slice(0, 500)
            })"""
        )
        print(f"  option-ish {i}: {element}")


def scrape_team(page, team_name: str, slug: str) -> list[dict]:
    """Scrape all players for a single team from cfblabs.com."""
    url = f"https://www.cfblabs.com/teams/{slug}"
    players = []

    try:
        page.goto(url, wait_until="networkidle", timeout=30000)
        # wait for player rows to appear
        page.wait_for_selector("table tbody tr, .player-row, [data-player]",
                               timeout=15000)
        time.sleep(1.5)  # let JS finish rendering

        # try table rows first
        rows = page.query_selector_all("table tbody tr")
        if rows:
            for row in rows:
                cells = [cell.inner_text().strip() for cell in row.query_selector_all("td")]
                player = parse_cells(cells, team_name)
                if player:
                    players.append(player)

    except PlaywrightTimeout:
        print(f"  [timeout] {team_name} — skipping")
    except Exception as e:
        print(f"  [error] {team_name}: {e}")

    return players


def build_output_df(players: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(players)
    if df.empty:
        return df

    for col in (*BASE_COLUMNS, *RATING_COLUMNS):
        if col not in df.columns:
            df[col] = None
    ordered = [*BASE_COLUMNS, *RATING_COLUMNS]
    extras = sorted(col for col in df.columns if col not in ordered)
    df = df[ordered + extras]
    df = df.drop_duplicates(subset=["team", "name", "position"]).sort_values(
        ["team", "ovr", "name"], ascending=[True, False, True]
    )
    return df


def write_output(df: pd.DataFrame, output: str | Path) -> pd.DataFrame:
    if df.empty:
        print("\nNo players scraped. CFBLabs markup may have changed.")
        return df

    print(f"\nTotal: {len(df)} players from {df['team'].nunique()} teams")
    bad_ovr = df["ovr"].isna().sum()
    if bad_ovr:
        raise ValueError(f"Scrape produced {bad_ovr} rows without OVR ratings")

    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(output, index=False)
    print(f"Saved -> {output}")
    print("\nSample:")
    print(df.head(10).to_string(index=False))
    return df


def scrape_all(team_filter=None, output=OUTPUT, rows_per_page=100, max_pages=None,
               legacy_team_page=False, inspect=False):
    """Scrape the full roster database, or legacy team pages when requested."""
    teams = {k: v for k, v in TEAM_SLUGS.items()
             if not team_filter or team_filter.lower() in k.lower()}

    all_players = []
    if legacy_team_page:
        print(f"Scraping {len(teams)} legacy team pages from cfblabs.com...")
    else:
        print("Scraping CFBLabs full roster database...")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/120.0.0.0 Safari/537.36"
        )
        page = context.new_page()

        if inspect:
            inspect_roster_database(page)
            browser.close()
            return pd.DataFrame()
        if legacy_team_page:
            for i, (team, slug) in enumerate(teams.items()):
                print(f"  [{i+1}/{len(teams)}] {team}...", end=" ", flush=True)
                players = scrape_team(page, team, slug)
                all_players.extend(players)
                print(f"{len(players)} players")
                time.sleep(0.8)  # polite delay
        else:
            all_players = scrape_roster_database(
                page,
                team_filter=team_filter,
                rows_per_page=rows_per_page,
                max_pages=max_pages,
            )

        browser.close()

    return write_output(build_output_df(all_players), output)


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--team', default=None, help='Filter to a single team')
    p.add_argument('--output', default=OUTPUT, help='CSV output path')
    p.add_argument('--rows-per-page', type=int, default=100)
    p.add_argument('--max-pages', type=int, default=None, help='Smoke-test limit')
    p.add_argument('--legacy-team-page', action='store_true',
                   help='Use /teams/{slug}; only exposes page summary tables')
    p.add_argument('--inspect', action='store_true',
                   help='Print live CFBLabs roster DOM snippets')
    a = p.parse_args()
    scrape_all(a.team, a.output, a.rows_per_page, a.max_pages, a.legacy_team_page, a.inspect)
