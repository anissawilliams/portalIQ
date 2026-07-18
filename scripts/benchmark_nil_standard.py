"""
benchmark_nil_standard.py - Compare PortalIQ estimates to NIL Standard
======================================================================
Scrapes the public NIL Standard football player valuations page, writes a
normalized benchmark CSV, then matches it to PortalIQ NIL estimates.

NIL Standard is not ground truth. Treat it as a public market-estimate
benchmark for calibration and bias checks.

Usage:
    .venv/bin/python scripts/benchmark_nil_standard.py
"""

from __future__ import annotations

import argparse
import csv
import html
import re
import unicodedata
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin
from urllib.request import Request, urlopen

import numpy as np
import pandas as pd
from sklearn.metrics import mean_absolute_error, median_absolute_error, r2_score


NIL_STANDARD_URL = "https://thenilstandard.com/football/players"
ROOT = Path(__file__).resolve().parents[1]
DEFAULT_STANDARD_OUTPUT = ROOT / "scripts" / "data" / "nil_standard_football_players.csv"
DEFAULT_TEAM_OUTPUT = ROOT / "scripts" / "data" / "nil_standard_florida_state_players.csv"
DEFAULT_ESTIMATES = ROOT / "backend" / "data" / "nil_player_estimates_2026_with_ea_ourlads.csv"
DEFAULT_MATCHED_OUTPUT = ROOT / "backend" / "data" / "nil_standard_benchmark_matches.csv"
DEFAULT_SUMMARY_OUTPUT = ROOT / "backend" / "data" / "nil_standard_benchmark_summary.csv"

POSITIONS = {
    "QB", "RB", "WR", "TE", "OT", "OL", "IOL", "C", "G", "DL", "DT", "DE",
    "EDGE", "LB", "CB", "DB", "S", "K", "P", "LS", "ATH", "FB", "KR",
}

TEAM_WORDS = (
    "tigers", "bulldogs", "seminoles", "crimson tide", "buckeyes", "longhorns",
    "wolverines", "hurricanes", "wildcats", "cardinals", "trojans", "aggies",
    "cougars", "panthers", "mountaineers", "bearcats", "bears", "rebels",
    "volunteers", "gators", "ducks", "gamecocks", "nittany lions", "cowboys",
    "sooners", "utes", "mustangs", "hoosiers", "red raiders", "wolfpack",
    "fighting irish", "yellow jackets", "razorbacks", "commodores", "terrapins",
)


def clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(value or "")).strip()


def normalize_name(value: str) -> str:
    text = unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode()
    text = re.sub(r"\b(jr|sr|ii|iii|iv|v)\b\.?", "", text, flags=re.I)
    return re.sub(r"[^a-z0-9]+", "", text.lower())


def normalize_team(value: str) -> str:
    text = str(value or "").lower()
    for word in TEAM_WORDS:
        text = text.replace(word, "")
    return re.sub(r"[^a-z0-9]+", "", text)


def teams_match(left: str, right: str) -> bool:
    left_key = normalize_team(left)
    right_key = normalize_team(right)
    return bool(left_key and right_key and (
        left_key == right_key or left_key in right_key or right_key in left_key
    ))


def fetch_html(url: str) -> str:
    req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urlopen(req, timeout=30) as response:
        return response.read().decode("utf-8", "ignore")


@dataclass
class AnchorText:
    href: str
    text: str


class AnchorParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.anchors: list[AnchorText] = []
        self._href = ""
        self._parts: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag != "a":
            return
        self._href = dict(attrs).get("href", "")
        self._parts = []

    def handle_endtag(self, tag):
        if tag != "a" or not self._href:
            return
        text = clean_text(" ".join(self._parts))
        if text:
            self.anchors.append(AnchorText(self._href, text))
        self._href = ""
        self._parts = []

    def handle_data(self, data):
        if self._href:
            self._parts.append(data)


def parse_anchor(anchor: AnchorText) -> dict | None:
    text = clean_text(anchor.text)
    if "$" not in text:
        return None

    match = re.match(r"^(.+?)\s+\$([\d,]+)$", text)
    if not match:
        return None

    left, value_text = match.groups()
    tokens = left.split()
    pos_idx = next((i for i, token in enumerate(tokens) if token.upper() in POSITIONS), None)
    if pos_idx is None or pos_idx == 0 or pos_idx == len(tokens) - 1:
        return None

    player_name = " ".join(tokens[:pos_idx])
    position = tokens[pos_idx].upper()
    team = " ".join(tokens[pos_idx + 1:])
    value = int(value_text.replace(",", ""))
    if not player_name or not team or value <= 0:
        return None

    return {
        "player_name": player_name,
        "team": team,
        "position": position,
        "nil_standard_value": value,
        "source_url": urljoin(NIL_STANDARD_URL, anchor.href),
    }


