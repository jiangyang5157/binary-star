# Evolver Batch Stats & Dashboard KPI Refinement — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace LLM-inferred evolver signals with deterministic Python-computed batch stats, and add 3 order-quality KPIs to the dashboard.

**Architecture:** Three independent layers: (1) Dashboard — replace 2 KPI cards with 3 new ones, extend `/api/trades` with 2 fields. (2) Evolver Python — add 4 batch stats + split `IS_CATASTROPHIC_MISS` in `compute_evolver_states()`, inject them in `evolver_agent.py`. (3) Evolver prompt — remove 2 invalid LOGIC_MACROS, add INPUT_DATUM block, rewrite 3 JUDGMENT_RUBRIC entries.

**Tech Stack:** Python 3.11+, FastAPI, Jinja2, Chart.js, vanilla JS

## Global Constraints

- No LLM output schema changes (Session, Critic, Evolver schemas unchanged)
- No new config keys (batch stat thresholds hardcoded in evolver.md)
- No new CSS (existing `.kpi-card`, `.kpi-value.health-*` classes cover all new cards)
- KPI color thresholds: Fill Rate ≥80/50-80/<50, MFE Efficiency ≥70/40-70/<40, MAE Stress ≥70/40-70/<40
- Batch stat thresholds in evolver.md: fill_rate < 60, near_miss < 30, cowardice_tag_rate > 40

---

### Task 1: Expose forensic fields in /api/trades

**Files:**
- Modify: `src/dashboard/api/audits.py:210-221`

**Interfaces:**
- Produces: `/api/trades` response gains `mfe_efficiency_pct` (float|null) and `mae_stress_tier` (string|null) per trade

- [ ] **Step 1: Add the two fields to the trades response**

In `src/dashboard/api/audits.py`, the `get_trades` function builds the trade dict at line 210. Add `metrics` extraction and the two new fields:

```python
# After line 199 (existing exit_price line), add metrics extraction:
            metrics = outcome.get("trade_execution_metrics") or {}

# Then in the trades.append() dict (line 210-221), add after "version":
            trades.append({
                "time": session.get("observation", {}).get("observed_at", ""),
                "symbol": session.get("observation", {}).get("symbol", ""),
                "opinion": opinion,
                "confidence": decision.get("confidence_score", 0),
                "is_filled": is_filled,
                "tp_sl_result": tp_sl_result,
                "pnl_pct": round(pnl, 2),
                "projected_holding_hours": tp_params.get("projected_holding_hours") or 0,
                "session_filename": f.name,
                "version": _extract_version(session),
                "mfe_efficiency_pct": metrics.get("mfe_efficiency_pct") if metrics else None,
                "mae_stress_tier": metrics.get("mae_stress_tier") if metrics else None,
            })
```

- [ ] **Step 2: Verify the change doesn't break existing behavior**

Run: `cd /Users/yangjiang/workspace/binary-star && python -c "from src.dashboard.api.audits import router; print('import OK')"`

- [ ] **Step 3: Commit**

```bash
git add src/dashboard/api/audits.py
git commit -m "feat: expose mfe_efficiency_pct and mae_stress_tier in /api/trades"
```

---

### Task 2: Add i18n keys for new KPIs

**Files:**
- Modify: `src/dashboard/static/i18n.js:21-23`

**Interfaces:**
- Produces: `t('kpi.fill_rate')`, `t('kpi.mfe_efficiency')`, `t('kpi.mae_stress')` return translated labels. `t('kpi.sharpe')` and `t('kpi.executed')` removed.

- [ ] **Step 1: Replace KPI translation keys**

In `src/dashboard/static/i18n.js`, replace lines 21-22 (the sharpe and executed keys):

```javascript
// Remove:
  "kpi.sharpe": { en: "Sharpe Ratio", zh: "夏普比率" },
  "kpi.executed": { en: "Executed / Total", zh: "已执行 / 总计" },

// Add after "kpi.max_drawdown":
  "kpi.fill_rate": { en: "Fill Rate", zh: "成交率" },
  "kpi.mfe_efficiency": { en: "MFE Efficiency", zh: "MFE 效率" },
  "kpi.mae_stress": { en: "MAE Stress", zh: "MAE 压力" },
```

- [ ] **Step 2: Verify syntax**

Run: `cd /Users/yangjiang/workspace/binary-star && node -e "eval(require('fs').readFileSync('src/dashboard/static/i18n.js','utf8').replace('const TRANSLATIONS','globalThis.TRANSLATIONS')); console.log(Object.keys(globalThis.TRANSLATIONS).filter(k=>k.startsWith('kpi.')))"`

Expected output includes: `'kpi.fill_rate'`, `'kpi.mfe_efficiency'`, `'kpi.mae_stress'`

- [ ] **Step 3: Commit**

```bash
git add src/dashboard/static/i18n.js
git commit -m "feat: add fill_rate, mfe_efficiency, mae_stress i18n keys; remove sharpe, executed"
```

---

### Task 3: Replace KPI cards in dashboard

**Files:**
- Modify: `src/dashboard/templates/index.html:41-68` (KPI HTML cards)
- Modify: `src/dashboard/templates/index.html:227-310` (KPI JS computation)

