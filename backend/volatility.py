"""
volatility.py — RosterEdge Volatility Scoring Engine
=====================================================
Predicts which players are at risk of entering the transfer portal.

v1 inputs (available now):
  - transfer_value_score   → portal attractiveness
  - est_player_nil_cost    → NIL market gap
  - depth_rank             → depth chart pressure
  - position count         → positional overcrowding
  - eligibility            → career stage

v2 inputs (coming with CFBD API):
  - snap_share             → usage % vs expected
  - epa_per_play           → production vs opportunity
  - portal_history_count   → serial transferor flag
  - coaching_change_flag   → environmental volatility
  - social_sentiment       → soft signals
"""

# ── Weights (v1) ──────────────────────────────────────────────
VOLATILITY_WEIGHTS = {
    "transfer_value_score": 0.30,   # How attractive to other programs
    "nil_market_gap":       0.25,   # Underpaid vs position market
    "depth_pressure":       0.20,   # Positional overcrowding
    "depth_rank_risk":      0.15,   # Starter vs buried
    "eligibility_risk":     0.10,   # Career stage / portal savviness
}

# ── Position NIL market rates ─────────────────────────────────
# Average FBS NIL cost by position — underpaid = flight risk
POSITION_MARKET_NIL = {
    "QB":   180000,
    "WR":    95000,
    "EDGE":  95000,
    "OT":    90000,
    "CB":    85000,
    "S":     70000,
    "LB":    65000,
    "DL":    65000,
    "IOL":   60000,
    "RB":    60000,
    "TE":    55000,
    "K":     30000,
    "P":     30000,
}

# ── Risk labels ───────────────────────────────────────────────
RISK_THRESHOLDS = [
    (70, "CRITICAL", "#ef4444"),
    (50, "HIGH",     "#f97316"),
    (30, "MEDIUM",   "#eab308"),
    (0,  "LOW",      "#22c55e"),
]

def get_risk_label(score: float) -> tuple[str, str]:
    for threshold, label, color in RISK_THRESHOLDS:
        if score >= threshold:
            return label, color
    return "LOW", "#22c55e"


def score_volatility(player: dict, position_counts: dict) -> dict:
    """
    Score a single player's volatility risk (0-100).

    Args:
        player:          Player dict from enriched_transfers data
        position_counts: {position: count} across the full roster

    Returns:
        Dict with volatility_score, risk_label, risk_color, breakdown
    """
    pos = player.get("position", "")

    # ── 1. Transfer value score ───────────────────────────────
    # How attractive this player is to other programs
    # High TVS = poaching target = flight risk
    tvs_raw = float(player.get("transfer_value_score") or 0)
    tvs = min(tvs_raw, 1.5) / 1.5   # normalize to 0-1

    # ── 2. NIL market gap ─────────────────────────────────────
    # Is this player being paid below market for their position?
    # Underpaid = more likely to seek a better deal elsewhere
    market_rate  = POSITION_MARKET_NIL.get(pos, 60000)
    actual_cost  = float(player.get("est_player_nil_cost") or 50000)
    nil_gap      = max(0.0, (market_rate - actual_cost) / market_rate)

    # ── 3. Depth pressure ─────────────────────────────────────
    # More players at same position = more competition = harder to keep everyone
    pos_count      = position_counts.get(pos, 1)
    depth_pressure = min(pos_count / 5.0, 1.0)   # 5+ players = max pressure

    # ── 4. Depth rank risk ────────────────────────────────────
    # Starters: attractive to poachers (moderate risk)
    # Backups:  want more snaps → leave (high risk)
    depth_rank = int(player.get("depth_rank") or 1)
    depth_rank_risk = {
        1: 0.55,    # Starter — poaching target
        2: 0.50,    # Backup — watching playing time
        3: 0.70,    # Third string — likely frustrated
    }.get(depth_rank, 0.85)  # 4th+ — very high risk

    # ── 5. Eligibility risk ───────────────────────────────────
    # Immediate eligibility = already portal-savvy = more likely to move again
    eligibility      = player.get("eligibility", "")
    eligibility_risk = 0.70 if eligibility == "Immediate" else 0.40

    # ── Weighted composite ────────────────────────────────────
    raw = (
        tvs              * VOLATILITY_WEIGHTS["transfer_value_score"] +
        nil_gap          * VOLATILITY_WEIGHTS["nil_market_gap"] +
        depth_pressure   * VOLATILITY_WEIGHTS["depth_pressure"] +
        depth_rank_risk  * VOLATILITY_WEIGHTS["depth_rank_risk"] +
        eligibility_risk * VOLATILITY_WEIGHTS["eligibility_risk"]
    )

    score = round(min(raw * 100, 100), 1)
    label, color = get_risk_label(score)

    return {
        "volatility_score": score,
        "risk_label":       label,
        "risk_color":       color,
        "breakdown": {
            "portal_attractiveness": round(tvs * 100, 1),
            "nil_market_gap":        round(nil_gap * 100, 1),
            "depth_pressure":        round(depth_pressure * 100, 1),
            "depth_rank_risk":       round(depth_rank_risk * 100, 1),
            "eligibility_risk":      round(eligibility_risk * 100, 1),
        },
    }