# Signal Stack Redesign: 13 → 9 Signals

**Date:** 2026-07-07
**Status:** Approved — ready for implementation plan

## Problem Statement

The current 13-signal stack has three structural issues:

1. **Data-source concentration**: 4 signals (cvd_momentum, cvd_divergence,
   cvd_absorption, taker_imbalance) all derive from a single data point —
   `cvd_intensity_ratio`. This creates false diversity and correlated failures.

2. **Dead signals**: 3 positioning signals (retail_extreme, oi_divergence,
   oi_surge) fired 0 times across a 460-pulse / 4-hour window. In low-volatility
   crypto markets, these hardcoded thresholds almost never trip.

3. **Wrong abstraction for the problem**: Signals like poc_gravity and
   trend_pullback detect *normal* market behavior (mean reversion, trend
   continuation), not *anomalous* activity. The signal stack's job is to answer
   "is something unusual happening?", not "what direction will it go?".
   Direction and quality are the Binary Star's responsibility.

## Design Goal

**Signal stack = market anomaly detector.** Each signal should detect one
distinct type of unusual market activity. Signals should NOT predict direction
— they answer "is there a situation worth investigating?" The Binary Star
debate then decides direction, conviction, and execution.

Quality constraints:
- Quality over frequency (user explicitly chose this)
- It is acceptable to miss trades (false negatives); false triggers are also
  acceptable because the AI gate can reject them
- The real "miss" to avoid is missing a genuine market anomaly that the AI
  should have been given a chance to evaluate

## Architecture: 9 Signals in 5 Categories

```
FLOW (3):      cvd_momentum, cvd_divergence, cvd_absorption
SIZE (1):      large_trade          ← NEW
ENERGY (2):    volatility_surge, squeeze
STRUCTURAL (2): boundary_test, liquidation_hunt
POSITIONING (1): positioning_extreme  ← merged from 3
```

### Removed Signals

| Signal | Reason |
|--------|--------|
| taker_imbalance | Merged into cvd_momentum. Both read `cvd_intensity_ratio`; the only difference was the threshold and whether growth was required. The merged detector uses a single threshold with two firing paths: (a) CVD growing above the base threshold, or (b) CVD already at extreme levels. |
| poc_gravity | Price returning to POC is normal mean-reversion, not an anomaly. |
| trend_pullback | Fired 0 times in 14 hours of log data. Requires |trend| > 0.35 AND price near HVN — an exceedingly rare combination. When trend IS strong, cvd_momentum already captures the flow. |
| retail_extreme | Merged into positioning_extreme |
| oi_divergence | Merged into positioning_extreme |
| oi_surge | Merged into positioning_extreme |

### New Signals

#### large_trade (SIZE)

Data source: `micro_klines[].volume / micro_klines[].trades` — already available
in `KlineData.trades` (field 8 of Binance kline response). Zero additional API cost.

```
avg_trade_size = sum(volume[-N:]) / sum(trades[-N:])
z_score = (avg_trade_size - rolling_mean) / rolling_std

Trigger: z_score > 2.0 (configurable per symbol)
Direction: from CVD sign (cvd > 0 → BULLISH, cvd < 0 → BEARISH)
Strength: clamp(z_score / 4.0, 0, 1)
Confidence: 0.55
```

Rolling window: 30 candles (~30 minutes for 1m klines), updated each pulse.
The rolling mean and standard deviation are computed over the `avg_trade_size`
values from the last 30 *pulses* (not candles within a single pulse). Each
pulse records its `avg_trade_size` into a deque; the Z-score is computed
against that deque's statistics.

#### positioning_extreme (POSITIONING)

Unifies three previously-separate detectors into one signal with three
independent trigger paths (any one suffices):

1. **LS extreme**: `ls_ratio > 1.5` → BEARISH (retail long-crowded) or
   `ls_ratio < 0.6` → BULLISH (retail short-crowded). Strength: normalized
   distance from neutral (1.0).

2. **OI divergence**: OI and price move in opposite directions
   (|oi_delta| > 0.01 required). Strength: min(|oi_delta| / 0.03, 1.0).

3. **OI surge**: OI and price move in the same direction
   (|oi_delta| > 0.02 required). Strength: min((|oi_delta| - 0.02) / 0.04, 1.0).

Confidence: 0.50 (LS ratio is a known lagging/contrarian indicator; OI data is
Binance-specific and may not reflect global positioning).

State lock: 8 hours (same as current retail_extreme, preventing repeated
triggers from the same positioning extreme).

**Conflict resolution**: If multiple sub-conditions fire in the same pulse,
the one with the highest strength wins (its direction and evidence are used).

### Adjusted Signals