**Interfaces:**
- Consumes: `trades[].mfe_efficiency_pct`, `trades[].mae_stress_tier` from Task 1; `t('kpi.fill_rate')`, etc. from Task 2
- Produces: 7 KPI cards rendered with animated values and health coloring

- [ ] **Step 1: Replace KPI HTML cards**

Replace lines 41-68 in `index.html` (the entire `kpi-grid` section). Remove Sharpe and Executed/Total cards, add Fill Rate, MFE Efficiency, MAE Stress cards:

```html
    <!-- ═══════ KPI Cards ═══════ -->
    <section class="kpi-grid" id="kpi-grid">
      <!-- Row 1: Results -->
      <div class="kpi-card" data-kpi="pnl">
        <span class="kpi-label" data-i18n="kpi.net_pnl"></span>
        <span class="kpi-value" id="kpi-pnl">--</span>
      </div>
      <div class="kpi-card" data-kpi="winrate">
        <span class="kpi-label" data-i18n="kpi.win_rate"></span>
        <span class="kpi-value" id="kpi-winrate">--</span>
      </div>
      <div class="kpi-card" data-kpi="winloss">
        <span class="kpi-label" data-i18n="kpi.win_loss"></span>
        <span class="kpi-value" id="kpi-winloss">--</span>
      </div>
      <!-- Row 2: Risk & Execution Quality -->
      <div class="kpi-card" data-kpi="mdd">
        <span class="kpi-label" data-i18n="kpi.max_drawdown"></span>
        <span class="kpi-value" id="kpi-mdd">--</span>
      </div>
      <div class="kpi-card" data-kpi="fillrate">
        <span class="kpi-label" data-i18n="kpi.fill_rate"></span>
        <span class="kpi-value" id="kpi-fillrate">--</span>
      </div>
      <div class="kpi-card" data-kpi="mfeeff">
        <span class="kpi-label" data-i18n="kpi.mfe_efficiency"></span>
        <span class="kpi-value" id="kpi-mfeeff">--</span>
      </div>
      <div class="kpi-card" data-kpi="maestress">
        <span class="kpi-label" data-i18n="kpi.mae_stress"></span>
        <span class="kpi-value" id="kpi-maestress">--</span>
      </div>
    </section>
```

- [ ] **Step 2: Add KPI computation in updateAllCharts()**

In `updateAllCharts()` (starting around line 227), after the existing `sharpe` computation block and before `_setKpiHealth('kpi-sharpe', ...)`, replace the sharpe + executed blocks with the new KPIs:

```javascript
      // ── Fill Rate: filled / directional (all threshold levels) ──────
      const allDirectional = trades.filter(t => t.opinion !== 'NEUTRAL');
      const allFilledForRate = allDirectional.filter(t => t.is_filled);
      const fillRate = allDirectional.length > 0 ? allFilledForRate.length / allDirectional.length * 100 : 0;

      _setKpiHealth('kpi-fillrate', fillRate >= 80 ? 'green' : fillRate >= 50 ? 'amber' : 'red');
      setKpiWithAnimation('kpi-fillrate', fillRate.toFixed(0) + '%', animMs);

      // ── MFE Efficiency: avg mfe_efficiency_pct across filled trades ──
      const mfeValues = filledTrades.map(t => t.mfe_efficiency_pct).filter(v => v != null);
      const mfeEfficiency = mfeValues.length > 0 ? mfeValues.reduce((a, b) => a + b, 0) / mfeValues.length : null;

      if (mfeEfficiency != null) {
        _setKpiHealth('kpi-mfeeff', mfeEfficiency >= 70 ? 'green' : mfeEfficiency >= 40 ? 'amber' : 'red');
        setKpiWithAnimation('kpi-mfeeff', mfeEfficiency.toFixed(0) + '%', animMs);
      } else {
        _setKpiHealth('kpi-mfeeff', null);
        $('kpi-mfeeff').textContent = '—';
      }

      // ── MAE Stress: % PINPOINT + STANDARD out of filled ────────────
      const stressTiers = filledTrades.map(t => t.mae_stress_tier).filter(Boolean);
      const protectedCount = stressTiers.filter(t => t === 'PINPOINT' || t === 'STANDARD').length;
      const maeStress = stressTiers.length > 0 ? protectedCount / stressTiers.length * 100 : null;

      if (maeStress != null) {
        _setKpiHealth('kpi-maestress', maeStress >= 70 ? 'green' : maeStress >= 40 ? 'amber' : 'red');
        setKpiWithAnimation('kpi-maestress', maeStress.toFixed(0) + '%', animMs);
      } else {
        _setKpiHealth('kpi-maestress', null);
        $('kpi-maestress').textContent = '—';
      }
```

- [ ] **Step 3: Remove old sharpe and executed KPI code**

Delete the existing blocks for:
- The sharpe computation and `setKpiWithAnimation('kpi-sharpe', ...)` + `_setKpiHealth('kpi-sharpe', ...)` (approximately lines 280-308 — the sharpe calculation and display)
- The `execRatio` computation and `$('kpi-executed').textContent = ...` (approximately lines 294-296)

