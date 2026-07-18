"""
nil_similarity_model_v2.py — NIL Player Valuation via Similarity
=================================================================
Production-ready model. Estimates NIL value for every FBS player.

Key improvements over v1:
  - Extended anchor set covering full NIL value range ($25K-$5.4M)
  - Depth rank differentiates starters vs backups properly
  - Long snapper / kicker / punter handled correctly
  - Outputs range estimate (honest uncertainty)
  - Ready to wire into PortalIQ API

Usage:
    python3 nil_similarity_model_v2.py \
        --roster path/to/cfb_rosters_2026_clean.csv \
        --sideline path/to/sideline-nil-rankings.json \
        --output path/to/nil_player_estimates.csv
"""

import json
import warnings
import argparse
import re
import unicodedata
import numpy as np
import pandas as pd
from pathlib import Path
from sklearn.preprocessing import StandardScaler
from sklearn.neighbors import NearestNeighbors

warnings.filterwarnings('ignore')

# ── Feature mappings ──────────────────────────────────────────

POS_MULT = {
    'QB': 1.00, 'WR': 0.52, 'EDGE': 0.52, 'OT': 0.50,
    'CB': 0.47, 'S': 0.39, 'SAF': 0.39, 'LB': 0.36,
    'DL': 0.36, 'DT': 0.36, 'DE': 0.52, 'IOL': 0.33,
    'RB': 0.33, 'TE': 0.30, 'K': 0.17, 'P': 0.17,
    'LS': 0.11, 'ATH': 0.30, 'C': 0.33, 'G': 0.33,
    'OL': 0.33, 'HB': 0.33, 'FB': 0.22, 'PK': 0.17,
    'DB': 0.43, 'NT': 0.36, 'SAM': 0.36, 'MIKE': 0.36,
    'WILL': 0.36, 'KR': 0.24,
}

POS_ALIAS = {
    'HB': 'RB', 'PK': 'K', 'FS': 'S', 'SS': 'S',
    'LT': 'OT', 'RT': 'OT', 'LG': 'IOL', 'RG': 'IOL',
    'G': 'IOL', 'C': 'IOL', 'OL': 'IOL', 'NT': 'DT',
    'SAM': 'LB', 'MIKE': 'LB', 'WILL': 'LB', 'DB': 'CB',
}

CLASS_MULT = {
    'Senior': 1.20, 'SR': 1.20, 'Graduate': 1.35, 'GR': 1.35,
    'Junior': 1.00, 'JR': 1.00, 'RS-JR': 1.05, 'RS-SR': 1.25,
    'Sophomore': 0.75, 'SO': 0.75, 'RS-SO': 0.80,
    'Freshman': 0.60, 'FR': 0.60, 'RS-FR': 0.65,
}

CLASS_EXP = {
    'Senior': 1.0, 'SR': 1.0, 'Graduate': 1.0, 'GR': 1.0, 'RS-SR': 1.0,
    'Junior': 0.75, 'JR': 0.75, 'RS-JR': 0.75,
    'Sophomore': 0.50, 'SO': 0.50, 'RS-SO': 0.50,
    'Freshman': 0.25, 'FR': 0.25, 'RS-FR': 0.25,
}

DEPTH_FACTORS = {1: 1.0, 2: 0.65, 3: 0.40, 4: 0.25}

POSITION_CAPS = {
    'QB': 5500000, 'WR': 2200000, 'EDGE': 2200000, 'OT': 1800000,
    'CB': 1600000, 'S': 1400000, 'LB': 1100000, 'DL': 1100000,
    'DT': 1100000, 'DE': 2200000, 'IOL': 900000, 'RB': 1100000,
    'TE': 850000, 'K': 125000, 'P': 90000, 'LS': 65000,
    'ATH': 500000, 'FB': 175000, 'KR': 175000,
}

DEPTH_CAP_MULT = {1: 1.0, 2: 0.45, 3: 0.25, 4: 0.15}

FEATURES = ['pos_mult', 'class_mult', 'depth_factor',
            'budget_norm', 'conf_mult', 'exp_norm']

DEFAULT_EA_RATINGS = Path(__file__).resolve().parents[1] / "scripts" / "data" / "ea_cf27_ratings.csv"
_BUDGET_LOOKUP_CACHE = {}

PLAYER_MARKET_FLOORS = {
    ("ducerobinson", "floridastate"): 1500000,
    ("quintrevionwisner", "floridastate"): 650000,
}

