"""
ingest_volatility_scores.py — Run volatility model and push to Supabase
========================================================================
1. Loads 2026 roster from CSV
2. Runs score_volatility() for every player
3. Applies class modifier (from rosters.py logic)
4. Upserts into volatility_scores table
5. Logs to data_provenance

Run from backend/:
    python3 ingest_volatility_scores.py
"""

import os
import math
import json
import pandas as pd
from pathlib import Path
from datetime import datetime, timezone
from collections import defaultdict
from dotenv import load_dotenv
from supabase import create_client, Client
from volatility import score_volatility

load_dotenv()

SUPABASE_URL  = os.environ.get("SUPABASE_URL", "https://fpigpzmgqmzoxdknhetg.supabase.co")
SUPABASE_KEY  = os.environ.get("SUPABASE_SERVICE_KEY")
DATA_DIR      = Path(__file__).parent / "data"
ROSTER_CSV    = DATA_DIR / "cfb_rosters_2026_clean.csv"
SEASON        = 2026
MODEL_VERSION = "v1"
BATCH_SIZE    = 100

if not SUPABASE_KEY:
    raise ValueError("SUPABASE_SERVICE_KEY not found in .env")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)


def batches(lst, n):
    for i in range(0, len(lst), n):
        yield lst[i:i + n]


def clean_val(v):
    if v is None:
        return None
    if isinstance(v, float) and math.isnan(v):
        return None
    return v


# ── Class modifier (from rosters.py) ─────────────────────────

CLASS_MODIFIERS = {
    "Senior":    {"buried": 1.25, "starter": 1.10},
    "Graduate":  {"buried": 1.30, "starter": 1.15},
    "Junior":    {"buried": 1.10, "starter": 1.00},
    "Sophomore": {"buried": 0.90, "starter": 0.95},
    "Freshman":  {"buried": 0.65, "starter": 0.75},
}

def apply_class_modifier(score: float, cls: str, depth_rank: int) -> float:
    modifier_set = CLASS_MODIFIERS.get(cls, {"buried": 1.0, "starter": 1.0})
    modifier = modifier_set["buried"] if depth_rank >= 3 else modifier_set["starter"]
    return round(min(score * modifier, 100), 1)

def get_risk_label(score: float) -> tuple:
    if score >= 70: return "CRITICAL", "#ef4444"
    if score >= 50: return "HIGH",     "#f97316"
    if score >= 30: return "MEDIUM",   "#eab308"
    return "LOW", "#22c55e"


# ── Load athlete UUID map ─────────────────────────────────────

def load_athlete_map() -> dict:
    """{ espn_athlete_id (int) -> athlete UUID }"""
    all_rows = []
    page, page_size = 0, 1000
    while True:
        resp = supabase.table("athletes")\
            .select("id, espn_athlete_id")\
            .range(page * page_size, (page + 1) * page_size - 1)\
            .execute()
        all_rows.extend(resp.data)
        if len(resp.data) < page_size:
            break
        page += 1
    return {
        int(row["espn_athlete_id"]): row["id"]
        for row in all_rows
        if row["espn_athlete_id"] is not None
    }


# ── Score all players ─────────────────────────────────────────

def score_all(df: pd.DataFrame) -> list:
    """Run volatility model on every player. Returns list of score dicts."""

    # ESPN players only (have real depth/position data)
    df_espn = df[df["athlete_id"].notna()].copy()
    df_espn = df_espn[df_espn["athlete_id"].astype(str).str.strip() != ""].copy()

    # Calculate depth rank per team/position
    if "transfer_value_score" in df_espn.columns:
        df_espn["depth_rank"] = df_espn.groupby(
            ["team", "position"]
        )["transfer_value_score"].rank(ascending=False, method="first").astype(int)
    else:
        df_espn["depth_rank"] = 2

    # Position counts per team (for depth pressure)
    position_counts_by_team = {}
    for team, grp in df_espn.groupby("team"):
        position_counts_by_team[team] = grp["position"].value_counts().to_dict()

    results = []
    for _, row in df_espn.iterrows():
        player = row.to_dict()
        team   = str(player.get("team", ""))
        pos    = str(player.get("position", ""))
        cls    = str(player.get("class", "Sophomore"))
        depth  = int(player.get("depth_rank", 2))

        position_counts = position_counts_by_team.get(team, {})

        # Base volatility score
        vol = score_volatility(player, position_counts)
        base_score = vol["volatility_score"]

        # Apply class modifier
        adjusted = apply_class_modifier(base_score, cls, depth)
        risk_label, risk_color = get_risk_label(adjusted)

        espn_id = clean_val(player.get("athlete_id"))
        try:
            espn_id = int(float(espn_id))
        except (ValueError, TypeError):
            continue

        results.append({
            "espn_athlete_id":  espn_id,
            "volatility_score": adjusted,
            "risk_label":       risk_label,
            "risk_color":       risk_color,
            "depth_rank":       depth,
            "class_modifier":   CLASS_MODIFIERS.get(cls, {}).get(
                "buried" if depth >= 3 else "starter", 1.0
            ),
            "breakdown":        vol["breakdown"],
            "position":         pos,
            "class":            cls,
            "team":             team,
        })

    return results