def parse_team_anchor(anchor: AnchorText, team: str) -> dict | None:
    text = clean_text(anchor.text)
    if "Est. NIL Value" not in text or "$" not in text:
        return None

    match = re.match(r"^(.+?)\s+([A-Z]{1,4})\s+(?:.*?\s+)?Est\. NIL Value\s+\$([\d,]+)$", text)
    if not match:
        return None

    player_name, position, value_text = match.groups()
    position = position.upper()
    if position not in POSITIONS:
        return None

    return {
        "player_name": player_name,
        "team": team,
        "position": position,
        "nil_standard_value": int(value_text.replace(",", "")),
        "source_url": urljoin(NIL_STANDARD_URL, anchor.href),
    }


def scrape_nil_standard(url: str) -> pd.DataFrame:
    parser = AnchorParser()
    parser.feed(fetch_html(url))

    rows = []
    seen = set()
    for anchor in parser.anchors:
        parsed = parse_anchor(anchor)
        if not parsed:
            continue
        key = (
            normalize_name(parsed["player_name"]),
            normalize_team(parsed["team"]),
            parsed["position"],
            parsed["nil_standard_value"],
        )
        if key in seen:
            continue
        seen.add(key)
        parsed["name_key"] = key[0]
        parsed["team_key"] = key[1]
        rows.append(parsed)

    if not rows:
        raise RuntimeError(f"No NIL Standard player valuation rows parsed from {url}")

    return pd.DataFrame(rows).sort_values("nil_standard_value", ascending=False)


def scrape_nil_standard_team(url: str, team: str) -> pd.DataFrame:
    parser = AnchorParser()
    parser.feed(fetch_html(url))

    rows = []
    seen = set()
    for anchor in parser.anchors:
        parsed = parse_team_anchor(anchor, team)
        if not parsed:
            continue
        key = (
            normalize_name(parsed["player_name"]),
            normalize_team(parsed["team"]),
            parsed["position"],
            parsed["nil_standard_value"],
        )
        if key in seen:
            continue
        seen.add(key)
        parsed["name_key"] = key[0]
        parsed["team_key"] = key[1]
        rows.append(parsed)

    if not rows:
        raise RuntimeError(f"No NIL Standard team valuation rows parsed from {url}")

    return pd.DataFrame(rows).sort_values("nil_standard_value", ascending=False)


def value_tier(value: float) -> str:
    if value >= 2_000_000:
        return "elite_2m_plus"
    if value >= 1_000_000:
        return "seven_figures"
    if value >= 500_000:
        return "high_500k_1m"
    return "sub_500k"


def metric_row(group: str, label: str, frame: pd.DataFrame) -> dict:
    y = frame["nil_standard_value"].astype(float)
    pred = frame["nil_estimate"].astype(float)
    abs_error = (pred - y).abs()
    return {
        "group": group,
        "label": label,
        "n": len(frame),
        "standard_mean": round(y.mean()),
        "estimate_mean": round(pred.mean()),
        "bias_mean": round((pred - y).mean()),
        "mae": round(mean_absolute_error(y, pred)),
        "median_ae": round(median_absolute_error(y, pred)),
        "rmse": round(float(np.sqrt(np.mean((pred - y) ** 2)))),
        "r2": round(r2_score(y, pred), 4) if len(frame) > 1 and y.nunique() > 1 else np.nan,
        "mape": round((abs_error / y.replace(0, np.nan)).mean(), 4),
        "wape": round(abs_error.sum() / y.sum(), 4) if y.sum() else np.nan,
    }