# ── Anchor dataset ────────────────────────────────────────────
# Known + disclosed NIL values + calibrated synthetic anchors

ANCHORS = [
    # Top known NIL values (On3)
    {'name': 'Arch Manning',        'pos': 'QB',   'school': 'Texas',           'nil': 5400000, 'depth': 1, 'cls': 'Senior'},
    {'name': 'Jeremiah Smith',      'pos': 'WR',   'school': 'Ohio State',      'nil': 4200000, 'depth': 1, 'cls': 'Junior'},
    {'name': 'Sam Leavitt',         'pos': 'QB',   'school': 'LSU',             'nil': 4000000, 'depth': 1, 'cls': 'Junior'},
    {'name': 'Brendan Sorsby',      'pos': 'QB',   'school': 'Texas Tech',      'nil': 3100000, 'depth': 1, 'cls': 'Senior'},
    {'name': 'Bryce Underwood',     'pos': 'QB',   'school': 'Michigan',        'nil': 3100000, 'depth': 1, 'cls': 'Sophomore'},
    {'name': 'Dante Moore',         'pos': 'QB',   'school': 'Oregon',          'nil': 3000000, 'depth': 1, 'cls': 'Senior'},
    {'name': 'Cam Coleman',         'pos': 'WR',   'school': 'Texas',           'nil': 2900000, 'depth': 1, 'cls': 'Junior'},
    {'name': 'LaNorris Sellers',    'pos': 'QB',   'school': 'South Carolina',  'nil': 2700000, 'depth': 1, 'cls': 'Senior'},
    {'name': 'Dylan Stewart',       'pos': 'EDGE', 'school': 'South Carolina',  'nil': 2500000, 'depth': 1, 'cls': 'Junior'},
    {'name': 'Josh Hoover',         'pos': 'QB',   'school': 'Indiana',         'nil': 2300000, 'depth': 1, 'cls': 'Senior'},
    {'name': 'Darian Mensah',       'pos': 'QB',   'school': 'Miami',           'nil': 2200000, 'depth': 1, 'cls': 'Junior'},
    {'name': 'Jackson Cantwell',    'pos': 'OT',   'school': 'Miami',           'nil': 1900000, 'depth': 1, 'cls': 'Freshman'},
    {'name': 'Jordan Seaton',       'pos': 'OT',   'school': 'LSU',             'nil': 1700000, 'depth': 1, 'cls': 'Junior'},
    {'name': 'Ryan Williams',       'pos': 'WR',   'school': 'Alabama',         'nil': 1600000, 'depth': 1, 'cls': 'Sophomore'},
    {'name': 'Caleb Downs',         'pos': 'S',    'school': 'Ohio State',      'nil': 1600000, 'depth': 1, 'cls': 'Junior'},
    {'name': 'Colin Simmons',       'pos': 'EDGE', 'school': 'Texas',           'nil': 1500000, 'depth': 1, 'cls': 'Junior'},
    # Disclosed portal/contract values
    {'name': 'Duce Robinson',       'pos': 'WR',   'school': 'Florida State',   'nil': 920000,  'depth': 1, 'cls': 'Junior'},
    {'name': 'Xavier Chaplin',      'pos': 'OT',   'school': 'Florida State',   'nil': 743000,  'depth': 1, 'cls': 'Junior'},
    {'name': 'Earl Little Jr',      'pos': 'S',    'school': 'Ohio State',      'nil': 239000,  'depth': 1, 'cls': 'Junior'},
    {'name': 'James Williams EDGE', 'pos': 'EDGE', 'school': 'Florida State',   'nil': 150000,  'depth': 1, 'cls': 'Junior'},
    {'name': 'Lawayne McCoy',       'pos': 'WR',   'school': 'Louisville',      'nil': 121000,  'depth': 2, 'cls': 'Sophomore'},
    {'name': 'Jayvan Boggs',        'pos': 'WR',   'school': 'Florida State',   'nil': 120000,  'depth': 3, 'cls': 'Freshman'},
    {'name': 'LaJesse Harrold',     'pos': 'EDGE', 'school': 'Florida State',   'nil': 116000,  'depth': 2, 'cls': 'Freshman'},
    # Calibrated mid-range anchors
    {'name': '_starter_QB_mid',     'pos': 'QB',   'school': 'Florida State',   'nil': 400000,  'depth': 1, 'cls': 'Senior'},
    {'name': '_backup_QB_P4',       'pos': 'QB',   'school': 'Florida State',   'nil': 120000,  'depth': 2, 'cls': 'Sophomore'},
    {'name': '_3rd_QB_P4',          'pos': 'QB',   'school': 'Florida State',   'nil': 60000,   'depth': 3, 'cls': 'Freshman'},
    {'name': '_starter_WR_mid',     'pos': 'WR',   'school': 'Georgia',         'nil': 280000,  'depth': 2, 'cls': 'Junior'},
    {'name': '_starter_OT_P4',      'pos': 'OT',   'school': 'Alabama',         'nil': 250000,  'depth': 2, 'cls': 'Junior'},
    {'name': '_starter_CB_P4',      'pos': 'CB',   'school': 'Ohio State',      'nil': 200000,  'depth': 2, 'cls': 'Junior'},
    {'name': '_starter_LB_P4',      'pos': 'LB',   'school': 'Michigan',        'nil': 150000,  'depth': 2, 'cls': 'Junior'},
    {'name': '_starter_RB_P4',      'pos': 'RB',   'school': 'Texas',           'nil': 180000,  'depth': 2, 'cls': 'Junior'},
    {'name': '_starter_DL_P4',      'pos': 'DL',   'school': 'Georgia',         'nil': 150000,  'depth': 1, 'cls': 'Senior'},
    {'name': '_starter_IOL_P4',     'pos': 'IOL',  'school': 'Alabama',         'nil': 120000,  'depth': 1, 'cls': 'Senior'},
    {'name': '_starter_TE_P4',      'pos': 'TE',   'school': 'Michigan',        'nil': 100000,  'depth': 1, 'cls': 'Senior'},
    {'name': '_backup_skill_P4',    'pos': 'WR',   'school': 'Florida State',   'nil': 75000,   'depth': 3, 'cls': 'Sophomore'},
    {'name': '_g5_starter_QB',      'pos': 'QB',   'school': 'Appalachian State','nil': 120000, 'depth': 1, 'cls': 'Senior'},
    {'name': '_g5_starter_WR',      'pos': 'WR',   'school': 'Troy',            'nil': 50000,   'depth': 1, 'cls': 'Senior'},
    {'name': '_g5_starter_DL',      'pos': 'DL',   'school': 'Troy',            'nil': 35000,   'depth': 1, 'cls': 'Senior'},
    {'name': '_kicker_P4',          'pos': 'K',    'school': 'Georgia',         'nil': 25000,   'depth': 1, 'cls': 'Senior'},
    {'name': '_punter_P4',          'pos': 'P',    'school': 'Alabama',         'nil': 20000,   'depth': 1, 'cls': 'Senior'},
    {'name': '_longsnapper_P4',     'pos': 'LS',   'school': 'Michigan',        'nil': 18000,   'depth': 1, 'cls': 'Senior'},
    {'name': '_freshman_bench',     'pos': 'LB',   'school': 'Alabama',         'nil': 30000,   'depth': 4, 'cls': 'Freshman'},
]


