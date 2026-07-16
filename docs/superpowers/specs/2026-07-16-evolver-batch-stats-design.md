# Evolver Batch Stats & Dashboard KPI Refinement

**Date:** 2026-07-16
**Status:** Design approved, awaiting plan

## Overview

Two tightly-coupled improvements driven by a single principle: **replace LLM-inferred signals with deterministic Python-computed data**. The evolver currently relies on logic macros (`IS_PHANTOM_ORDER_BIAS`, `IS_OVERFIT_RISK`) that are defined in the prompt but never injected as pre-computed states. Meanwhile, the dashboard lacks KPIs that directly measure order quality (fill rate, take-profit placement, stop-loss structure).

This spec covers three layers:

1. **Dashboard** — 3 new KPIs replacing less useful ones; `/api/trades` extended to supply the data
2. **Evolver data** — 4 new batch-level forensic stats + split of `IS_CATASTROPHIC_MISS`
3. **Evolver prompt** — JUDGMENT_RUBRIC rewritten to consume batch stats instead of phantom boolean macros

---

## 1. Dashboard KPIs

### 1.1 Final KPI Card Layout

7 cards, naturally wrapping in the existing CSS grid (`repeat(auto-fill, minmax(200px, 1fr))`). No artificial limit on count.

| # | KPI | Source | New? | Thresholds (Green / Amber / Red) |
|---|-----|--------|------|----------------------------------|
| 1 | **Net P&L** | cumulative equity from filled trades | Keep | ≥ 0 green, < 0 red |
| 2 | **Win Rate** | TP_HIT / filled | Keep | ≥ 60% / 40-60% / < 40% |
| 3 | **Win/Loss** | avgWin / |avgLoss| | Keep (was previously in grid) | ≥ 2.0 / 1.0-2.0 / < 1.0 |
| 4 | **Max Drawdown** | peak-to-trough equity decline | Keep | < 5% / 5-15% / > 15% |
| 5 | **Fill Rate** | filled / directional (excl. NEUTRAL) | **New** | ≥ 80% / 50-80% / < 50% |
| 6 | **MFE Efficiency** | avg of `mfe_efficiency_pct` across filled | **New** | ≥ 70% / 40-70% / < 40% |
| 7 | **MAE Stress** | % PINPOINT+STANDARD out of filled | **New** | ≥ 70% / 40-70% / < 40% |

Removed:
- **Sharpe Ratio** — replaced by MFE Efficiency (more directly actionable)
- **Executed/Total** — redundant with Fill Rate when confidence threshold = 0

### 1.2 KPI Definitions

**Fill Rate**
```
fill_rate = filled_count / directional_count * 100
```
Directional = opinion is BULLISH or BEARISH. Filled = `is_filled` is True. Only meaningful for the full dataset (threshold = 0). When threshold > 0, the denominator shrinks (only above-threshold sessions count), which changes the semantics — this is fine because the slider is an exploration tool.

**MFE Efficiency**
```
avg of trade_execution_metrics.mfe_efficiency_pct across all filled trades
```
Measures what percentage of the TP distance price actually reached before exit. TP_HIT trades will have ≥ 100%; SL_HIT and NEITHER trades typically < 100%. An average of 40% means price only makes it 40% of the way to TP before reversing — TP is placed too far.

**MAE Stress**
```
(pinpoint_count + standard_count) / filled_count * 100
```
Percentage of filled trades where MAE stress tier is PINPOINT or STANDARD (structurally protected stops). LUCK and FAILURE tiers indicate the stop-loss was placed without adequate structural anchoring.

### 1.3 `/api/trades` — New Fields

Add two fields to each trade record:

```python
trades.append({
    # ... existing fields ...
    "mfe_efficiency_pct": metrics.get("mfe_efficiency_pct") if metrics else None,
    "mae_stress_tier": metrics.get("mae_stress_tier") if metrics else None,
})
```

Where `metrics = outcome.get("trade_execution_metrics", {})`. Both fields already computed in `audit_assembler.py` — just not exposed through the API.

### 1.4 i18n Keys

Add to `TRANSLATIONS` in `i18n.js`:

```javascript
"kpi.fill_rate": { en: "Fill Rate", zh: "成交率" },
"kpi.mfe_efficiency": { en: "MFE Efficiency", zh: "MFE 效率" },
"kpi.mae_stress": { en: "MAE Stress", zh: "MAE 压力" },
```

Remove: `kpi.sharpe`, `kpi.executed`.

### 1.5 Frontend Logic (index.html)

**KPI value computation** — in `updateAllCharts()`, add after existing KPI calculations:

```javascript
// Fill Rate — all directional sessions (threshold-independent baseline)
const allDirectional = trades.filter(t => t.opinion !== 'NEUTRAL');
const allFilled = allDirectional.filter(t => t.is_filled);
const fillRate = allDirectional.length > 0 ? allFilled.length / allDirectional.length * 100 : 0;

// MFE Efficiency — avg across filled trades
const mfeValues = filledTrades.map(t => t.mfe_efficiency_pct).filter(v => v != null);
const mfeEfficiency = mfeValues.length > 0 ? mfeValues.reduce((a,b) => a+b, 0) / mfeValues.length : null;

// MAE Stress — % PINPOINT + STANDARD
const stressTiers = filledTrades.map(t => t.mae_stress_tier).filter(Boolean);
const protectedCount = stressTiers.filter(t => t === 'PINPOINT' || t === 'STANDARD').length;
const maeStress = stressTiers.length > 0 ? protectedCount / stressTiers.length * 100 : null;
```