# ── Build DB records ──────────────────────────────────────────

def build_records(scores: list, athlete_map: dict) -> tuple:
    records = []
    unmatched = 0
    now = datetime.now(timezone.utc).isoformat()

    for s in scores:
        athlete_uuid = athlete_map.get(s["espn_athlete_id"])
        if not athlete_uuid:
            unmatched += 1
            continue

        records.append({
            "athlete_id":       athlete_uuid,
            "season":           SEASON,
            "model_version":    MODEL_VERSION,
            "calculated_at":    now,
            "volatility_score": s["volatility_score"],
            "risk_label":       s["risk_label"],
            "risk_color":       s["risk_color"],
            "depth_rank":       s["depth_rank"],
            "class_modifier":   s["class_modifier"],
            "breakdown":        json.dumps(s["breakdown"]),
        })

    return records, unmatched


# ── Upsert ────────────────────────────────────────────────────

def upsert_scores(records: list) -> int:
    print(f"  Upserting {len(records):,} volatility scores...")
    inserted = 0
    for batch in batches(records, BATCH_SIZE):
        supabase.table("volatility_scores").upsert(
            batch,
            on_conflict="athlete_id,season,model_version"
        ).execute()
        inserted += len(batch)
        print(f"    {inserted:,} / {len(records):,}", end="\r")
    print(f"\n  Done — {inserted:,} scores upserted")
    return inserted


# ── Log provenance ────────────────────────────────────────────

def log_provenance(fetched, inserted):
    supabase.table("data_provenance").insert({
        "source":           "calculated",
        "entity_type":      "volatility_scores",
        "season":           SEASON,
        "records_fetched":  fetched,
        "records_inserted": inserted,
        "records_updated":  0,
        "records_removed":  0,
        "pulled_at":        datetime.now(timezone.utc).isoformat(),
        "notes":            f"Volatility model {MODEL_VERSION} with class modifier.",
        "raw_config":       {
            "model_version": MODEL_VERSION,
            "roster_csv":    str(ROSTER_CSV),
        },
    }).execute()
    print("  Provenance logged")


# ── Main ──────────────────────────────────────────────────────

def main():
    print(f"Loading roster from {ROSTER_CSV}...")
    df = pd.read_csv(ROSTER_CSV, low_memory=False)
    print(f"  {len(df):,} rows")

    print("\nLoading athlete UUID map from Supabase...")
    athlete_map = load_athlete_map()
    print(f"  {len(athlete_map):,} athletes loaded")

    print("\nScoring all players...")
    scores = score_all(df)
    print(f"  {len(scores):,} players scored")

    print("\nBuilding DB records...")
    records, unmatched = build_records(scores, athlete_map)
    print(f"  {len(records):,} matched | {unmatched:,} unmatched")

    print("\n── Upserting volatility_scores ───────────────────────")
    inserted = upsert_scores(records)

    print("\n── Logging provenance ────────────────────────────────")
    log_provenance(len(scores), inserted)

    # FSU sanity check — top 10 by volatility
    print("\n── FSU volatility sanity check ───────────────────────")
    fsu_scores = [s for s in scores if "Florida State" in s.get("team", "")]
    fsu_sorted = sorted(fsu_scores, key=lambda x: x["volatility_score"], reverse=True)
    print(f"  FSU players scored: {len(fsu_scores)}")
    print(f"  {'Player':<6} {'Pos':<6} {'Class':<12} {'Score':>6} {'Risk'}")
    for s in fsu_sorted[:10]:
        print(f"  {s['position']:<6} {s['class']:<12} {s['volatility_score']:>6.1f}  {s['risk_label']}")

    # Risk summary across all teams
    risk_counts = defaultdict(int)
    for s in scores:
        risk_counts[s["risk_label"]] += 1

    print(f"""
── Summary ───────────────────────────────────────────
  Players scored:     {len(scores):,}
  Scores upserted:    {inserted:,}
  Unmatched:          {unmatched:,}
  Model version:      {MODEL_VERSION}

  Risk distribution:
    CRITICAL: {risk_counts['CRITICAL']:,}
    HIGH:     {risk_counts['HIGH']:,}
    MEDIUM:   {risk_counts['MEDIUM']:,}
    LOW:      {risk_counts['LOW']:,}
──────────────────────────────────────────────────────
""")


if __name__ == "__main__":
    main()