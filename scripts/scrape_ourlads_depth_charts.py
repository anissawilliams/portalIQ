"""
scrape_ourlads_depth_charts.py - Scrape Ourlads college football depth charts
=============================================================================
Outputs a normalized CSV with one row per player depth-chart slot.

Usage:
    python scripts/scrape_ourlads_depth_charts.py --team "Florida State"
    python scripts/scrape_ourlads_depth_charts.py --all
"""

import argparse
import csv
import html
import re
import time
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import quote, urljoin
from urllib.request import Request, urlopen


BASE_URL = "https://secure.ourlads.com/ncaa-football-depth-charts/"
INDEX_URL = urljoin(BASE_URL, "default.aspx")
OUTPUT = Path(__file__).parent / "data" / "ourlads_depth_charts.csv"


def clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(value or "")).strip()


def name_key(value: str) -> str:
    text = clean_text(value)
    text = re.sub(r"\b(jr|sr|ii|iii|iv|v)\b\.?", "", text, flags=re.I)
    return re.sub(r"[^a-z0-9]+", "", text.lower())


def fetch_html(url: str) -> str:
    req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urlopen(req, timeout=30) as response:
        return response.read().decode("utf-8", "ignore")


@dataclass
class TeamLink:
    team: str
    slug: str
    team_id: str
    url: str


class OurladsIndexParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []
        self._last_team = ""
        self._capture_team = False
        self._team_parts = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "div" and attrs.get("class") == "nfl-dc-mm-team-name":
            self._capture_team = True
            self._team_parts = []
        if tag == "a" and clean_text(attrs.get("href", "")).startswith("depth-chart.aspx"):
            href = attrs["href"]
            slug_match = re.search(r"[?&]s=([^&]+)", href)
            id_match = re.search(r"[?&]id=(\d+)", href)
            if slug_match and id_match and self._last_team:
                self.links.append(TeamLink(
                    team=self._last_team,
                    slug=slug_match.group(1),
                    team_id=id_match.group(1),
                    url=urljoin(
                        BASE_URL,
                        f"depth-chart.aspx?s={quote(slug_match.group(1))}&id={id_match.group(1)}",
                    ),
                ))

    def handle_endtag(self, tag):
        if tag == "div" and self._capture_team:
            self._last_team = clean_text("".join(self._team_parts))
            self._capture_team = False

    def handle_data(self, data):
        if self._capture_team:
            self._team_parts.append(data)


class DepthChartParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.title = ""
        self.updated_at = ""
        self.rows = []
        self._in_title = False
        self._in_updated = False
        self._in_depth_body = False
        self._in_row = False
        self._in_cell = False
        self._cell_parts = []
        self._cell_attrs = {}
        self._row = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "title":
            self._in_title = True
            return
        if tag == "tbody" and attrs.get("id") == "ctl00_phContent_dcTBody":
            self._in_depth_body = True
            return
        if tag == "div" and attrs.get("id") == "ctl00_phContent_DateUpd":
            self._in_updated = True
            self._cell_parts = []
            return
        if self._in_depth_body and tag == "tr":
            self._in_row = True
            self._row = []
            return
        if self._in_row and tag == "td":
            self._in_cell = True
            self._cell_parts = []
            self._cell_attrs = {}
            return
        if self._in_cell and tag == "a":
            self._cell_attrs["href"] = attrs.get("href", "")
            self._cell_attrs["class"] = attrs.get("class", "")

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False
            return
        if tag == "div" and self._in_updated:
            self.updated_at = clean_text("".join(self._cell_parts)).replace("Updated:", "").strip()
            self._in_updated = False
            self._cell_parts = []
            return
        if self._in_depth_body and tag == "tbody":
            self._in_depth_body = False
            return
        if self._in_cell and tag == "td":
            self._row.append({
                "text": clean_text("".join(self._cell_parts)),
                "href": self._cell_attrs.get("href", ""),
                "class": self._cell_attrs.get("class", ""),
            })
            self._in_cell = False
            self._cell_parts = []
            self._cell_attrs = {}
            return
        if self._in_row and tag == "tr":
            if self._row:
                self.rows.append(self._row)
            self._in_row = False
            self._row = []

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        if self._in_updated or self._in_cell:
            self._cell_parts.append(data)