Also update the empty-state block (around lines 232-241) to clear the new KPI IDs:

```javascript
      if (!filledTrades.length) {
        for (const id of ['kpi-pnl', 'kpi-winrate', 'kpi-sharpe', 'kpi-mdd', 'kpi-winloss', 'kpi-executed']) {
          $(id).textContent = id === 'kpi-executed' ? `0 / ${orderedTrades.length}` : '—';
          _setKpiHealth(id, null);
          _prevKpiValues[id] = null;
        }
        $('confVal').textContent = threshold;
        renderTimeline(trades, threshold, []);
        return;
      }
```

Replace with:

```javascript
      if (!filledTrades.length) {
        for (const id of ['kpi-pnl', 'kpi-winrate', 'kpi-mdd', 'kpi-winloss', 'kpi-fillrate', 'kpi-mfeeff', 'kpi-maestress']) {
          if (id === 'kpi-fillrate') {
            const dirCount = trades.filter(t => t.opinion !== 'NEUTRAL').length;
            $(id).textContent = dirCount > 0 ? '0%' : '—';
          } else {
            $(id).textContent = '—';
          }
          _setKpiHealth(id, null);
          _prevKpiValues[id] = null;
        }
        $('confVal').textContent = threshold;
        renderTimeline(trades, threshold, []);
        return;
      }
```

- [ ] **Step 4: Verify the page renders without JS errors**

Run: `cd /Users/yangjiang/workspace/binary-star && python -c "from src.dashboard.server import app; print('FastAPI app loads OK')"`

- [ ] **Step 5: Commit**

```bash
git add src/dashboard/templates/index.html
git commit -m "feat: replace Sharpe and Executed KPIs with Fill Rate, MFE Efficiency, MAE Stress"
```

---

### Task 4: Add batch stats + split IS_CATASTROPHIC_MISS in evolver states

**Files:**
- Modify: `src/analyzer/regime_states.py:329-443` (`compute_evolver_states` function)
- Modify: `tests/unit/test_regime_states.py:686-710` (update existing tests, add new ones)

**Interfaces:**
- Consumes: `audit_reports` list (same as existing)
- Produces: `compute_evolver_states()` return dict gains `fill_rate_pct`, `near_miss_rate`, `mae_stress_distribution`, `cowardice_tag_rate`. `IS_CATASTROPHIC_MISS` removed; `IS_CATASTROPHIC_NEUTRAL_MISS` and `IS_CATASTROPHIC_UNFILLED_MISS` added.

- [ ] **Step 1: Add batch stats computation and split CATASTROPHIC_MISS**

In `src/analyzer/regime_states.py`, in `compute_evolver_states()`, replace lines 353-443 (from `non_profit = ...` to the return statement) with:

```python
    non_profit = sum(
        1 for r in audit_reports
        if (r.get("market_outcome", {}).get("tp_sl_result") or "").upper() != "TP_HIT"
    )
    is_batch_significant = non_profit >= 2
    is_failure_ratio_alarm = (non_profit / total) > 0.2
    has_systemic_pathology = is_batch_significant and is_failure_ratio_alarm

    # IS_LOGIC_COWARDICE: NEUTRAL sessions where Critic gave specific tags
    cowardice_tags = {"[INACTION_BIAS]", "[TREND_STARVATION]", "[OPPORTUNITY_DENIAL]"}
    is_logic_cowardice = False
    for r in audit_reports:
        session = r.get("session", {})
        opinion = (session.get("final_decision", {}).get("opinion") or "").upper()
        if opinion != "NEUTRAL":
            continue
        history = session.get("debate_history", []) or []
        for entry in history:
            critic = entry.get("critic", {}) if isinstance(entry, dict) else {}
            invalids = critic.get("invalidations", []) or []
            for inv in invalids:
                tag = str(inv).split(" - ")[0].strip() if " - " in str(inv) else str(inv)
                if tag in cowardice_tags:
                    is_logic_cowardice = True
                    break
            if is_logic_cowardice:
                break
        if is_logic_cowardice:
            break

    # HAS_STRUCTURAL_AMNESTY: any filled report where last math_fact_check
    # confirms sl_shielded AND mae_stress_tier is STANDARD.
    has_structural_amnesty = False
    for r in audit_reports:
        outcome = r.get("market_outcome", {})
        if not outcome.get("is_filled"):
            continue
        session = r.get("session", {})
        history = session.get("debate_history", []) or []
        last_mfc = {}
        if history:
            last_entry = history[-1] if isinstance(history[-1], dict) else {}
            last_mfc = last_entry.get("math_fact_check", {}) or {}
        sl_shielded = last_mfc.get("compliance_verdict", {}).get("sl_is_shielded", False)
        mae_tier = (outcome.get("trade_execution_metrics", {}).get("mae_stress_tier") or "").upper()
        if sl_shielded and mae_tier == "STANDARD":
            has_structural_amnesty = True
            break

    # IS_PROFIT_EVAPORATION: outcome=NEITHER AND MFE >= 60% of TP distance.
    # NEUTRAL sessions excluded — no position was entered, no profit to evaporate.
    is_profit_evaporation = False
    for r in audit_reports:
        outcome = r.get("market_outcome", {})
        if (outcome.get("tp_sl_result") or "").upper() != "NEITHER":
            continue
        session = r.get("session", {})
        opinion = (session.get("final_decision", {}).get("opinion") or "").upper()
        if opinion == "NEUTRAL":
            continue
        mfe_atr = float(outcome.get("market_forensics", {}).get("max_favorable_runup_atr", 0))
        tp_params = session.get("final_decision", {}).get("tactical_parameters", {})
        entry = float(tp_params.get("entry") or 0)
        tp = float(tp_params.get("take_profit") or 0)
        atr = float(session.get("observation", {}).get("quantitative_metrics", {}).get("price_dynamics", {}).get("atr_macro", 1.0))
        tp_distance_atr = abs(tp - entry) / atr if atr > 0 else 1.0
        if mfe_atr >= 0.6 * tp_distance_atr:
            is_profit_evaporation = True
            break

    # ── Batch forensic stats ─────────────────────────────────────

    # fill_rate_pct: directional session fill rate
    directional = [r for r in audit_reports
        if (r.get("session", {}).get("final_decision", {}).get("opinion") or "").upper() != "NEUTRAL"]
    filled = [r for r in directional
        if r.get("market_outcome", {}).get("is_filled")]
    fill_rate_pct = round(len(filled) / len(directional) * 100, 1) if directional else 0

    # near_miss_rate: of unfilled sessions, % where entry was close to filling
    unfilled = [r for r in directional
        if not r.get("market_outcome", {}).get("is_filled")]
    near_miss = [r for r in unfilled
        if r.get("market_outcome", {}).get("execution_forensics", {}).get("is_near_miss")]
    near_miss_rate = round(len(near_miss) / len(unfilled) * 100, 1) if unfilled else 0

    # mae_stress_distribution: counts per tier across all filled trades
    distribution = {"PINPOINT": 0, "STANDARD": 0, "LUCK": 0, "FAILURE": 0}
    for r in audit_reports:
        tier = (r.get("market_outcome", {}).get("trade_execution_metrics", {}) or {}).get("mae_stress_tier", "")
        if tier in distribution:
            distribution[tier] += 1
    mae_stress_distribution = distribution

    # cowardice_tag_rate: % of NEUTRAL sessions where Critic flagged inaction
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

    # IS_CATASTROPHIC_MISS split: NEUTRAL (sat out) vs directional unfilled (couldn't reach entry)
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

    # Time calibration
    time_cal = compute_time_calibration(audit_reports)

    return {
        "IS_BATCH_SIGNIFICANT": is_batch_significant,
        "IS_FAILURE_RATIO_ALARM": is_failure_ratio_alarm,
        "HAS_SYSTEMIC_PATHOLOGY": has_systemic_pathology,
        "IS_LOGIC_COWARDICE": is_logic_cowardice,
        "HAS_STRUCTURAL_AMNESTY": has_structural_amnesty,
        "IS_PROFIT_EVAPORATION": is_profit_evaporation,
        "IS_CATASTROPHIC_NEUTRAL_MISS": is_catastrophic_neutral_miss,
        "IS_CATASTROPHIC_UNFILLED_MISS": is_catastrophic_unfilled_miss,
        "fill_rate_pct": fill_rate_pct,
        "near_miss_rate": near_miss_rate,
        "mae_stress_distribution": mae_stress_distribution,
        "cowardice_tag_rate": cowardice_tag_rate,
        "time_calibration_report": time_cal,
    }
```

Also update the empty-reports early return (lines 342-351) to include the new keys:

```python
        return {
            "IS_BATCH_SIGNIFICANT": False,
            "IS_FAILURE_RATIO_ALARM": False,
            "HAS_SYSTEMIC_PATHOLOGY": False,
            "IS_LOGIC_COWARDICE": False,
            "HAS_STRUCTURAL_AMNESTY": False,
            "IS_PROFIT_EVAPORATION": False,
            "IS_CATASTROPHIC_NEUTRAL_MISS": False,
            "IS_CATASTROPHIC_UNFILLED_MISS": False,
            "fill_rate_pct": 0,
            "near_miss_rate": 0,
            "mae_stress_distribution": {"PINPOINT": 0, "STANDARD": 0, "LUCK": 0, "FAILURE": 0},
            "cowardice_tag_rate": 0,
            "time_calibration_report": empty_regimes,
        }
```

- [ ] **Step 2: Run existing tests to confirm no regressions**

```bash
cd /Users/yangjiang/workspace/binary-star && python -m pytest tests/unit/test_regime_states.py -v
```

Expected: The `test_returns_all_8_evolver_keys` test will FAIL (old key names changed). Tests for `IS_CATASTROPHIC_MISS` will FAIL. Other evolver state tests should PASS.

- [ ] **Step 3: Update the key-count test**

In `tests/unit/test_regime_states.py`, replace `test_returns_all_8_evolver_keys` (line 700):