All three recompute when the confidence slider changes (they depend on `filledTrades` which is threshold-filtered).

### 1.6 CSS

No new CSS needed. Existing `.kpi-card`, `.kpi-value.health-*`, `.kpi-card.health-*` classes cover all 7 cards.

---

## 2. Evolver Batch Stats

### 2.1 New Stats in `compute_evolver_states()` (`regime_states.py`)

**fill_rate_pct** — directional session fill rate
```python
directional = [r for r in audit_reports
    if (r.get("session", {}).get("final_decision", {}).get("opinion") or "").upper() != "NEUTRAL"]
filled = [r for r in directional
    if r.get("market_outcome", {}).get("is_filled")]
fill_rate_pct = round(len(filled) / len(directional) * 100, 1) if directional else 0
```

**near_miss_rate** — of unfilled sessions, % that were close to filling
```python
unfilled = [r for r in directional
    if not r.get("market_outcome", {}).get("is_filled")]
near_miss = [r for r in unfilled
    if r.get("market_outcome", {}).get("execution_forensics", {}).get("is_near_miss")]
near_miss_rate = round(len(near_miss) / len(unfilled) * 100, 1) if unfilled else 0
```

**mae_stress_distribution** — counts per tier
```python
distribution = {"PINPOINT": 0, "STANDARD": 0, "LUCK": 0, "FAILURE": 0}
for r in audit_reports:
    tier = (r.get("market_outcome", {}).get("trade_execution_metrics", {}) or {}).get("mae_stress_tier", "")
    if tier in distribution:
        distribution[tier] += 1
```

**cowardice_tag_rate** — % of NEUTRAL sessions where Critic flagged inaction
```python
cowardice_tags = {"[INACTION_BIAS]", "[TREND_STARVATION]", "[OPPORTUNITY_DENIAL]"}
neutral_sessions = [r for r in audit_reports
    if (r.get("session", {}).get("final_decision", {}).get("opinion") or "").upper() == "NEUTRAL"]
cowardice_count = 0
for r in neutral_sessions:
    history = r.get("session", {}).get("debate_history", []) or []
    for entry in history:
        critic = entry.get("critic", {}) if isinstance(entry, dict) else {}
        for inv in (critic.get("invalidations", []) or []):
            tag = str(inv).split(" - ")[0].strip() if " - " in str(inv) else str(inv)
            if tag in cowardice_tags:
                cowardice_count += 1
                break
cowardice_tag_rate = round(cowardice_count / len(neutral_sessions) * 100, 1) if neutral_sessions else 0
```

### 2.2 Split `IS_CATASTROPHIC_MISS`

Delete existing `IS_CATASTROPHIC_MISS`. Add two new fields:

```python
is_catastrophic_neutral_miss = any(
    (r.get("session", {}).get("final_decision", {}).get("opinion") or "").upper() == "NEUTRAL"
    and r.get("forensic_verdict", {}).get("is_catastrophic_miss") is True
    for r in audit_reports
)

is_catastrophic_unfilled_miss = any(
    (r.get("session", {}).get("final_decision", {}).get("opinion") or "").upper() != "NEUTRAL"
    and r.get("forensic_verdict", {}).get("is_catastrophic_miss") is True
    for r in audit_reports
)
```

Return both in the evolver states dict (replacing the old single `IS_CATASTROPHIC_MISS`).

### 2.3 Injection (`evolver_agent.py`)

Pass new stats to `_prepare_prompt`:
```python
fill_rate_pct=evolver_states.get("fill_rate_pct", 0),
near_miss_rate=evolver_states.get("near_miss_rate", 0),
mae_stress_distribution=evolver_states.get("mae_stress_distribution", {}),
cowardice_tag_rate=evolver_states.get("cowardice_tag_rate", 0),
```

---

## 3. Evolver Prompt (`evolver.md`)

### 3.1 LOGIC_MACROS — Remove Two

Delete `IS_PHANTOM_ORDER_BIAS` and `IS_OVERFIT_RISK` from the LOGIC_MACROS section. These were never pre-computed and forced the LLM into unreliable inference.

- `IS_PHANTOM_ORDER_BIAS` → replaced by `fill_rate_pct` + `near_miss_rate` in JUDGMENT_RUBRIC
- `IS_OVERFIT_RISK` → left to sandbox validation; ANTI-OVERFITTING LAW remains as qualitative guidance

### 3.2 INPUT_DATUM — Add Batch Forensic Stats

After the existing PRE-COMPUTED STATES block, add:

```markdown
- **Batch Forensic Stats**: Pre-computed from `{audit_reports_json}`. Use as given.
  - `fill_rate_pct` (`{fill_rate_pct}`): % of directional sessions where entry was filled.
  - `near_miss_rate` (`{near_miss_rate}`): Of unfilled sessions, % where entry was within the proximity limit (almost filled).
  - `mae_stress_distribution` (`{mae_stress_distribution}`): Counts of PINPOINT / STANDARD / LUCK / FAILURE stress tiers across filled trades.
  - `cowardice_tag_rate` (`{cowardice_tag_rate}`): % of NEUTRAL sessions where the Critic flagged inaction bias, trend starvation, or opportunity denial.
```

### 3.3 PRE-COMPUTED STATES — Update Evolver States

Replace `IS_CATASTROPHIC_MISS` with the two split fields in the documented Evolver States list.

### 3.4 JUDGMENT_RUBRIC — Rewrite Trigger Blocks

**THE_OPPORTUNITY_COST** (was: `IS_PROFIT_EVAPORATION OR IS_PHANTOM_ORDER_BIAS`):

```markdown
- **THE_OPPORTUNITY_COST** (Profit Evaporation & Phantom Orders):
  - Trigger: `IS_PROFIT_EVAPORATION` is TRUE
    OR (`fill_rate_pct` < 60 AND `near_miss_rate` < 30)
  - Diagnosis: The system is either demanding unrealistic entry depths (phantom
    orders — low fill rate, and even the unfilled ones weren't close) or failing
    to secure floating profits before time expires.
  - Action: `AGGRESSIVE_REFINEMENT`.
    - Targets: Decrease `min_rr_ranging`, decrease `breakout_frontrun_atr`, or
      refine `session.md` to mandate proximity-based entries.
    - Goal: Force the system to actively engage the market and lock in realistic
      yields rather than holding out for theoretical perfection.
```

**THE_COWARDICE_TRAP** (was: `IS_LOGIC_COWARDICE OR IS_CATASTROPHIC_MISS`):

```markdown
- **THE_COWARDICE_TRAP** (Logic Hardening):
  - Trigger: `IS_LOGIC_COWARDICE` is TRUE
    OR `IS_CATASTROPHIC_NEUTRAL_MISS` is TRUE
    OR `cowardice_tag_rate` > 40
  - Diagnosis: System correctly identifies directional opportunities but
    surrenders to NEUTRAL — either through Critic veto pressure or internal
    timidity. The `cowardice_tag_rate` confirms this is a pattern, not an
    isolated incident.
  - Action: `SEMANTIC_REFINEMENT`.
    - Targets: Modify `session.md` or `critic.md` to grant momentum exemptions
      (e.g., allowing Shallow Pullbacks when `IS_TREND_STRONG` is true).
    - Goal: Eliminate instructional bottlenecks that prevent trend participation.
```

**THE_PHANTOM_ORDER_FIX** (new):

```markdown
- **THE_PHANTOM_ORDER_FIX** (Entry Proximity Tightening):
  - Trigger: `IS_CATASTROPHIC_UNFILLED_MISS` is TRUE
    OR (`fill_rate_pct` < 60 AND `near_miss_rate` >= 30)
  - Diagnosis: Directional entries are unfilled, but many are near-misses — the
    entry proximity logic is slightly too conservative. Price is coming close
    but not quite reaching the limit order.
  - Action: `AGGRESSIVE_REFINEMENT`.
    - Targets: Decrease `max_entry_distance_atr` or reduce `breakout_frontrun_atr`
      to pull entries closer to current price.
    - Goal: Convert near-misses into fills without sacrificing structural anchoring.
```

### 3.5 ANTI-OVERFITTING LAW — Keep

Keep the section unchanged. `IS_OVERFIT_RISK` is removed from LOGIC_MACROS but the qualitative principle ("a patch is a failure if it breaks previously successful trades") remains. This is validated by the sandbox, not the LLM.

---

## 4. Files Changed

| File | Change |
|------|--------|
| `src/dashboard/templates/index.html` | Replace KPI cards (Sharpe → MFE Efficiency, Executed/Total → Fill Rate + MAE Stress), add JS computation |
| `src/dashboard/static/i18n.js` | Add 3 KPI keys, remove 2 |
| `src/dashboard/api/audits.py` | `/api/trades` returns `mfe_efficiency_pct` + `mae_stress_tier` |
| `src/analyzer/regime_states.py` | `compute_evolver_states()` — add 4 batch stats, split `IS_CATASTROPHIC_MISS` |
| `src/agent/evolver_agent.py` | `evolve()` — inject 4 new stats into prompt template |
| `config/prompts/evolver.md` | Remove 2 LOGIC_MACROS, add INPUT_DATUM block, rewrite 2 JUDGMENT_RUBRIC entries, add 1 new entry |

## 5. Non-Goals

- No LLM output schema changes (Session, Critic, Evolver schemas unchanged)
- No new config keys (batch stat thresholds are hardcoded in evolver.md)
- No NEUTRAL reason-code changes (cowardice_tag_rate derived from existing Critic tags)
- Confidence Calibration Curve (user confirmed not needed)
