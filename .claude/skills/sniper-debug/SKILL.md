---
name: sniper-debug
description: >
  Trace why the Sniper did or did not trigger at a specific time window.
  Use when the user asks: "why did sniper trigger here?", "why didn't it trigger?",
  "debug this signal", "what happened at 2pm yesterday?", "trace the confluence",
  "check the cooldown state", "why was this session fired?", "analyze the trigger log".
  Also use when the user mentions a specific session file and wants to understand
  what caused it, or when they report unexpected sniper behavior (missed entries,
  false triggers, suspicious signal patterns).
---

# Sniper Debug — Signal Trace & Trigger Forensics

Trace through the Sniper's decision pipeline at a specific point in time: which
signals activated, what the confluence engine computed, whether cooldown or the
pre-AI gate blocked it, and why the final trigger decision was made.

## Input Modes

The skill supports three ways to specify what to debug. Ask the user which they
prefer if it's ambiguous.

| Mode | Input | Use case |
|------|-------|----------|
| **Time window** | Symbol + datetime (or "around 14:30 yesterday") | "Why didn't it trigger at 2pm?" |
| **Session file** | Path to a session JSON | "Debug why this session fired" |
| **Signal focus** | Signal name + time window | "Why is cvd_divergence never firing?" |

If the user gives a session file path, extract the timestamp from
`observation.observed_at` and the symbol from `observation.symbol` — then debug
the time window around that session.

## Step 1: Read the Sniper Log

The primary data source is `data/prod/sniper.log`. Each pulse (~2 min) writes a
`SIGNAL DIAG` line. When the confluence engine fires, a `WAKE` line appears.

### SIGNAL DIAG line format

```
HH:MM:SS.sss INF [trigger] [SYMBOL] SIGNAL DIAG |
  cvd=<float> | cvd_momentum=<F:strength|R:reason> |
  cvd_divergence=<F:strength|R:reason> |
  cvd_absorption=<F:strength|R:reason> |
  taker_imb=<F:strength|R:reason> |
  vii=<float>,vpr=<float> | vol_surge=<F:strength|R:reason> |
  squeeze=<F:strength|R:reason> |
  price=<float>,atr=<float> |
  boundary_test=<F:strength|R:reason> |
  poc_gravity=<F:strength|R:reason> |
  liq_hunt=<F:strength|R:reason> |
  trend_pullback=<F:strength|R:reason> |
  ls=<float>,fund=<float> | retail_ext=<F:strength|R:reason> |
  oi_div=<F:strength|R:reason> |
  oi_surge=<F:strength|R:reason>
```

Each detector shows either `F:0.XX` (fired, with raw strength 0–1) or
`R:<reason>` (rejected, with the threshold comparison that failed).

### WAKE line format

```
HH:MM:SS.sss INF [trigger] [SYMBOL] WAKE |
  dir=<BULLISH|BEARISH> | confluence=<0.XX> | signals=<N> |
  active=['signal_name',...] | gate=<PASS|FAIL> | regime=<regime_name>
```

### Locating relevant lines

Use `grep` to find the SIGNAL DIAG and WAKE lines for the target symbol and
time window. Example for a 30-minute window around 14:30:

```bash
grep '\[trigger\].*\[BTCUSDT\]' data/prod/sniper.log | grep -E 'SIGNAL DIAG|WAKE'
```

For large log files, narrow with `sed -n '/<start_pattern>/,/<end_pattern>/p'`.

If the sniper log doesn't go back far enough, tell the user and fall back to
analyzing the session JSON's `observation.situation_brief` (which captures the
trigger state at session time, but not the pulse-by-pulse history).

## Step 2: Parse and Structure the Data

For each SIGNAL DIAG line in the target window, extract a structured record.
Use inline Python to parse reliably:

```python
import re
from datetime import datetime

# Parse one SIGNAL DIAG line
def parse_diag_line(line, date_str):
    # Extract timestamp
    ts_match = re.match(r'(\d{2}:\d{2}:\d{2}\.\d+)', line)
    ts = datetime.strptime(f"{date_str} {ts_match.group(1)}", "%Y-%m-%d %H:%M:%S.%f")

    # Parse each detector: F:0.XX = fired, R:... = rejected
    detectors = {}
    # Pattern: detector_name=F:0.XX or detector_name=R:reason-text
    for m in re.finditer(r'(\w+)=(F:[0-9.]+|R:[^|]+)', line):
        name = m.group(1)
        value = m.group(2)
        if value.startswith('F:'):
            detectors[name] = {'status': 'FIRED', 'strength': float(value[2:])}
        else:
            detectors[name] = {'status': 'REJECTED', 'reason': value[2:].strip()}

    # Parse contextual metrics
    cvd_match = re.search(r'cvd=(-?[\d.]+)', line)
    vii_match = re.search(r'vii=(-?[\d.]+)', line)
    vpr_match = re.search(r'vpr=(-?[\d.]+)', line)
    sf_match = re.search(r'sf=(-?[\d.]+)', line)
    price_match = re.search(r'price=(-?[\d.]+)', line)
    atr_match = re.search(r'atr=(-?[\d.]+)', line)
    ls_match = re.search(r'ls=(-?[\d.]+)', line)
    fund_match = re.search(r'fund=(-?[\d.]+)', line)
    trend_match = re.search(r'\|trend\|=(-?[\d.]+)', line)

    return {
        'timestamp': ts,
        'metrics': {
            'cvd': float(cvd_match.group(1)) if cvd_match else None,
            'vii': float(vii_match.group(1)) if vii_match else None,
            'vpr': float(vpr_match.group(1)) if vpr_match else None,
            'squeeze_factor': float(sf_match.group(1)) if sf_match else None,
            'price': float(price_match.group(1)) if price_match else None,
            'atr': float(atr_match.group(1)) if atr_match else None,
            'ls_ratio': float(ls_match.group(1)) if ls_match else None,
            'funding': float(fund_match.group(1)) if fund_match else None,
            'trend_intensity': float(trend_match.group(1)) if trend_match else None,
        },
        'detectors': detectors,
    }
```

## Step 3: Determine Regime and Thresholds

From the metrics in each pulse, classify the regime using the same logic as
`SniperTrigger._determine_regime()` (see `src/sniper/trigger.py` starts at line 298):

```python
def classify_regime(vii, squeeze_factor, trend_intensity):
    if vii is None or squeeze_factor is None or trend_intensity is None:
        return 'unknown'
    if vii > 2.2:
        return 'chaos'
    if squeeze_factor < 1.0:    # squeeze_threshold from strategy_config
        return 'squeeze'
    if abs(trend_intensity) > 0.35:
        return 'trending'
    return 'ranging'
```

⚠️ These thresholds come from `config/strategy_config.yaml` — verify against current config values before debugging.

Regime modifiers (from `config/global_config.yaml` → `signal_stack.regime_modifiers`):
- trending: ×0.85 → effective threshold 0.289
- ranging: ×1.00 → effective threshold 0.340
- squeeze: ×0.75 → effective threshold 0.255
- chaos: ×1.50 → effective threshold 0.510

Base threshold: 0.34 (from `signal_stack.trigger_threshold`).

## Step 4: Reconstruct the Confluence Score

For each pulse, compute what the confluence engine would have produced.

### Directional stacking formula

For each direction (BULLISH / BEARISH):

```
directional_score = 1 − ∏(1 − s.strength × s.confidence)
    for all signals s with that direction AND strength ≥ 0.15
```

Signal confidence values (from `config/global_config.yaml` → `signal_stack.weights`):

| Signal | Confidence |
|--------|-----------|
| cvd_momentum | 0.65 |
| cvd_divergence | 0.70 |
| cvd_absorption | 0.65 |
| taker_imb | 0.60 |
| volatility_surge | 0.55 |
| squeeze | 0.75 |
| boundary_test | 0.50 |
| poc_gravity | 0.55 |
| liquidation_hunt | 0.60 |
| trend_pullback | 0.75 |
| retail_extreme | 0.42 |
| oi_divergence | 0.70 |
| oi_surge | 0.55 |

### Noise cancellation

```
noise_factor = 1.0 − (bullish_score × bearish_score)
raw_confluence = max(bullish_score, bearish_score)
final_confluence = raw_confluence × noise_factor
```

### Emergency override

Any single signal with raw `strength ≥ 0.80` bypasses cooldown and threshold
entirely. Check for this explicitly in the output.

## Step 5: Check Cooldown State

Cooldown is determined by regime and time since last trigger:

| Regime | Cooldown (minutes) |
|--------|-------------------|
| trending | 25 |
| ranging | 45 |
| squeeze | 25 |
| chaos | 60 |

_Note: config applies `base_multiplier: 2.5` — effective values are trending 62.5 min, ranging 112.5 min, squeeze 62.5 min, chaos 150 min._

Absolute minimum gap between triggers: 10 minutes (any regime).

Cooldown break conditions (either one suffices):
1. **Stacked break**: 3+ fresh signals in the same direction (strength ≥ 0.15)
2. **Strength ratio break**: any fresh signal's `weighted_score ≥ last_trigger_score × 1.8`

To check cooldown state, find the most recent WAKE line before the target window.
If none exists in the log, cooldown is inactive.

**Cooldown can also be reset mid-lifecycle** when the Guardian clears a trade state
(entry expired or position closed via TP/SL). This sets `last_trigger_time = None`,
completely releasing the cooldown. Emergency close paths do NOT trigger this reset.
Check the sniper log for `cooldown reset (trade cleared)` lines near the target window.

## Step 6: Check Pre-AI Gate

If confluence exceeded the effective threshold and cooldown didn't block it,
the pre-AI gate applies these checks (from `src/sniper/trigger.py` starts at line 395):