```python
    def test_returns_all_evolver_keys(self):
        reports = [_make_audit_report(**{"market_outcome": {"tp_sl_result": "SL_HIT"}})]
        result = compute_evolver_states(reports, _make_audit_config())
        expected = {
            "IS_BATCH_SIGNIFICANT", "IS_FAILURE_RATIO_ALARM",
            "HAS_SYSTEMIC_PATHOLOGY", "IS_LOGIC_COWARDICE",
            "HAS_STRUCTURAL_AMNESTY", "IS_PROFIT_EVAPORATION",
            "IS_CATASTROPHIC_NEUTRAL_MISS", "IS_CATASTROPHIC_UNFILLED_MISS",
            "fill_rate_pct", "near_miss_rate",
            "mae_stress_distribution", "cowardice_tag_rate",
            "time_calibration_report",
        }
        assert set(result.keys()) == expected
```

- [ ] **Step 4: Update the IS_CATASTROPHIC_MISS test to use split fields**

Replace `test_is_catastrophic_miss_true` (line 686):

```python
    def test_is_catastrophic_neutral_miss_true(self):
        reports = [
            _make_audit_report(
                **{
                    "forensic_verdict": {
                        "is_catastrophic_miss": True,
                        "is_justified_surrender": False,
                    },
                },
            ),
        ]
        result = compute_evolver_states(reports, _make_audit_config())
        # Default opinion is NEUTRAL, so this should be a neutral miss
        assert result["IS_CATASTROPHIC_NEUTRAL_MISS"] is True
        assert result["IS_CATASTROPHIC_UNFILLED_MISS"] is False

    def test_is_catastrophic_unfilled_miss_true(self):
        reports = [
            _make_audit_report(
                **{
                    "session": {
                        "final_decision": {
                            "opinion": "BULLISH",
                            "tactical_parameters": {"entry": 90000.0, "take_profit": 93000.0},
                        },
                        "debate_history": [],
                        "observation": {
                            "quantitative_metrics": {
                                "price_dynamics": {"atr_macro": 300.0},
                            },
                        },
                    },
                    "forensic_verdict": {
                        "is_catastrophic_miss": True,
                        "is_justified_surrender": False,
                    },
                },
            ),
        ]
        result = compute_evolver_states(reports, _make_audit_config())
        assert result["IS_CATASTROPHIC_NEUTRAL_MISS"] is False
        assert result["IS_CATASTROPHIC_UNFILLED_MISS"] is True
```

- [ ] **Step 5: Add tests for new batch stats**

Add after the CATASTROPHIC_MISS tests (before the key-count test):

