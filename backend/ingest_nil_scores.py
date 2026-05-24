"""
ingest_nil_scores.py — Run NIL similarity model and push to Supabase
=====================================================================
1. Runs nil_similarity_model.py against 2026 roster
2. Matches each player to athletes.id via espn_athlete_id
3. Upserts into nil_valuations table
4. Logs to data_provenance

Run from backend/:
    python3 ingest_nil_scores.py
"""

import os
import math
import warnings
import json
import numpy as np
import pandas as pd
from pathlib import Path
from datetime import datetime, timezone
from dotenv import load_dotenv
from supabase import create_client, Client
from sklearn.preprocessing import StandardScaler
from sklearn.neighbors import NearestNeighbors

# Import model components
from nil_similarity_model import (
    run as run_nil_model,
    ANCHORS, FEATURES, POS_MULT, CLASS_MULT, CLASS_EXP,
    DEPTH_FACTORS, featurize, build_anchors, load_budgets,
    estimate_nil, POSITION_MARKET_RATE
)

warnings.filterwarnings('ignore')
load_dotenv()

SUPABASE_URL = os.environ.get("SUPABASE_URL", "https://fpigpzmgqmzoxdknhetg.supabase.co")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_KEY")
DATA_DIR     = Path(__file__).parent / "data"
ROSTER_CSV   = DATA_DIR / "cfb_rosters_2026_clean.csv"
SIDELINE_JSON = Path(__file__).parent / "sideline-nil-rankings.json"
OUTPUT_CSV   = DATA_DIR / "nil_player_estimates_2026.csv"
SEASON       = 2026
MODEL_VERSION = "v2"
BATCH_SIZE   = 100

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


# ── Load athlete UUID map ─────────────────────────────────────

def load_athlete_map() -> dict:
    """{ espn_athlete_id (int) -> athlete UUID }"""
    all_rows = []
    page = 0
    page_size = 1000
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


# ── Run NIL model ─────────────────────────────────────────────

def run_model() -> pd.DataFrame:
    """Run the NIL similarity model and return results DataFrame."""
    print(f"  Roster:   {ROSTER_CSV}")
    print(f"  Sideline: {SIDELINE_JSON}")
    print(f"  Output:   {OUTPUT_CSV}")

    if not ROSTER_CSV.exists():
        raise FileNotFoundError(f"Roster CSV not found: {ROSTER_CSV}")
    if not SIDELINE_JSON.exists():
        raise FileNotFoundError(f"Sideline JSON not found: {SIDELINE_JSON}")

    # Normalize column names for model compatibility
    df = pd.read_csv(ROSTER_CSV, low_memory=False)

    # Only run model on ESPN players with real data (not portal additions)
    df = df[df["athlete_id"].notna() & (df["athlete_id"] != "")].copy()
    print(f"  Filtered to {len(df):,} ESPN players (excluding portal additions)")
    if "display_name" in df.columns and "player_name" not in df.columns:
        df["player_name"] = df["display_name"]
    if "pos_group" not in df.columns:
        df["pos_group"] = df.get("position_group", "")
    if "depth_rank" not in df.columns:
        if "transfer_value_score" in df.columns:
            df["depth_rank"] = df.groupby(["team", "position"])["transfer_value_score"] \
                .rank(ascending=False, method="first").astype(int)
        else:
            df["depth_rank"] = 2

    # Save temp normalized CSV for model
    tmp = DATA_DIR / "cfb_rosters_2026_model_input.csv"
    df.to_csv(tmp, index=False)

    results = run_nil_model(
        roster_path=str(tmp),
        sideline_path=str(SIDELINE_JSON),
        output_path=str(OUTPUT_CSV),
        k=5
    )
    return results


# ── Build valuation records ───────────────────────────────────

