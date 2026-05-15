# RosterEdge Volatility Model
## Product Specification & Technical Reference
**Version:** 1.0 | **Status:** v1 Built, v2 Roadmap Defined

---

## What It Is

The RosterEdge Volatility Model predicts which players on a roster are at risk of entering the transfer portal. It scores every player 0–100 and produces a **Team Volatility Index** — a signature metric that tells coaching staffs and front offices where their roster is unstable before it becomes a crisis.

---

## The Output (What Coaches See)

### 1. Player Volatility Score (0–100)
| Score | Label | Color | Meaning |
|-------|-------|-------|---------|
| 70–100 | CRITICAL | 🔴 Red | Very likely to transfer — act now |
| 50–69 | HIGH | 🟠 Orange | Elevated risk — monitor closely |
| 30–49 | MEDIUM | 🟡 Yellow | Some risk factors — keep engaged |
| 0–29 | LOW | 🟢 Green | Likely to stay |

### 2. Position Group Volatility
> "RB room volatility: 72 (CRITICAL)"

### 3. Team Volatility Index
Your signature metric. A single number representing overall roster stability. Comparable across programs, trackable over time.

### 4. Estimated NIL Retention Cost
Dollar estimate of what it would cost to retain all CRITICAL + HIGH players.

---

## v1 Model (Built — Live on Railway)

### Inputs & Weights

| Input | Weight | Source | What It Captures |
|-------|--------|--------|-----------------|
| `transfer_value_score` | 30% | PortalIQ enriched transfers | How attractive this player is to other programs |
| `nil_market_gap` | 25% | `est_player_nil_cost` vs position market rate | Underpaid = flight risk |
| `depth_pressure` | 20% | Position player count | Overcrowding at same position |
| `depth_rank_risk` | 15% | `depth_rank` | Starter vs buried on depth chart |
| `eligibility_risk` | 10% | `eligibility` field | Portal-savvy players move again |

### Position NIL Market Rates (v1)
```python
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
```

### Scoring Formula
```
volatility_score = (
    normalize(transfer_value_score) * 0.30 +
    nil_market_gap                  * 0.25 +
    depth_pressure                  * 0.20 +
    depth_rank_risk                 * 0.15 +
    eligibility_risk                * 0.10
) * 100
```

### Depth Rank Risk Logic
```
depth_rank = 1 → 0.55  (starter — poaching target)
depth_rank = 2 → 0.50  (backup — watching playing time)
depth_rank = 3 → 0.70  (third string — likely frustrated)
depth_rank = 4+ → 0.85 (buried — very high risk)
```

### API Endpoint
```
GET /players/volatility/{team}

Parameters:
  team       (str)   — team name e.g. "Florida State"
  season     (int)   — optional, defaults to latest
  min_score  (float) — filter to players above score threshold

Response:
{
  "team": "Florida State",
  "season": 2026,
  "team_volatility_index": 61.4,
  "risk_summary": {
    "critical": 3,
    "high": 8,
    "medium": 7,
    "low": 4
  },
  "estimated_retention_cost": 847200,
  "position_volatility": {
    "Offense": { "avg_volatility": 58.2, "risk_label": "HIGH" },
    "Defense": { "avg_volatility": 63.1, "risk_label": "HIGH" }
  },
  "players": [
    {
      "player_name": "Duce Robinson",
      "position": "WR",
      "volatility_score": 74.2,
      "risk_label": "CRITICAL",
      "breakdown": { ... }
    }
  ]
}
```

---

## v2 Model (Roadmap — CFBD API + Additional Sources)

### Additional Inputs

| Input | Weight | Source | What It Captures |
|-------|--------|--------|-----------------|
| `snap_share` | +15% | CFBD play-by-play | Usage % vs expected by position |
| `snap_share_delta` | +10% | CFBD season-over-season | Losing snaps = flight risk |
| `epa_per_play` | +10% | CFBD advanced stats | Production vs opportunity gap |
| `portal_history_count` | +8% | Transfer history | Serial transferors move again |
| `coaching_change_flag` | +7% | Staff tracking | New scheme = movement |
| `position_coach_change` | +5% | Staff tracking | New position coach = disruption |

### The "Performance vs Opportunity Gap"
The most predictive signal:
> High production + low usage = CRITICAL flight risk

```python
perf_opportunity_gap = (epa_per_play_rank - snap_share_rank)
# Positive = outperforming role = wants more
# Negative = underperforming = coach may move on first
```

### Social Signal Layer (v3)
- Transfer portal follow/unfollow patterns
- Engagement with team content declining
- Portal-adjacent account follows
- Public sentiment shift

---

## The Differentiator

Most tools track:
- Stats
- Depth chart
- Star ratings

RosterEdge models:
- NIL economics (underpaid = flight risk)
- Roster construction pressure (overcrowding)
- Multi-year volatility forecasting
- Environmental signals (coaching, scheme)
- Performance vs opportunity gap

**That's the moat.**

---

## Files

| File | Location | Purpose |
|------|----------|---------|
| `volatility.py` | `backend/` | Scoring engine — weights, formulas, risk labels |
| `routers/players.py` | `backend/routers/` | FastAPI endpoint `/players/volatility/{team}` |

---

## Demo Script (Minute 2–7)

> "This is the holy shit moment."

1. Pull up `rosteredge.app`
2. Select Florida State
3. Click **Volatility** tab
4. Show Team Volatility Index: **61.4**
5. Show CRITICAL players — "These 3 players are likely gone in December"
6. Show estimated retention cost: **$847,200**
7. Show position group breakdown — "Your WR room is your biggest risk"

> "Most programs find out their players left when they see it on Twitter.
> RosterEdge tells you 6 months before."

---

## Changelog

| Version | Date | Notes |
|---------|------|-------|
| v1.0 | May 2026 | Built on existing PortalIQ fields — 5 inputs, weighted linear model |
| v2.0 | TBD | CFBD snap data, EPA, coaching signals |
| v3.0 | TBD | Social sentiment, predictive ML (logistic regression / XGBoost) |