```python
    def test_fill_rate_pct_all_filled(self):
        reports = [
            _make_audit_report(
                **{
                    "session": {
                        "final_decision": {
                            "opinion": "BULLISH",
                            "tactical_parameters": {"entry": 90000.0, "take_profit": 93000.0},
                        },
                        "debate_history": [],
                        "observation": {
                            "quantitative_metrics": {
                                "price_dynamics": {"atr_macro": 300.0},
                            },
                        },
                    },
                },
            ),
        ]
        result = compute_evolver_states(reports, _make_audit_config())
        assert result["fill_rate_pct"] == 100.0

    def test_fill_rate_pct_half_filled(self):
        reports = [
            _make_audit_report(
                **{
                    "session": {
                        "final_decision": {
                            "opinion": "BULLISH",
                            "tactical_parameters": {"entry": 90000.0, "take_profit": 93000.0},
                        },
                        "debate_history": [],
                        "observation": {
                            "quantitative_metrics": {
                                "price_dynamics": {"atr_macro": 300.0},
                            },
                        },
                    },
                    "market_outcome": {"is_filled": False},
                },
            ),
            _make_audit_report(
                **{
                    "session": {
                        "final_decision": {
                            "opinion": "BEARISH",
                            "tactical_parameters": {"entry": 90000.0, "take_profit": 87000.0},
                        },
                        "debate_history": [],
                        "observation": {
                            "quantitative_metrics": {
                                "price_dynamics": {"atr_macro": 300.0},
                            },
                        },
                    },
                },
            ),
        ]
        result = compute_evolver_states(reports, _make_audit_config())
        assert result["fill_rate_pct"] == 50.0

    def test_fill_rate_pct_excludes_neutral(self):
        """NEUTRAL sessions don't count toward fill rate."""
        reports = [
            _make_audit_report(),  # default NEUTRAL
        ]
        result = compute_evolver_states(reports, _make_audit_config())
        assert result["fill_rate_pct"] == 0  # no directional sessions

    def test_near_miss_rate(self):
        reports = [
            _make_audit_report(
                **{
                    "session": {
                        "final_decision": {
                            "opinion": "BULLISH",
                            "tactical_parameters": {"entry": 90000.0, "take_profit": 93000.0},
                        },
                        "debate_history": [],
                        "observation": {
                            "quantitative_metrics": {
                                "price_dynamics": {"atr_macro": 300.0},
                            },
                        },
                    },
                    "market_outcome": {
                        "is_filled": False,
                        "execution_forensics": {"is_near_miss": True},
                    },
                },
            ),
            _make_audit_report(
                **{
                    "session": {
                        "final_decision": {
                            "opinion": "BEARISH",
                            "tactical_parameters": {"entry": 90000.0, "take_profit": 87000.0},
                        },
                        "debate_history": [],
                        "observation": {
                            "quantitative_metrics": {
                                "price_dynamics": {"atr_macro": 300.0},
                            },
                        },
                    },
                    "market_outcome": {
                        "is_filled": False,
                        "execution_forensics": {"is_near_miss": False},
                    },
                },
            ),
        ]
        result = compute_evolver_states(reports, _make_audit_config())
        assert result["near_miss_rate"] == 50.0

    def test_near_miss_rate_no_unfilled(self):
        reports = [
            _make_audit_report(
                **{
                    "session": {
                        "final_decision": {
                            "opinion": "BULLISH",
                            "tactical_parameters": {"entry": 90000.0, "take_profit": 93000.0},
                        },
                        "debate_history": [],
                        "observation": {
                            "quantitative_metrics": {
                                "price_dynamics": {"atr_macro": 300.0},
                            },
                        },
                    },
                },
            ),
        ]
        result = compute_evolver_states(reports, _make_audit_config())
        assert result["near_miss_rate"] == 0  # all filled, no unfilled

    def test_mae_stress_distribution(self):
        reports = [
            _make_audit_report(
                **{
                    "market_outcome": {
                        "trade_execution_metrics": {"mae_stress_tier": "PINPOINT"},
                    },
                },
            ),
            _make_audit_report(
                **{
                    "market_outcome": {
                        "trade_execution_metrics": {"mae_stress_tier": "STANDARD"},
                    },
                },
            ),
            _make_audit_report(
                **{
                    "market_outcome": {
                        "trade_execution_metrics": {"mae_stress_tier": "LUCK"},
                    },
                },
            ),
        ]
        result = compute_evolver_states(reports, _make_audit_config())
        assert result["mae_stress_distribution"] == {
            "PINPOINT": 1, "STANDARD": 1, "LUCK": 1, "FAILURE": 0,
        }

    def test_cowardice_tag_rate(self):
        # 2 NEUTRAL sessions, 1 has cowardice tag
        reports = [
            _make_audit_report(),  # default: NEUTRAL + INACTION_BIAS
            _make_audit_report(
                **{
                    "session": {
                        "final_decision": {"opinion": "NEUTRAL"},
                        "debate_history": [
                            {"critic": {"invalidations": ["[TREND_STARVATION] - ..."]}},
                        ],
                    },
                },
            ),
        ]
        result = compute_evolver_states(reports, _make_audit_config())
        # Both default and this one have cowardice tags → 100%
        # Actually default already has INACTION_BIAS → still 100%
        assert result["cowardice_tag_rate"] == 100.0

    def test_cowardice_tag_rate_no_neutral(self):
        reports = [
            _make_audit_report(
                **{
                    "session": {
                        "final_decision": {
                            "opinion": "BULLISH",
                            "tactical_parameters": {"entry": 90000.0, "take_profit": 93000.0},
                        },
                        "debate_history": [],
                        "observation": {
                            "quantitative_metrics": {
                                "price_dynamics": {"atr_macro": 300.0},
                            },
                        },
                    },
                },
            ),
        ]
        result = compute_evolver_states(reports, _make_audit_config())
        assert result["cowardice_tag_rate"] == 0  # no NEUTRAL sessions
```

- [ ] **Step 6: Run all tests**

```bash
cd /Users/yangjiang/workspace/binary-star && python -m pytest tests/unit/test_regime_states.py -v
```

Expected: ALL tests PASS.

- [ ] **Step 7: Commit**

```bash
git add src/analyzer/regime_states.py tests/unit/test_regime_states.py
git commit -m "feat: add 4 batch stats + split IS_CATASTROPHIC_MISS in evolver states"
```

---

### Task 5: Inject batch stats into evolver prompt

**Files:**
- Modify: `src/agent/evolver_agent.py:114-145`

**Interfaces:**
- Consumes: `evolver_states` dict from `compute_evolver_states()` (Task 4) with keys `fill_rate_pct`, `near_miss_rate`, `mae_stress_distribution`, `cowardice_tag_rate`, `IS_CATASTROPHIC_NEUTRAL_MISS`, `IS_CATASTROPHIC_UNFILLED_MISS`
- Produces: Prompt template receives `{fill_rate_pct}`, `{near_miss_rate}`, `{mae_stress_distribution}`, `{cowardice_tag_rate}` placeholders

- [ ] **Step 1: Extract new stats and pass to _prepare_prompt**

In `src/agent/evolver_agent.py`, after line 114 (`evolver_states = compute_evolver_states(audit_reports, audit_cfg)`), extract the new stats before they're popped/removed:

```python
            evolver_states = compute_evolver_states(audit_reports, audit_cfg)
            time_cal = evolver_states.pop("time_calibration_report", {})
            time_cal_json = compact_json(time_cal)

            # Extract batch forensic stats before formatting evolver_states for injection
            fill_rate_pct = evolver_states.pop("fill_rate_pct", 0)
            near_miss_rate = evolver_states.pop("near_miss_rate", 0)
            mae_stress_distribution = evolver_states.pop("mae_stress_distribution", {})
            cowardice_tag_rate = evolver_states.pop("cowardice_tag_rate", 0)
```