def load_budgets(sideline_path: str) -> dict:
    with open(sideline_path) as f:
        data = json.load(f)
    budgets = {}
    for item in data['data']:
        school = item['school']
        for s in item.get('sports', []):
            if isinstance(s, dict) and 'Football' in s.get('sport', ''):
                budgets[school] = float(s.get('spend', 5.0))
                break
        if school not in budgets:
            budgets[school] = 5.0
    return budgets


def get_budget(school: str, budgets: dict) -> float:
    if school in budgets:
        return budgets[school]
    school_key = normalize_team(school)
    cache_key = id(budgets)
    budget_keys = _BUDGET_LOOKUP_CACHE.get(cache_key)
    if budget_keys is None:
        budget_keys = {normalize_team(k): v for k, v in budgets.items()}
        _BUDGET_LOOKUP_CACHE[cache_key] = budget_keys
    if school_key in budget_keys:
        return budget_keys[school_key]
    for key, v in budget_keys.items():
        if school_key and key and (school_key.startswith(key) or key.startswith(school_key)):
            return v
    return 8.0


def canonical_position(pos) -> str:
    pos = str(pos or "ATH").upper().strip()
    return POS_ALIAS.get(pos, pos)


def featurize(pos, cls, depth, school, budgets, max_budget):
    pos = canonical_position(pos)
    budget = get_budget(school, budgets)
    return {
        'pos_mult':     POS_MULT.get(pos, 0.30),
        'class_mult':   CLASS_MULT.get(str(cls), 0.75),
        'depth_factor': DEPTH_FACTORS.get(int(depth) if str(depth).isdigit() else 1, 0.25),
        'budget_norm':  budget / max_budget,
        'conf_mult':    1.05 if budget > 20
                        else 0.95 if budget > 10
                        else 0.65,
        'exp_norm':     CLASS_EXP.get(str(cls), 0.50),
    }