1. **Entry Feasibility**: is there a structural anchor (HVN/LVN) within
   `max_price_to_structure_atr` (4.0 ATR) of current price? If not → FAIL.
   Requires `observation.quantitative_metrics.volume_profile.anchors_above/below`
   from a session JSON or chart data.

2. **Directional Sanity**: if the signal direction contradicts trend
   (`|trend| > 0.35`) AND CVD is weak (`|cvd| < 0.1`) → FAIL (no counter-trend
   without flow confirmation).

3. **Chaos Survival** (chaos regime only): if the only active signals are
   directional momentum (`cvd_momentum`, `volatility_surge`) without squeeze
   or absorption as balance → FAIL.

Note: gate check #4 (RR feasibility) is in config but not implemented in code.

## Step 7: Cross-Reference with Session JSON

If a session exists for the trigger event, load the session JSON and extract:

- `observation.situation_brief` — contains `activated_by[]` (which signals the
  sniper itself identified as the trigger cause), `confluence_score`,
  `confluence_direction`, `gate_result`, `regime_note`.
- `observation.quantitative_metrics.market_regime` — squeeze_factor,
  trend_intensity, volume_participation_ratio, temporal_physics.
- `final_decision.opinion` and `final_decision.confidence_score` — did the AI
  agree with the trigger?

Compare the session's `situation_brief.activated_by` with your reconstructed
signal analysis — discrepancies between what the sniper recorded and what the
log shows are themselves useful findings.

## Output Format

Always produce this structured report:

```markdown
# Sniper Trace: {SYMBOL} @ {TIME_WINDOW}

## 1. Regime & Threshold
| Pulse Time | VII | Squeeze | Trend | Regime | Modifier | Eff. Threshold |
|------------|-----|---------|-------|--------|----------|---------------|
| ... | ... | ... | ... | ... | ... | ... |

## 2. Signal Activation (per pulse)
| Pulse Time | Signal | Status | Strength | Confidence | Weighted | Direction |
|------------|--------|--------|----------|------------|----------|-----------|
| ... | cvd_momentum | FIRED:0.45 | 0.45 | 0.65 | 0.29 | BEARISH |
| ... | cvd_divergence | REJECTED | — | — | — | — |
| ... (all 13) | ... | ... | ... | ... | ... | ... |

## 3. Confluence Engine
| Pulse Time | Bullish Score | Bearish Score | Raw | Noise Factor | Final | Eff. Threshold | Pass? |
|------------|--------------|--------------|-----|-------------|-------|---------------|-------|

## 4. Cooldown & Gate
- Last trigger: {timestamp or "none in log"}
- Cooldown status: {active/inactive} ({N} min remaining)
- Cooldown break: {none / stacked(3 signals) / strength_ratio(2.1×)}
- Emergency override: {none / signal_name: strength 0.XX}
- Gate result: {PASS / FAIL: reason}

## 5. Root Cause
[One paragraph explaining WHY the trigger did or didn't fire at this moment.
Name the dominant factor: signal weakness, cooldown block, gate rejection,
regime suppression, or noise cancellation.]

## 6. Session Correlation (if applicable)
- Session file: {path}
- Sniper recorded: {activated_by signals}
- AI opinion: {BULLISH/BEARISH/NEUTRAL} @ confidence {N}%
- Agreement with trigger: {consistent / discrepancy: explain}
```

## Edge Cases

- **Log doesn't go back far enough**: tell the user the earliest available
  timestamp in the log, fall back to session JSON analysis only.
- **No SIGNAL DIAG lines for that symbol**: check if the symbol name format
  matches (e.g. `BTCUSDT` not `BTC`), try both.
- **Multiple WAKE lines close together**: leader sync may have boosted a
  follower — check for cross-symbol correlation.
- **Confluence says trigger but WAKE line absent**: the pre-AI gate likely
  rejected it. Check gate conditions carefully.
- **Signal locked out by state lock**: structural signals (boundary_test,
  poc_gravity, liquidation_hunt) and retail_extreme each lock for 8 hours
  after firing. If a signal fired recently but isn't showing up, check the
  lockout period.

## Reference Files

- `src/sniper/trigger.py` — signal detectors, ConfluenceEngine, gate logic,
  cooldown system, regime classification (the source of truth for all logic).
- `src/sniper/scout.py` — how market metrics are harvested before trigger evaluation.
- `config/global_config.yaml` → `sniper.signal_stack` — thresholds, weights,
  cooldown minutes, regime modifiers, gate flags.
- `config/strategy_config.yaml` → `regime_parameters` — VII/squeeze/trend
  thresholds, CVD intensity thresholds, volume participation thresholds.
- `data/prod/sniper.log` — runtime SIGNAL DIAG and WAKE lines.
- `data/prod/sessions/{SYMBOL}_session_*.json` — session archives with
  situation_brief for cross-reference.