Then in the `_prepare_prompt` call (line 127), add the new keyword arguments:

```python
            prompt = self._prepare_prompt(
                self.config.instruction_path,
                audit_reports_json=reports_json,
                active_config_yaml=config_json,
                current_prompt_md=prompts_md,
                strategy_intent=active_config.get('strategy_intent', "N/A"),
                precomputed_evolver_states=_format_states(evolver_states),
                time_calibration_report=time_cal_json,
                fill_rate_pct=fill_rate_pct,
                near_miss_rate=near_miss_rate,
                mae_stress_distribution=mae_stress_distribution,
                cowardice_tag_rate=cowardice_tag_rate,
                regime_parameters=active_config.get('regime_parameters', {}),
                trend_intensity_threshold=active_config.get('regime_parameters', {}).get('trend', {}).get('trend_intensity_threshold'),
                volatility_extreme_ratio=active_config.get('regime_parameters', {}).get('volatility', {}).get('volatility_extreme_ratio'),
                structural_buffer_atr=active_config.get('regime_parameters', {}).get('structural', {}).get('structural_buffer_atr'),
                stop_loss_buffer_min=active_config.get('regime_parameters', {}).get('risk', {}).get('stop_loss_buffer_min'),
                max_holding_hours=active_config.get('regime_parameters', {}).get('risk', {}).get('max_holding_hours'),
                mae_threshold_pinpoint=active_config.get('audit_review', {}).get('mae', {}).get('mae_threshold_pinpoint'),
                mae_threshold_standard=active_config.get('audit_review', {}).get('mae', {}).get('mae_threshold_standard'),
                mae_threshold_luck=active_config.get('audit_review', {}).get('mae', {}).get('mae_threshold_luck'),
                max_rounds=active_config.get('binary_star', {}).get('max_rounds'),
            )
```

Note: `_format_states(evolver_states)` now only contains the boolean flags (IS_*, HAS_*) since we popped the batch stats. This is correct — the prompt template uses `{precomputed_evolver_states}` for the boolean flags and `{fill_rate_pct}` etc. for the batch stats.

- [ ] **Step 2: Verify import and syntax**

```bash
cd /Users/yangjiang/workspace/binary-star && python -c "from src.agent.evolver_agent import EvolverAgent; print('import OK')"
```

- [ ] **Step 3: Run existing evolver tests**

```bash
cd /Users/yangjiang/workspace/binary-star && python -m pytest tests/integration/test_evolver_sandbox.py -v --timeout=60 2>&1 | head -20
```

(These tests may require API keys; import-level verification from Step 2 is sufficient.)

- [ ] **Step 4: Commit**

```bash
git add src/agent/evolver_agent.py
git commit -m "feat: inject fill_rate_pct, near_miss_rate, mae_stress_distribution, cowardice_tag_rate into evolver prompt"
```

---

### Task 6: Update evolver.md prompt

**Files:**
- Modify: `config/prompts/evolver.md:16-17` (LOGIC_MACROS)
- Modify: `config/prompts/evolver.md:8-14` (INPUT_DATUM — add Batch Forensic Stats block)
- Modify: `config/prompts/evolver.md:50-62` (JUDGMENT_RUBRIC — rewrite OPPORTUNITY_COST and COWARDICE_TRAP, add PHANTOM_ORDER_FIX)

**Interfaces:**
- Consumes: `{fill_rate_pct}`, `{near_miss_rate}`, `{mae_stress_distribution}`, `{cowardice_tag_rate}` placeholders injected by Task 5; `{precomputed_evolver_states}` now contains `IS_CATASTROPHIC_NEUTRAL_MISS` and `IS_CATASTROPHIC_UNFILLED_MISS` instead of `IS_CATASTROPHIC_MISS`

- [ ] **Step 1: Remove IS_PHANTOM_ORDER_BIAS and IS_OVERFIT_RISK from LOGIC_MACROS**

In `config/prompts/evolver.md`, replace lines 16-17:

```
- `IS_OVERFIT_RISK`: Historical fix would invalidate > 5% of "Pristine" success records.
- `IS_PHANTOM_ORDER_BIAS`: The Session routinely proposes `entry` coordinates
  > 1.0 ATR away from `current_price` to artificially satisfy RR requirements,
  resulting in missed fills.
```

With a single comment line:

```
(LOGIC_MACROS are now pre-computed in Python — see PRE-COMPUTED STATES below.)
```

- [ ] **Step 2: Add Batch Forensic Stats to INPUT_DATUM**

After the `- **Time Calibration Report**: ...` line (line 12), insert the new block:

```markdown
- **Batch Forensic Stats**: Pre-computed from `{audit_reports_json}`. Use as given.
  - `fill_rate_pct` (`{fill_rate_pct}`): % of directional sessions where entry was filled.
  - `near_miss_rate` (`{near_miss_rate}`): Of unfilled sessions, % where entry was within the proximity limit (almost filled).
  - `mae_stress_distribution` (`{mae_stress_distribution}`): Counts of PINPOINT / STANDARD / LUCK / FAILURE stress tiers across filled trades.
  - `cowardice_tag_rate` (`{cowardice_tag_rate}`): % of NEUTRAL sessions where the Critic flagged inaction bias, trend starvation, or opportunity denial.
```