def build_records(results: pd.DataFrame, athlete_map: dict) -> tuple[list, int]:
    """Build nil_valuations records. Returns (records, unmatched_count)."""
    records = []
    unmatched = 0
    now = datetime.now(timezone.utc).isoformat()

    for _, row in results.iterrows():
        # Match to athlete UUID
        espn_id = clean_val(row.get("athlete_id"))
        athlete_uuid = None
        if espn_id is not None:
            try:
                athlete_uuid = athlete_map.get(int(float(espn_id)))
            except (ValueError, TypeError):
                pass

        if not athlete_uuid:
            unmatched += 1
            continue

        pos = str(row.get("position", "")).upper()
        cls = str(row.get("class", ""))
        exp = clean_val(row.get("experience_years"))
        depth = clean_val(row.get("depth_rank"))
        nil_est = clean_val(row.get("nil_estimate"))
        nil_lower = clean_val(row.get("nil_lower"))
        nil_upper = clean_val(row.get("nil_upper"))

        # Build inputs jsonb
        inputs = {
            "position":       pos,
            "class":          cls,
            "experience_years": int(exp) if exp else None,
            "depth_rank":     int(depth) if depth else None,
            "nil_lower":      int(nil_lower) if nil_lower else None,
            "nil_upper":      int(nil_upper) if nil_upper else None,
            "nil_range_str":  clean_val(row.get("nil_range_str")),
            "nil_market_gap": float(row.get("nil_market_gap", 0)),
            "team":           clean_val(row.get("team")),
            "model":          "knn_cosine",
            "k":              5,
            "anchor_count":   len(ANCHORS),
        }

        records.append({
            "athlete_id":           athlete_uuid,
            "season":               SEASON,
            "model_version":        MODEL_VERSION,
            "calculated_at":        now,
            "est_nil_value":        int(nil_est) if nil_est else None,
            "position":             pos,
            "class":                cls,
            "experience_years":     int(exp) if exp else None,
            "depth_rank":           int(depth) if depth else None,
            "inputs":               json.dumps(inputs),
        })

    return records, unmatched


# ── Upsert to Supabase ────────────────────────────────────────

def upsert_valuations(records: list) -> int:
    print(f"  Upserting {len(records):,} NIL valuations...")
    inserted = 0
    for batch in batches(records, BATCH_SIZE):
        supabase.table("nil_valuations").upsert(
            batch,
            on_conflict="athlete_id,season,model_version"
        ).execute()
        inserted += len(batch)
        print(f"    {inserted:,} / {len(records):,}", end="\r")
    print(f"\n  Done — {inserted:,} valuations upserted")
    return inserted


# ── Log provenance ────────────────────────────────────────────

def log_provenance(fetched, inserted):
    supabase.table("data_provenance").insert({
        "source":           "calculated",
        "entity_type":      "nil_valuations",
        "season":           SEASON,
        "records_fetched":  fetched,
        "records_inserted": inserted,
        "records_updated":  0,
        "records_removed":  0,
        "pulled_at":        datetime.now(timezone.utc).isoformat(),
        "notes":            f"NIL similarity model {MODEL_VERSION}. KNN cosine, k=5, {len(ANCHORS)} anchors.",
        "raw_config":       {
            "model_version": MODEL_VERSION,
            "k": 5,
            "anchor_count": len(ANCHORS),
            "roster_csv": str(ROSTER_CSV),
            "sideline_json": str(SIDELINE_JSON),
        },
    }).execute()
    print("  Provenance logged")


# ── Main ──────────────────────────────────────────────────────

def main():
    print("Loading athlete UUID map from Supabase...")
    athlete_map = load_athlete_map()
    print(f"  {len(athlete_map):,} athletes loaded")

    print("\nRunning NIL similarity model...")
    results = run_model()
    print(f"  Model complete — {len(results):,} player estimates")

    print("\nBuilding valuation records...")
    records, unmatched = build_records(results, athlete_map)
    print(f"  {len(records):,} matched | {unmatched:,} unmatched (no ESPN ID)")

    print("\n── Upserting nil_valuations ──────────────────────────")
    inserted = upsert_valuations(records)

    print("\n── Logging provenance ────────────────────────────────")
    log_provenance(len(results), inserted)

    # Sanity check — top 10 FSU players by NIL
    print("\n── FSU NIL sanity check ──────────────────────────────")
    fsu_results = results[
        results["team"].str.contains("Florida State", na=False)
    ].nlargest(10, "nil_estimate")

    for _, r in fsu_results.iterrows():
        print(f"  {r['player_name']:<28} {r['position']:<6} "
              f"${r['nil_estimate']:>8,.0f}  {r['nil_range_str']}")

    print(f"""
── Summary ───────────────────────────────────────────
  Players modeled:      {len(results):,}
  Valuations upserted:  {inserted:,}
  Unmatched:            {unmatched:,}
  Model version:        {MODEL_VERSION}
  Output CSV:           {OUTPUT_CSV}
──────────────────────────────────────────────────────
""")


if __name__ == "__main__":
    main()