def build_anchors(budgets: dict, max_budget: float):
    rows = []
    for a in ANCHORS:
        f = featurize(a['pos'], a['cls'], a['depth'], a['school'], budgets, max_budget)
        f['name'] = a['name']
        f['nil']  = a['nil']
        rows.append(f)
    return pd.DataFrame(rows)


def normalize_name(value: str) -> str:
    text = unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode()
    text = re.sub(r"\b(jr|sr|ii|iii|iv|v)\b\.?", "", text, flags=re.I)
    return re.sub(r"[^a-z0-9]+", "", text.lower())


def normalize_team(value: str) -> str:
    text = str(value or "").lower()
    for word in (
        "tigers", "bulldogs", "seminoles", "crimson tide", "buckeyes", "longhorns",
        "wolverines", "hurricanes", "wildcats", "cardinals", "trojans", "aggies",
        "cougars", "panthers", "mountaineers", "bearcats", "bears", "rebels",
        "volunteers", "gators", "ducks", "gamecocks", "nittany lions",
    ):
        text = text.replace(word, "")
    return re.sub(r"[^a-z0-9]+", "", text)


def teams_match(left: str, right: str) -> bool:
    left_key = normalize_team(left)
    right_key = normalize_team(right)
    return bool(left_key and right_key and (left_key in right_key or right_key in left_key))


def load_ea_ratings(ea_path: str | Path | None) -> pd.DataFrame:
    if not ea_path:
        return pd.DataFrame()

    path = Path(ea_path)
    if not path.exists():
        print(f"  EA ratings not found: {path}")
        return pd.DataFrame()

    ea = pd.read_csv(path)
    required = {"name", "position", "team", "ovr"}
    missing = required - set(ea.columns)
    if missing:
        raise ValueError(f"EA ratings CSV missing columns: {sorted(missing)}")

    ea = ea.copy()
    ea["name_key"] = ea["name"].map(normalize_name)
    ea["team_key"] = ea["team"].map(normalize_team)
    for col in ["ovr", "spd", "str", "agi", "awr"]:
        if col in ea.columns:
            ea[col] = pd.to_numeric(ea[col], errors="coerce")
    ea = ea[ea["name_key"].ne("") & ea["ovr"].between(40, 100, inclusive="both")]
    return ea


def attach_ea_ratings(roster: pd.DataFrame, ea: pd.DataFrame) -> pd.DataFrame:
    roster = roster.copy()
    for col in ["ea_ovr", "ea_spd", "ea_str", "ea_agi", "ea_awr", "ea_position"]:
        roster[col] = np.nan if col != "ea_position" else ""

    if ea.empty:
        roster["ea_match"] = False
        return roster

    by_name = {name: grp for name, grp in ea.groupby("name_key")}
    matches = 0
    for idx, row in roster.iterrows():
        name_key = normalize_name(row.get("display_name", row.get("player_name", "")))
        candidates = by_name.get(name_key)
        if candidates is None:
            continue

        team = row.get("team", "")
        team_matches = candidates[candidates["team"].map(lambda ea_team: teams_match(team, ea_team))]
        if team_matches.empty:
            continue

        candidate = team_matches.sort_values("ovr", ascending=False).iloc[0]
        roster.at[idx, "ea_position"] = candidate.get("position", "")
        for src, dest in [("ovr", "ea_ovr"), ("spd", "ea_spd"), ("str", "ea_str"), ("agi", "ea_agi"), ("awr", "ea_awr")]:
            if src in candidate:
                roster.at[idx, dest] = candidate.get(src)
        matches += 1

    roster["ea_match"] = roster["ea_ovr"].notna()
    print(f"  EA ratings matched: {matches:,} / {len(roster):,}")
    return roster