def parse_player_text(value: str) -> dict:
    text = clean_text(value)
    if not text:
        return {}

    tokens = text.split()
    tags = []
    while tokens and re.fullmatch(r"[A-Z]{1,3}(?:/[A-Z]{1,3})?", tokens[-1]):
        tags.insert(0, tokens.pop())

    name = " ".join(tokens)
    if "," in name:
        last, first = [part.strip() for part in name.split(",", 1)]
        name = f"{first} {last}".strip()

    return {
        "player_name": clean_text(name),
        "class_tag": "/".join(tags),
        "is_transfer": any("TR" in tag for tag in tags),
        "is_true_freshman": any(tag == "FR" for tag in tags),
    }


def parse_depth_chart(team: TeamLink, page_html: str) -> list[dict]:
    parser = DepthChartParser()
    parser.feed(page_html)

    season_match = re.search(r"\b(20\d{2})\b", parser.title)
    season = int(season_match.group(1)) if season_match else None
    out = []
    for row in parser.rows:
        if len(row) < 3:
            continue
        position = row[0]["text"]
        if not position:
            continue
        for slot in range(1, 6):
            jersey_idx = 1 + (slot - 1) * 2
            player_idx = jersey_idx + 1
            if player_idx >= len(row):
                continue
            parsed = parse_player_text(row[player_idx]["text"])
            if not parsed.get("player_name"):
                continue
            link_class = row[player_idx].get("class", "")
            out.append({
                "team": team.team,
                "team_slug": team.slug,
                "team_id": team.team_id,
                "season": season,
                "position": position,
                "depth_slot": slot,
                "jersey": row[jersey_idx]["text"],
                "player_name": parsed["player_name"],
                "name_key": name_key(parsed["player_name"]),
                "class_tag": parsed["class_tag"],
                "is_transfer": parsed["is_transfer"] or "lc_orange" in link_class or "gold" in link_class,
                "is_true_freshman": parsed["is_true_freshman"] or "lc_purple" in link_class,
                "source_updated_at": parser.updated_at,
                "source_url": team.url,
            })
    return out


def load_team_links() -> list[TeamLink]:
    parser = OurladsIndexParser()
    parser.feed(fetch_html(INDEX_URL))
    return parser.links


def select_teams(links: list[TeamLink], team_filter: str | None, all_teams: bool) -> list[TeamLink]:
    if all_teams:
        return links
    if not team_filter:
        team_filter = "Florida State"
    needle = team_filter.lower()
    selected = [
        link for link in links
        if needle in link.team.lower() or needle == link.slug.lower()
    ]
    if not selected:
        raise ValueError(f"No Ourlads team matched: {team_filter}")
    return selected


def scrape(team_filter=None, all_teams=False, output=OUTPUT, delay=0.4) -> list[dict]:
    links = select_teams(load_team_links(), team_filter, all_teams)
    rows = []
    print(f"Scraping {len(links)} Ourlads depth chart(s)...", flush=True)
    for i, team in enumerate(links, 1):
        try:
            chart_rows = parse_depth_chart(team, fetch_html(team.url))
            rows.extend(chart_rows)
            print(f"  [{i}/{len(links)}] {team.team}: {len(chart_rows)} players", flush=True)
        except Exception as exc:
            print(f"  [{i}/{len(links)}] {team.team}: ERROR {exc}", flush=True)
        time.sleep(delay)

    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "team", "team_slug", "team_id", "season", "position", "depth_slot",
        "jersey", "player_name", "name_key", "class_tag", "is_transfer",
        "is_true_freshman", "source_updated_at", "source_url",
    ]
    with output.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    print(f"Saved {len(rows)} rows -> {output}")
    return rows


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--team", default=None, help="Team name or Ourlads slug")
    parser.add_argument("--all", action="store_true", help="Scrape every team on the Ourlads index")
    parser.add_argument("--output", default=OUTPUT, help="CSV output path")
    parser.add_argument("--delay", type=float, default=0.4, help="Delay between team pages")
    args = parser.parse_args()
    scrape(args.team, args.all, args.output, args.delay)