#### cvd_momentum (FLOW)

Now absorbs taker_imbalance's role:
- **Path A (growth)**: |cvd| > base threshold AND |cvd| >= |prev_cvd| × 1.4
  → strength = min(|cvd| / (threshold × 3), 1.0)
- **Path B (extreme static)**: |cvd| > extreme_threshold. The extreme_threshold
  is the per-symbol `taker_imbalance` threshold from symbol_config.yaml
  (0.18 BTC / 0.36 XAUT), which will be renamed to `cvd_extreme_threshold`.
  → strength = min((|cvd| - extreme_threshold) / extreme_threshold, 1.0)

Confidence: 0.65 (unchanged).

#### cvd_absorption (FLOW)

Confidence reduced: 0.65 → 0.50. Without order book depth data, absorption
detection from CVD alone is unreliable — we can see "CVD is extreme but price
is flat" but cannot confirm there's actually an iceberg wall absorbing the flow.

### Unchanged Signals

cvd_divergence, volatility_surge, squeeze, boundary_test, liquidation_hunt —
logic, thresholds, and confidence values unchanged.

## Configuration Changes

### global_config.yaml — signal_stack section

```yaml
signal_stack:
  trigger_threshold: 0.34
  emergency_threshold: 0.80

  weights:
    cvd_momentum: 0.65
    cvd_divergence: 0.70
    cvd_absorption: 0.50     # was 0.65
    large_trade: 0.55        # NEW
    volatility_surge: 0.55
    squeeze: 0.75
    boundary_test: 0.50
    liquidation_hunt: 0.60
    positioning_extreme: 0.50  # NEW, replaces retail_extreme/oi_divergence/oi_surge
    leader_sync: 0.40
    # REMOVED: taker_imbalance, poc_gravity, trend_pullback,
    #          retail_extreme, oi_divergence, oi_surge

  thresholds:
    cvd_divergence_tick_delta: 0.25
    large_trade_zscore: 2.0     # NEW
    large_trade_lookback: 30    # NEW, candles
    # REMOVED: taker_imbalance
```

### symbol_config.yaml — per-symbol overrides

Default thresholds in `strategy_config.yaml` → `micro_sentiment` serve as the
base. Per-symbol overrides for XAUTUSDT already exist for CVD thresholds.
Add large_trade and positioning_extreme thresholds as needed after observing
baseline behavior.

## Code Changes

### Files to Modify

| File | Changes |
|------|---------|
| `src/sniper/trigger.py` | Delete 4 detectors, add 2, merge 3→1. Update `_signal_detectors` registry, `_suggest_thesis`, `_format_evidence`, `_build_risk_caveats`, `_build_entry_suggestion`, `_run_pre_ai_gate` (chaos survival check). Remove taker_imbalance/poc_gravity/trend_pullback/retail_extreme/oi_divergence/oi_surge references. |
| `src/analyzer/market_observer.py` | `_derive_sentiment`: add `avg_trade_size` and `trade_count` to the returned sentiment dict. |
| `config/global_config.yaml` | Update `signal_stack.weights`, add `large_trade_*` thresholds, remove old signal weights. |
| `config/symbol_config.yaml` | Remove `taker_imbalance` override from XAUTUSDT. |

### Files NOT Modified

- `config/strategy_config.yaml` — regime_parameters untouched (user constraint)
- `run_sniper.py` — TriggerResult interface unchanged, daemon consumes same API
- `run_session.py` — situation_brief interface unchanged
- `src/agent/order_executor.py` — order management untouched (user constraint)
- `src/sniper/scout.py` — already passes all micro_klines through metrics

## Backward Compatibility

- `TriggerResult` dataclass unchanged
- `SignalCard` dataclass unchanged
- `situation_brief` structure unchanged (activated_by still uses sub_type.UPPER())
- Session JSONs will contain new signal names (`LARGE_TRADE`, `POSITIONING_EXTREME`) and no longer contain removed ones (`TAKER_IMBALANCE`, `POC_GRAVITY`, `TREND_PULLBACK`, `RETAIL_EXTREME`, `OI_DIVERGENCE`, `OI_SURGE`)
- `session_html_renderer.py` has no dependency on specific signal names (confirmed via code search)

## Success Criteria

1. All 9 signal detectors execute per pulse without errors
2. New `large_trade` signal fires when avg trade size deviates significantly
3. New `positioning_extreme` fires at least occasionally (more than the current 0/460 rate)
4. CVD signals no longer dominate the active-signal list — SIZE/ENERGY/STRUCTURAL signals contribute at comparable rates
5. `situation_brief.activated_by` correctly reflects the 9-signal vocabulary
6. Existing unit tests pass (or are updated for the new signal names)