def ensure_depth_rank(roster: pd.DataFrame) -> pd.DataFrame:
    roster = roster.copy()
    if "depth_rank" in roster.columns and roster["depth_rank"].notna().any():
        roster["depth_rank"] = pd.to_numeric(roster["depth_rank"], errors="coerce").fillna(2).astype(int)
        return roster

    if "transfer_value_score" in roster.columns:
        score = pd.to_numeric(roster["transfer_value_score"], errors="coerce").fillna(0)
    else:
        class_score = roster.get("class", pd.Series("", index=roster.index)).map(CLASS_EXP).fillna(0.25)
        exp_score = pd.to_numeric(roster.get("experience_years", 0), errors="coerce").fillna(0).clip(0, 4) / 4
        ea_ovr = pd.to_numeric(roster.get("ea_ovr"), errors="coerce")
        ea_score = (ea_ovr / 100).fillna(0)
        no_ea_penalty = np.where(ea_ovr.notna(), 0, -0.10)
        score = (ea_score * 0.70) + (exp_score * 0.20) + (class_score * 0.10) + no_ea_penalty

    roster["_depth_score"] = score
    roster["_position_key"] = roster["position"].map(canonical_position)
    roster["depth_rank"] = roster.groupby(["team", "_position_key"])["_depth_score"] \
        .rank(ascending=False, method="first").astype(int)
    roster = roster.drop(columns=["_depth_score", "_position_key"])
    return roster


def apply_ea_adjustment(estimates: np.ndarray, roster: pd.DataFrame) -> np.ndarray:
    adjusted = estimates.astype(float).copy()
    ovr = pd.to_numeric(roster.get("ea_ovr"), errors="coerce")
    if ovr.isna().all():
        return estimates

    # OVR is a player-quality signal, not an NIL market by itself. Keep it bounded.
    factors = 1 + ((ovr - 75) / 100)
    factors = factors.clip(lower=0.85, upper=1.25).fillna(1.0)
    return np.round(adjusted * factors.to_numpy()).astype(int)


def apply_market_caps(values: np.ndarray, roster: pd.DataFrame) -> np.ndarray:
    capped = values.astype(float).copy()
    for i, (_, row) in enumerate(roster.iterrows()):
        pos = canonical_position(row.get("position"))
        depth = row.get("depth_rank", 2)
        try:
            depth = int(depth)
        except (TypeError, ValueError):
            depth = 2
        depth = min(max(depth, 1), 4)
        cap = POSITION_CAPS.get(pos, 500000) * DEPTH_CAP_MULT.get(depth, 0.15)
        capped[i] = min(capped[i], cap)
    return np.round(capped).astype(int)


def apply_player_market_floors(values: np.ndarray, roster: pd.DataFrame) -> np.ndarray:
    adjusted = values.astype(float).copy()
    for i, (_, row) in enumerate(roster.iterrows()):
        player_key = normalize_name(row.get("display_name", row.get("player_name", "")))
        team_key = normalize_team(row.get("team", ""))
        floor = PLAYER_MARKET_FLOORS.get((player_key, team_key))
        if floor:
            adjusted[i] = max(adjusted[i], floor)
    return np.round(adjusted).astype(int)


def estimate_nil(X_query, X_anchors_sc, y_anchors, knn):
    distances, indices = knn.kneighbors(X_query)
    estimates, lowers, uppers = [], [], []
    for i in range(len(X_query)):
        sims    = np.clip(1 - distances[i], 0, 1)
        weights = sims / sims.sum() if sims.sum() > 0 else np.ones(len(sims)) / len(sims)
        nils    = y_anchors[indices[i]]
        estimates.append(int(np.dot(weights, nils)))
        lowers.append(int(np.percentile(nils, 15)))
        uppers.append(int(np.percentile(nils, 85)))
    return np.array(estimates), np.array(lowers), np.array(uppers)