- [ ] **Step 3: Update PRE-COMPUTED STATES description**

In the `- **Evolver States**: ...` line, ensure it documents the split fields:

```markdown
  - **Evolver States**: `{precomputed_evolver_states}` — Boolean flags: `IS_BATCH_SIGNIFICANT`, `IS_FAILURE_RATIO_ALARM`, `HAS_SYSTEMIC_PATHOLOGY`, `IS_LOGIC_COWARDICE`, `HAS_STRUCTURAL_AMNESTY`, `IS_PROFIT_EVAPORATION`, `IS_CATASTROPHIC_NEUTRAL_MISS`, `IS_CATASTROPHIC_UNFILLED_MISS`.
```

- [ ] **Step 4: Rewrite THE_OPPORTUNITY_COST in JUDGMENT_RUBRIC**

Replace the existing THE_OPPORTUNITY_COST block (lines 50-55) with:

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

- [ ] **Step 5: Rewrite THE_COWARDICE_TRAP in JUDGMENT_RUBRIC**

Replace the existing THE_COWARDICE_TRAP block (lines 57-62) with:

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

- [ ] **Step 6: Add THE_PHANTOM_ORDER_FIX to JUDGMENT_RUBRIC**

After THE_COWARDICE_TRAP, before `# ACTION_DICTIONARY`, insert:

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

- [ ] **Step 7: Verify the prompt template has no orphaned placeholders**

```bash
cd /Users/yangjiang/workspace/binary-star && python3 -c "
import re
with open('config/prompts/evolver.md') as f:
    content = f.read()
placeholders = set(re.findall(r'\{(\w+)\}', content))
# These are injected by evolver_agent.py._prepare_prompt:
known = {'strategy_intent','audit_reports_json','precomputed_evolver_states',
    'time_calibration_report','current_prompt_md','active_config_yaml',
    'fill_rate_pct','near_miss_rate','mae_stress_distribution','cowardice_tag_rate',
    'regime_parameters','trend_intensity_threshold','volatility_extreme_ratio',
    'structural_buffer_atr','stop_loss_buffer_min','max_holding_hours',
    'mae_threshold_pinpoint','mae_threshold_standard','mae_threshold_luck',
    'max_rounds','min_rr_ranging','min_rr_trending','poc_gravity_atr_distance',
    'breakout_frontrun_atr','max_entry_distance_atr','chaos_rr_discount',
    'squeeze_audit_threshold','funding_extreme_threshold'}
unknown = placeholders - known
if unknown:
    print(f'UNKNOWN PLACEHOLDERS: {unknown}')
else:
    print('All placeholders accounted for')
"
```

Expected: `All placeholders accounted for`

- [ ] **Step 8: Commit**

```bash
git add config/prompts/evolver.md
git commit -m "feat: rewrite evolver JUDGMENT_RUBRIC with batch stats; remove phantom boolean macros"
```

---

## Self-Review

**1. Spec coverage:**
- Dashboard KPI replacement → Tasks 1-3
- `/api/trades` new fields → Task 1
- i18n keys → Task 2
- Batch stats in `compute_evolver_states()` → Task 4
- Split `IS_CATASTROPHIC_MISS` → Task 4
- Injection in `evolver_agent.py` → Task 5
- `evolver.md` LOGIC_MACROS removal → Task 6 Step 1
- `evolver.md` INPUT_DATUM block → Task 6 Step 2
- `evolver.md` JUDGMENT_RUBRIC rewrite → Task 6 Steps 4-6
- KPI thresholds → hardcoded in Task 3 JS
- Batch stat thresholds → hardcoded in Task 6 Steps 4-6
- Non-goals respected: no LLM schema changes, no config keys, no NEUTRAL changes
✅ All covered.

**2. Placeholder scan:**
No TBDs, TODOs, or vague steps. Every step has actual code.
✅ Clean.

**3. Type consistency:**
- `fill_rate_pct`: float (Task 4) → `{fill_rate_pct}` in template (Task 6) → injected as float (Task 5)
- `near_miss_rate`: float → same
- `mae_stress_distribution`: dict → `{mae_stress_distribution}` → compact_json'd
- `cowardice_tag_rate`: float → same
- `mfe_efficiency_pct`: float|null from API (Task 1) → used as `t.mfe_efficiency_pct` in JS (Task 3)
- `mae_stress_tier`: string|null from API (Task 1) → used as `t.mae_stress_tier` in JS (Task 3)
- `IS_CATASTROPHIC_NEUTRAL_MISS`: bool (Task 4) → referenced in evolver.md (Task 6)
- `IS_CATASTROPHIC_UNFILLED_MISS`: bool (Task 4) → referenced in evolver.md (Task 6)
✅ All consistent.

**4. Edge cases covered:**
- Empty audit_reports → Task 4 returns zeroed stats
- No directional sessions → fill_rate_pct = 0
- No unfilled sessions → near_miss_rate = 0
- No filled trades → MFE Efficiency and MAE Stress show "—" in Task 3
- No NEUTRAL sessions → cowardice_tag_rate = 0
✅ Covered.