def match_benchmark(standard: pd.DataFrame, estimates: pd.DataFrame) -> pd.DataFrame:
    estimates = estimates.copy()
    estimates["name_key"] = estimates["player_name"].map(normalize_name)
    estimates["team_key"] = estimates["team"].map(normalize_team)

    rows = []
    for _, target in standard.iterrows():
        candidates = estimates[estimates["name_key"].eq(target["name_key"])]
        if candidates.empty:
            continue

        team_matches = candidates[candidates["team"].map(lambda team: teams_match(target["team"], team))]
        if team_matches.empty:
            continue

        same_pos = team_matches[
            team_matches["position"].astype(str).str.upper().eq(str(target["position"]).upper())
        ]
        pool = same_pos if not same_pos.empty else team_matches
        match = pool.sort_values("nil_estimate", ascending=False).iloc[0]

        row = {
            "player_name": target["player_name"],
            "team": target["team"],
            "position": target["position"],
            "nil_standard_value": target["nil_standard_value"],
            "portal_iq_player_name": match["player_name"],
            "portal_iq_team": match["team"],
            "portal_iq_position": match["position"],
            "nil_estimate": match["nil_estimate"],
            "nil_error": match["nil_estimate"] - target["nil_standard_value"],
            "nil_abs_error": abs(match["nil_estimate"] - target["nil_standard_value"]),
            "nil_pct_error": (
                (match["nil_estimate"] - target["nil_standard_value"]) / target["nil_standard_value"]
            ),
            "value_tier": value_tier(target["nil_standard_value"]),
            "ea_ovr": match.get("ea_ovr", np.nan),
            "ea_match": match.get("ea_match", False),
            "ourlads_match": match.get("ourlads_match", False),
            "ourlads_depth_slot": match.get("ourlads_depth_slot", np.nan),
            "ourlads_position": match.get("ourlads_position", ""),
            "source_url": target["source_url"],
        }
        rows.append(row)

    return pd.DataFrame(rows)


def build_summary(matches: pd.DataFrame) -> pd.DataFrame:
    rows = [metric_row("overall", "all", matches)]

    for pos, frame in matches.groupby("position"):
        if len(frame) >= 3:
            rows.append(metric_row("position", pos, frame))

    for tier, frame in matches.groupby("value_tier"):
        if len(frame) >= 3:
            rows.append(metric_row("tier", tier, frame))

    for col in ["ea_match", "ourlads_match"]:
        for label, frame in matches.groupby(col):
            if len(frame) >= 3:
                rows.append(metric_row(col, str(bool(label)), frame))

    fsu = matches[matches["team"].eq("Florida State")]
    if len(fsu) >= 2:
        rows.append(metric_row("team", "Florida State", fsu))

    return pd.DataFrame(rows)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default=NIL_STANDARD_URL)
    parser.add_argument("--team-url", default=None)
    parser.add_argument("--team", default=None)
    parser.add_argument("--standard-output", default=str(DEFAULT_STANDARD_OUTPUT))
    parser.add_argument("--team-output", default=str(DEFAULT_TEAM_OUTPUT))
    parser.add_argument("--estimates", default=str(DEFAULT_ESTIMATES))
    parser.add_argument("--matched-output", default=str(DEFAULT_MATCHED_OUTPUT))
    parser.add_argument("--summary-output", default=str(DEFAULT_SUMMARY_OUTPUT))
    args = parser.parse_args()

    standard_output = Path(args.standard_output)
    team_output = Path(args.team_output)
    matched_output = Path(args.matched_output)
    summary_output = Path(args.summary_output)
    standard_output.parent.mkdir(parents=True, exist_ok=True)
    team_output.parent.mkdir(parents=True, exist_ok=True)
    matched_output.parent.mkdir(parents=True, exist_ok=True)
    summary_output.parent.mkdir(parents=True, exist_ok=True)

    if args.team_url:
        if not args.team:
            raise ValueError("--team is required when --team-url is provided")
        standard = scrape_nil_standard_team(args.team_url, args.team)
        standard.to_csv(team_output, index=False, quoting=csv.QUOTE_MINIMAL)
        benchmark_output = team_output
    else:
        standard = scrape_nil_standard(args.url)
        standard.to_csv(standard_output, index=False, quoting=csv.QUOTE_MINIMAL)
        benchmark_output = standard_output

    estimates = pd.read_csv(args.estimates)
    matches = match_benchmark(standard, estimates)
    if matches.empty:
        raise RuntimeError("No NIL Standard rows matched PortalIQ estimates")
    matches.to_csv(matched_output, index=False)

    summary = build_summary(matches)
    summary.to_csv(summary_output, index=False)

    print(f"NIL Standard rows: {len(standard):,} -> {benchmark_output}")
    print(f"Matched rows:      {len(matches):,} -> {matched_output}")
    print(f"Summary rows:      {len(summary):,} -> {summary_output}")
    print()
    print(summary.to_string(index=False))


if __name__ == "__main__":
    main()