def run(roster_path: str, sideline_path: str, output_path: str, k: int = 5, ea_path: str | None = None):
    print("=" * 65)
    print("NIL PLAYER SIMILARITY MODEL v2")
    print("=" * 65)

    # Load
    print("\n[1] Loading data...")
    roster = pd.read_csv(roster_path)
    ea = load_ea_ratings(ea_path or DEFAULT_EA_RATINGS)
    roster = attach_ea_ratings(roster, ea)
    roster = ensure_depth_rank(roster)
    budgets = load_budgets(sideline_path)
    max_budget = max(budgets.values())

    print(f"  Players:  {len(roster):,}")
    print(f"  Schools with budgets: {len(budgets):,}")
    print(f"  Anchors: {len(ANCHORS):,}")

    # Build anchors
    print("\n[2] Building anchor features...")
    anchor_df = build_anchors(budgets, max_budget)
    X_anchors = anchor_df[FEATURES].values
    y_anchors = anchor_df['nil'].values

    scaler = StandardScaler()
    X_anchors_sc = scaler.fit_transform(X_anchors)

    # Build roster features
    print("\n[3] Featurizing roster players...")
    feat_rows = []
    for _, row in roster.iterrows():
        f = featurize(
            pos=row.get('position', 'ATH'),
            cls=row.get('class', 'Sophomore'),
            depth=row.get('depth_rank', 2),
            school=row.get('team', ''),
            budgets=budgets,
            max_budget=max_budget,
        )
        feat_rows.append(f)

    feat_df = pd.DataFrame(feat_rows)
    X_roster = scaler.transform(feat_df[FEATURES].fillna(0).values)

    # KNN
    print(f"\n[4] Computing K={k} nearest neighbors...")
    knn = NearestNeighbors(n_neighbors=min(k, len(ANCHORS)), metric='cosine')
    knn.fit(X_anchors_sc)
    estimates, lowers, uppers = estimate_nil(X_roster, X_anchors_sc, y_anchors, knn)
    estimates = apply_ea_adjustment(estimates, roster)
    estimates = apply_market_caps(estimates, roster)
    estimates = apply_player_market_floors(estimates, roster)
    lowers = np.minimum(lowers, estimates)
    uppers = np.maximum(np.minimum(uppers, estimates * 2), estimates)

    # Output
    print("\n[5] Building output...")
    roster['depth_rank'] = roster.get('depth_rank', 2)  # default to backup if missing
    out = roster[['display_name', 'position', 'position_group', 'class',
                  'experience_years', 'depth_rank', 'team', 'athlete_id',
                  'headshot', 'jersey']].copy()
    out = out.rename(columns={'display_name': 'player_name', 'position_group': 'pos_group'})
    for col in ["ea_ovr", "ea_spd", "ea_str", "ea_agi", "ea_awr", "ea_position", "ea_match"]:
        out[col] = roster[col]

    out['nil_estimate']  = estimates
    out['nil_lower']     = lowers
    out['nil_upper']     = uppers
    out['nil_range_str'] = out.apply(
        lambda r: f"${r['nil_lower']/1000:.0f}K–${r['nil_upper']/1000:.0f}K", axis=1
    )
    out['nil_market_gap'] = out.apply(
        lambda r: max(0, (
            POSITION_MARKET_RATE(r['position']) - r['nil_estimate']
        ) / max(POSITION_MARKET_RATE(r['position']), 1)),
        axis=1
    ).round(3)

    out.to_csv(output_path, index=False)
    print(f"  Saved {len(out):,} player estimates → {output_path}")

    # Summary
    print("\n" + "=" * 65)
    print("RESULTS")
    print("=" * 65)
    print(f"\n  Mean estimate:   ${out['nil_estimate'].mean():>10,.0f}")
    print(f"  Median estimate: ${out['nil_estimate'].median():>10,.0f}")

    print("\n  Top 15 estimated values:")
    for _, r in out.nlargest(15, 'nil_estimate').iterrows():
        print(f"    {r['player_name']:28} {r['position']:5} {r['team']:25} "
              f"${r['nil_estimate']:>8,.0f}  {r['nil_range_str']}")

    print("\n  Position medians:")
    for pos, med in out.groupby('position')['nil_estimate']\
            .median().sort_values(ascending=False).items():
        print(f"    {pos:6}  ${med:>8,.0f}")

    return out


def POSITION_MARKET_RATE(pos):
    base = {
        'QB': 180000, 'WR': 95000, 'EDGE': 95000, 'OT': 90000,
        'CB': 85000, 'S': 70000, 'SAF': 70000, 'LB': 65000,
        'DL': 65000, 'DT': 65000, 'DE': 95000, 'IOL': 60000,
        'RB': 60000, 'TE': 55000, 'K': 25000, 'P': 20000, 'LS': 18000,
    }
    return base.get(str(pos).upper(), 50000)


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--roster',   required=True)
    p.add_argument('--sideline', required=True)
    p.add_argument('--output',   default='nil_player_estimates.csv')
    p.add_argument('--k',        type=int, default=5)
    p.add_argument('--ea-ratings', default=str(DEFAULT_EA_RATINGS),
                   help='Optional EA/CFBLabs ratings CSV')
    a = p.parse_args()
    run(a.roster, a.sideline, a.output, a.k, a.ea_ratings)
