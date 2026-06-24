# Singularity Trigger Strategy Redesign

**Date**: 2026-06-25
**Status**: Design Proposal (pre-implementation)
**Scope**: Phase 1 Trigger Architecture — signal evaluation, confluence scoring, adaptive gating, AI context injection

---

## 1. Problem Diagnosis

### 1.1 What the production log reveals

Analysis of `data/prod/sniper.log` (~2 hours, 2 symbols: BTCUSDT + XAUTUSDT):

| Metric | Observation |
|--------|-------------|
| Total triggers | 14 (all `FLOW_ASYMMETRY`) |
| `ENERGY_BUILDUP` triggers | **0** — threshold too strict or condition rare at 2-min pulse |
| `STRUCTURAL_APPROACH` triggers | **0** — same |
| Retail sentiment triggers | Dominant (LS ratio extremes), but low strength (3–5/10) |
| CVD momentum triggers | Stronger (6–10/10) but less frequent |
| Cooldown hits | **0** (daemon restarts prevented cooldown from activating) |
| AI sessions per trigger | 1 expensive full-debate session EVERY trigger |
| NEUTRAL outcomes | ~30% of sessions — wasted AI cost |
| Token cost per session | ~80K–120K input tokens (DeepSeek, ~$0.11–$0.17/session) |

### 1.2 Root causes

1. **Binary trigger loses information.** A strength-3 retail sentiment extreme and a strength-10 CVD momentum impulse both fire the same expensive AI debate. There's no quality gating.

2. **No signal confluence detection.** The system picks the single strongest signal and ignores that two moderate signals reinforcing each other (e.g., CVD bearish + retail long extreme) are far more predictive than one strong signal alone.

3. **Trigger → AI context is a fire-and-forget.** The SessionAgent receives raw observation data and has to rediscover the opportunity from scratch. It doesn't know WHAT triggered the session or WHY.

4. **Cooldown is purely time-based, not condition-based.** 37.5 minutes of silence regardless of whether the market has fundamentally changed. A great setup can be missed because a mediocre trigger consumed the cooldown window.

5. **Signal decay is not modeled.** Conditions that triggered 35 minutes ago may still be valid (or may have intensified), but the binary cooldown treats them as "done."

6. **No pre-AI deterministic filtering.** Some triggers are physically impossible to trade (e.g., no room for valid RR, entry would exceed `max_entry_distance_atr`). These still fire expensive AI sessions.

7. **Missing signal dimensions.** No order-book imbalance, no OI-price divergence detection, no multi-timeframe alignment scoring, no volume-delta analysis.

---

## 2. Design Philosophy: From "Trigger" to "Signal Stack"

The current model is a **single-event trigger** — one condition fires, one AI session runs. 

The new model is a **Signal Stack** — multiple signals accumulate, cross-validate, and only fire when confluence reaches a dynamic threshold. The trigger is no longer a boolean; it's a **continuous confidence score** that rises and falls with market evidence.

### Core principles

| Principle | Old Model | New Model |
|-----------|-----------|-----------|
| Signal representation | Binary (hit / no-hit) | Continuous score (0–1) with direction, decay, confidence |
| Multi-signal handling | Pick strongest, discard rest | Stack signals, detect confluence, cancel contradictory signals |
| AI handoff | Raw observation only | Pre-brief with trigger type, direction, key levels, risk caveats |
| Cooldown | Fixed 37.5 min | Adaptive: regime-sensitive, breakable on material condition change |
| Quality gating | None (all triggers equal) | Pre-AI commonsense gate + dynamic confidence threshold |
| Signal memory | None (amnesia between triggers) | Persistent signal cards with temporal decay |
| Feedback | Manual audit review | Audit data feeds back into per-signal-type weight adjustment |

---

## 3. Architecture: The Signal Stack

### 3.1 Signal Card

Every detected condition produces a **Signal Card** — a structured, scored, directional assessment:

```
SignalCard:
  signal_id: str                    # unique per pulse (e.g., "CVD_MOMENTUM_20260625_120000")
  type: SignalType                  # ENERGY | FLOW | STRUCTURAL | SENTIMENT | INTER_MARKET
  sub_type: str                     # e.g., "cvd_divergence", "squeeze_intensifying"
  direction: Direction              # BULLISH | BEARISH | NEUTRAL
  strength: float                   # 0.0–1.0 continuous score
  confidence: float                 # 0.0–1.0 how reliable this signal type is
  urgency: float                    # 0.0–1.0 time-sensitivity (squeeze=high, POC magnet=low)
  timestamp: datetime               # when detected
  decay_half_life_minutes: float    # how fast signal relevance fades
  evidence: dict                    # structured data for context injection
  regime_compatibility: float       # 0.0–1.0 how well signal matches current regime
```

### 3.2 Available Data Inventory

Every signal must be computable from data the scout already collects. Here is the complete field inventory at trigger evaluation time:

**From `distilled_metrics` (per pulse):**
| Source | Fields |
|--------|--------|
| `price_dynamics` | `current_price`, `atr_macro`, `atr_micro`, `volatility_intensity_index`, `volatility_expansion_index`, `wick_skew_instant`, `normalized_velocity` |
| `market_regime` | `volume_participation_ratio`, `squeeze_factor`, `trend_intensity` (signed -1..1) |
| `volume_profile` | `poc`, `vah`, `val`, `nearest_hvn_dist_atr`, `nearest_lvn_dist_atr`, `volume_span_atr`, `anchors_above[]`, `anchors_below[]` |
| `structural_anchors` | `poc_dist_atr` (signed), `vah_dist_atr` (signed), `val_dist_atr` (signed) |
| `sentiment_signals` | `cvd_intensity_ratio` (-1..1), `cvd_volume_delta`, `cvd_total_volume`, `ls_ratio_macro`, `ls_ratio_micro`, `oi_nominal`, `oi_delta_macro`, `oi_delta_micro`, `funding_rate`, `funding_rate_delta`, `liquidation_clusters` |

**From `raw.micro_klines[]` (per candle, 192 candles):** `open`, `high`, `low`, `close`, `volume`, `taker_buy_base`

**From `prev_metrics` (previous pulse):** Same structure as `distilled_metrics`, enabling inter-pulse delta calculations.

### 3.3 Signal Taxonomy (redesigned from available data)

14 signals in 5 categories. Every signal maps to a specific, computable field from the data inventory above.

#### FLOW — Order Flow Imbalance (4 signals)

| # | Signal | Computed From | Direction | Detection Logic |
|---|--------|---------------|-----------|-----------------|
| 1 | **CVD Momentum** | `cvd_intensity_ratio` | Sign of CVD | `abs(cvd) > cvd_intensity_threshold (0.10)` AND growing pulse-over-pulse |
| 2 | **CVD Divergence** | CVD delta vs price delta (prev pulse required) | Opposite to price | `sign(price_delta) != sign(cvd_delta)` AND `abs(cvd_delta) > tick_delta` |
| 3 | **CVD Absorption** | `cvd_intensity_ratio` + price delta | Opposite to CVD | `abs(cvd) > extreme (0.25)` AND `abs(price_delta) < 0.3 × atr_micro` |
| 4 | **Taker Imbalance** | `taker_buy_base` / volume per micro candle | Sign of ratio | `taker_buy / total_vol > 0.60` → BULLISH, `< 0.40` → BEARISH, over last 4 micro candles |

**Note:** Signal #4 requires passing `taker_buy_base` from `raw.micro_klines` into the distilled metrics (one additional field in `sentiment_signals`).

#### ENERGY — Volatility Dynamics (2 signals)

| # | Signal | Computed From | Direction | Detection Logic |
|---|--------|---------------|-----------|-----------------|
| 5 | **Volatility Surge** | `volatility_intensity_index` + `volume_participation_ratio` | From CVD sign | VII > `volatility_baseline_ratio (1.25)` AND VPR > `volume_participation_threshold (1.5)` AND VII accelerating pulse-over-pulse |
| 6 | **Squeeze** | `squeeze_factor` | NEUTRAL | `squeeze_factor < squeeze_threshold × squeeze_trigger_multiplier (0.75)` AND tightening pulse-over-pulse |

#### STRUCTURAL — Price vs. Key Levels (4 signals)

| # | Signal | Computed From | Direction | Detection Logic |
|---|--------|---------------|-----------|-----------------|
| 7 | **Boundary Test** | `vah`/`val` distance + volume + direction | Toward boundary | `dist_to_boundary < proximity_vah_val_atr (0.70)` AND `volume_participation > 1.0` AND price moving toward boundary |
| 8 | **POC Gravity** | `poc_dist_atr` + direction | Toward POC | `abs(poc_dist) > 0.50 ATR` AND price moving toward POC |
| 9 | **Liquidation Hunt** | `liquidation_clusters` + direction | Toward nearest cluster | Price within `proximity_liq_atr (0.40)` of cluster AND moving toward it |
| 10 | **Trend Pullback** | `trend_intensity` + `nearest_hvn_dist_atr` | Trend direction | `IS_TREND_STRONG` AND price within `1.0 ATR` of HVN/POC in the trend's direction. **Highest-quality signal — currently not detected at all.** |

#### POSITIONING — Sentiment & Open Interest (3 signals)

| # | Signal | Computed From | Direction | Detection Logic |
|---|--------|---------------|-----------|-----------------|
| 11 | **Retail Extreme** | `ls_ratio_micro` OR `funding_rate` | CONTRARIAN | LS > `long_short_imbalance_ratio (1.5)` → BEARISH. LS < `short_heavy_imbalance_ratio (0.6)` → BULLISH. OR `abs(funding) > funding_extreme_threshold (0.0005)` → opposite direction. |
| 12 | **OI Divergence** | `oi_delta_micro` sign vs price delta sign | Opposite to price | `sign(oi_delta) != sign(price_delta)`. Price↑ OI↓ = short squeeze exhaustion (BEARISH). Price↓ OI↑ = accumulation (BULLISH). |
| 13 | **OI Surge** | `oi_delta_micro` + price delta | Price direction | `abs(oi_delta) > 0.02` AND price moving same direction as OI change. Fresh capital entering → trend continuation fuel. |

**Note:** Signal #11 merges the old separate `_check_retail_sentiment` and `_check_funding_extreme` into one signal — they share identical contrarian logic.

#### CROSS-SYMBOL — Inter-Market Dynamics (1 signal)

| # | Signal | Computed From | Direction | Detection Logic |
|---|--------|---------------|-----------|-----------------|
| 14 | **Leader Sync** | Another symbol's confluence score + correlation | Inherited | When symbol A triggers, symbol B with a weak directional stack gets a boost: `boost = leader_score × correlation × 0.30`. Capped at 0.15. |

**Cross-symbol mechanism:**
```
For each pair (leader, follower) tracked simultaneously:
  if leader.confluence_score > leader.trigger_threshold:
    boost = min(leader.confluence_score × corr_coef × 0.30, 0.15)
    follower.effective_score += boost
```
The correlation coefficient is computed from a rolling 24h window of 15m returns. Default pair correlations: BTC→XAUT ≈ 0.40, BTC→ETH ≈ 0.75. The boost can tip a borderline signal over threshold but cannot create a trigger from zero — it only amplifies existing directional alignment.

### 3.3 Continuous Scoring

Each signal produces a `strength` (0.0–1.0) instead of a discrete 1–10 integer. The scoring function is:

```
strength = clamp(signal_value / saturation_threshold, 0.0, 1.0) × regime_weight
```

Where:
- `signal_value`: the raw metric (e.g., `abs(cvd_delta)`)
- `saturation_threshold`: the value at which the signal is "fully saturated" (3× the minimum trigger threshold)
- `regime_weight`: multiplier based on regime compatibility (0.5–1.5)
  - Trending regime: trend-following signals get 1.2×, counter-trend get 0.7×
  - Ranging regime: mean-reversion signals get 1.2×, momentum signals get 0.8×
  - Chaos regime: all signals get 0.6× (higher bar to trigger)

### 3.4 Confidence per Signal Type

Each signal type has a **dynamic confidence weight** initialized from prior knowledge and updated from audit feedback:

| Signal Type | Base Confidence | Rationale |
|-------------|----------------|-----------|
| CVD Divergence | 0.70 | Price-CVD divergence is a well-documented leading indicator |
| CVD Momentum | 0.65 | Strong but can be late (already in motion) |
| Squeeze Intensifying | 0.75 | Bollinger-Keltner squeezes have high breakout reliability |
| Liquidation Magnet | 0.60 | Liquidity hunting is real but timing is uncertain |
| Retail L/S Extreme | 0.45 | Contrarian but often early — sentiment can stay extreme for hours |
| Funding Extreme | 0.40 | Similar to L/S — mean-reversion timing is difficult |
| POC Magnet | 0.55 | Mean reversion is reliable in ranging, dangerous in trending |
| VAH/VAL Approach | 0.50 | Boundary tests are common; breakout vs rejection is the question |
| OI-Price Divergence | 0.70 | Strong structural signal — diverging OI reveals smart money positioning |
| Volume Delta Imbalance | 0.60 | Direct order flow measurement, but noisy on single pulses |

These weights **self-adjust** via evolution feedback (Section 7).

---

## 4. Confluence Engine

### 4.1 Signal Stacking

Signals in the same direction **amplify** each other. The relationship is **sub-linear** (diminishing returns) to prevent score inflation:

```
directional_score(direction) = 1 - ∏(1 - sᵢ × cᵢ)
```

Where `sᵢ` is the strength and `cᵢ` is the confidence of each signal aligned with that direction.

Example: Two moderate signals (strength 0.5, confidence 0.6 each):
- Individual: 0.5 × 0.6 = 0.30
- Stacked: 1 - (1 - 0.30)(1 - 0.30) = 1 - 0.49 = 0.51

### 4.2 Signal Cancellation

Contradictory signals (one BULLISH, one BEARISH) create a **noise penalty**:

```
noise_factor = 1.0 - (bullish_score × bearish_score)
confluence_score = max(bullish_score, bearish_score) × noise_factor
```

If both directions have strong signals, noise is high and the confluence score is suppressed — the market is conflicted, don't trade.

### 4.3 Signal Persistence & Decay

Signals don't disappear after one pulse. They **decay** with a half-life:

```
decayed_strength = strength × 0.5^(elapsed / half_life)
```

| Signal Category | Half-Life | Rationale |
|-----------------|-----------|-----------|
| FLOW (tick-scale: divergence, impulse) | 4 min | Micro-structure, fast decay |
| FLOW (macro: momentum, absorption) | 15 min | Slower-building, more persistent |
| ENERGY (squeeze, expansion) | 20 min | Structural condition, changes slowly |
| SENTIMENT (LS ratio, funding) | 60 min | Sentiment extremes persist |
| STRUCTURAL (boundaries, POC) | 10 min | Price moves, structure relevance shifts |

### 4.4 Trigger Decision

A Binary Star session fires when:

```
confluence_score ≥ trigger_threshold × regime_modifier
```

Where:
- `trigger_threshold`: base threshold (e.g., 0.35)
- `regime_modifier`:
  - Trending: 0.85 (easier to trigger — follow the trend)
  - Ranging: 1.15 (harder — wait for clearer setup)
  - Squeeze: 0.70 (easier — squeeze breakouts are high-value)
  - Chaos: 1.50 (much harder — protect capital)

**Additional override**: Fire IMMEDIATELY if any single signal exceeds `emergency_threshold` (e.g., 0.85), regardless of confluence. This preserves the ability to catch sudden, high-quality moves.

---

## 5. Adaptive Cooldown

### 5.1 Regime-Adaptive Base Cooldown

| Regime | Cooldown | Rationale |
|--------|----------|-----------|
| Trending | 25 min | Trend moves are sequential — shorter cooldown captures continuation |
| Ranging | 45 min | Range setups develop slowly — longer silence prevents whipsaw |
| Squeeze | 20 min | Breakouts are time-sensitive — shorter cooldown |
| Chaos | 60 min | Protect capital — long silence during extreme volatility |
| Default | 37.5 min | Current value, preserved as fallback |

### 5.2 Condition-Change Break

During cooldown, the system **tracks** signals (doesn't fire AI, but records them). If a **material condition change** is detected, cooldown breaks early:

**Material changes:**
- CVD flips direction (sign change with `abs(cvd) > 0.05`)
- Volatility doubles or halves from trigger baseline
- Price breaks VAH or VAL (structural regime change)
- Signal strength during cooldown ≥ 1.8× the strength that triggered

### 5.3 Stacked Wait Mode

Instead of a rigid cooldown, the system can operate in **Stacked Wait** mode:

1. First trigger fires AI session normally
2. During cooldown, signals accumulate in a **pending stack**
3. When cooldown expires, evaluate the pending stack:
   - If the best pending signal is stronger than what triggered → fire immediately
   - If 3+ signals stacked in the same direction → fire immediately
   - If nothing accumulated → extend cooldown (market is quiet)

---

## 6. Pre-AI Commonsense Gate

Before spending AI tokens, a **deterministic pre-check** validates that the signal's implied trade is physically possible:

### 6.1 Gate Checks

```
1. ENTRY FEASIBILITY
   - For signal direction: is there a valid entry within max_entry_distance_atr?
   - Check: nearest structural anchor in signal direction exists and is within range

2. RR FEASIBILITY
   - Can a trade in the signal direction achieve min_rr_ranging (or min_rr_trending)?
   - Quick estimate: |entry_candidate - tp_candidate| / |entry_candidate - sl_candidate|

3. DIRECTIONAL SANITY
   - Signal says BULLISH but price is at VAH with massive CVD bearish? → Gate fails
   - Signal says BEARISH but IS_TREND_STRONG bullish and no mean-reversion anchor? → Gate fails

4. CHAOS SURVIVAL
   - If IS_CHAOS: does the signal support a hit-and-run (compressed TP at first boundary)?
   - If IS_CHAOS and signal is directional momentum → Gate fails (chaos override)
```

### 6.2 Gate Outcomes

| Result | Action |
|--------|--------|
| **PASS** | Fire AI session with pre-brief |
| **WEAK_PASS** | Fire AI session but flag "high risk" in pre-brief, reduce confidence threshold for execution |
| **FAIL** | Suppress trigger, log reason, do NOT spend AI tokens |

This gate eliminates the ~30% of triggers that currently result in NEUTRAL because the setup is structurally untradeable.

---

## 7. Context Pre-Brief Injection

When the AI session fires, the trigger intelligence is injected as a structured pre-brief into the observation. The SessionAgent doesn't have to rediscover what the trigger found.

### 7.0 Visibility: SessionAgent Only

The Critic is not part of the Sniper trigger loop — it operates purely inside the Binary Star debate, auditing proposals against market physics. It has no need to know why the session was triggered, and knowing would risk anchoring bias. The pre-brief is injected **exclusively** into the SessionAgent's observation. The Critic sees the same observation it always has — raw market data, the proposed plan, and the math fact check.

### 7.1 Pre-Brief Structure (SessionAgent only)

```json
{
  "trigger_pre_brief": {
    "activated_by": [
      {
        "signal": "CVD_MOMENTUM",
        "direction": "BEARISH",
        "strength": 0.72,
        "confidence": 0.65,
        "key_evidence": "CVD intensity -0.201, growing 1.4× over previous pulse",
        "suggested_thesis": "Institutional selling pressure accelerating — seek short entry on pullback to nearest HVN"
      },
      {
        "signal": "RETAIL_LS_EXTREME",
        "direction": "BEARISH",
        "strength": 0.45,
        "confidence": 0.45,
        "key_evidence": "LS ratio 2.51 — retail heavily long",
        "suggested_thesis": "Retail crowding provides squeeze convexity — long liquidation cascade likely if support breaks"
      }
    ],
    "confluence_score": 0.68,
    "confluence_direction": "BEARISH",
    "stacked_signals_count": 2,
    "regime_note": "IS_TREND_STRONG bearish, IS_EXPANDING — momentum entry authorized",
    "risk_caveats": [
      "CVD dominance is strong but not extreme — watch for absorption",
      "LS extreme can persist for hours — don't force entry without structural confirmation"
    ],
    "suggested_entry_zone": {
      "type": "shallow_pullback_dle",
      "target_area": "nearest HVN above current price",
      "max_distance_atr": 1.0
    }
  }
}
```

### 7.2 How the AI uses this

The pre-brief is appended to the observation JSON. The SessionAgent's prompt already handles `LOGIC_MACROS` evaluation — the pre-brief gives it a **starting hypothesis** rather than a blank slate. This:

- **Reduces debate rounds**: Session starts closer to the right answer → more PASS on R1
- **Improves accuracy**: Session doesn't miss the signal that triggered it
- **Reduces token cost**: Fewer rounds = fewer tokens

---

## 8. New Signal Implementations

### 8.1 Volume Delta Imbalance (FLOW)

```
metric: taker_buy_volume / taker_sell_volume on micro timeframe (last 4 candles)
direction: ratio > 1.3 → BULLISH, ratio < 0.7 → BEARISH
strength: clamp(|ratio - 1.0| / 0.5, 0, 1)  # saturates at 1.5 or 0.5
half_life: 4 min (tick-scale)
```

Requires taker buy/sell volume data — already available via `fetch_taker_long_short_ratio` in Binance client.

### 8.2 OI-Price Divergence (SENTIMENT)

```
metric: sign(price_delta_micro) != sign(oi_delta_micro)
  Price ↑ + OI ↓ = Short squeeze in progress → BEARISH (exhaustion)
  Price ↓ + OI ↑ = Accumulation → BULLISH (smart money buying)
direction: contrarian to price move
strength: clamp(|oi_delta_pct| / 0.03, 0, 1)  # saturates at 3% OI change
half_life: 15 min
```

Requires Open Interest delta between current and previous pulse — already available via `micro_oi` and `current_oi` in RawMarketData.

### 8.3 Multi-Timeframe Alignment (STRUCTURAL)

```
metric: macro trend direction AND micro price pulling back to structure
  Macro: IS_TREND_STRONG with clear direction
  Micro: price within 1.0 ATR of nearest HVN/POC in trend direction
direction: macro trend direction
strength: trend_intensity × (1 - dist_to_structure / 1.0 ATR)
half_life: 10 min
```

This is the classic "trend + pullback to structure" setup — high probability, currently not explicitly detected.

### 8.4 CVD Absorption (FLOW)

```
metric: abs(cvd_intensity) > cvd_intensity_extreme AND |price_delta| < 0.3 × atr_micro
  Extreme CVD with negligible price movement = iceberg orders absorbing flow
direction: opposite to CVD (absorption implies distribution/accumulation against the apparent flow)
strength: clamp((abs(cvd) - cvd_intensity_extreme) / 0.15, 0, 1)
half_life: 10 min
```

### 8.5 Volume Climax (ENERGY)

```
metric: single-bar volume > 3.0 × volume_ma AND price_range > 1.5 × atr_micro
direction: from CVD sign or candle close vs open
strength: clamp((vol / vol_ma - 2.0) / 2.0, 0, 1)  # saturates at 4× MA
half_life: 6 min
```

---

## 9. Feedback Loop: Audit → Signal Weight Calibration

### 9.1 Per-Signal Performance Tracking

Each audit evaluates the session outcome against what actually happened. The trigger system can retroactively score whether the signal that fired was "right":

```
signal_accuracy = did_price_move_in_signal_direction_within_holding_window?
```

Track per signal type:
- `hit_count`: number of times signal fired → trade was profitable (or would have been)
- `miss_count`: number of times signal fired → trade was unprofitable or NEUTRAL
- `false_alarm_count`: signal fired → AI produced NEUTRAL (wasted cost)

### 9.2 Confidence Update

```
updated_confidence = base_confidence + learning_rate × (hit_rate - 0.5)
```

Where `hit_rate = hit_count / (hit_count + miss_count + false_alarm_count)`.

This feeds into the `confidence` field of each Signal Card, creating a **self-tuning** system that automatically weights signals based on their historical reliability.

### 9.3 Evolution Integration

The Evolver agent already mutates `strategy_config.yaml` parameters. The signal confidence weights can become evolvable parameters:

```yaml
sniper:
  signal_weights:
    cvd_divergence: 0.70
    cvd_momentum: 0.65
    squeeze_intensifying: 0.75
    liquidation_magnet: 0.60
    retail_ls_extreme: 0.45
    funding_extreme: 0.40
    poc_magnet: 0.55
    vah_val_approach: 0.50
    oi_price_divergence: 0.70
    volume_delta_imbalance: 0.60
    cvd_absorption: 0.65
    multi_tf_alignment: 0.75
    volume_climax: 0.55
```

The Evolver can adjust these based on audit data, making the trigger system **self-optimizing**.

---

## 10. Implementation Roadmap

### Phase 1: Signal Continuum (low risk, immediate value)

1. Refactor `SniperTrigger` to produce `SignalCard` objects instead of boolean + reason strings
2. Implement continuous strength scoring (0.0–1.0) for all existing signal types
3. Add signal decay tracking between pulses
4. Keep existing cooldown and trigger decision logic unchanged

**Benefit**: Cleaner signal representation without changing behavior.

### Phase 2: Confluence Engine (medium risk, core innovation)

1. Implement `ConfluenceEngine` class that scores the signal stack
2. Add signal stacking, cancellation, and persistence
3. Implement dynamic trigger threshold with regime modifier
4. Add emergency override for single strong signals
5. Full replace of `SniperTrigger.evaluate()` — old code deleted

**Benefit**: The core innovation — multi-signal confluence instead of single-signal trigger.

### Phase 3: Adaptive Cooldown (medium risk)

1. Implement regime-adaptive base cooldown
2. Add condition-change detection for cooldown break
3. Implement Stacked Wait mode (configurable, off by default)

**Benefit**: Fewer missed opportunities during cooldown, better protection during chaos.

### Phase 4: Pre-AI Gate + Context Injection (low risk, high value)

1. Implement deterministic PreAI Gate with the 4 checks
2. Build pre-brief JSON injector into `BinaryStarOrchestrator`
3. Add pre-brief section to session prompt
4. Log gate rejections for audit

**Benefit**: ~30% reduction in wasted AI sessions, faster debate convergence.

### Phase 5: New Signal Types (medium risk)

1. Implement Volume Delta Imbalance
2. Implement OI-Price Divergence
3. Implement Multi-Timeframe Alignment
4. Implement CVD Absorption
5. Implement Volume Climax

**Benefit**: Broader signal coverage, fewer missed opportunity types.

### Phase 6: Feedback Loop (high value, complex)

1. Implement per-signal performance tracking in audit pipeline
2. Add signal weight configuration to `global_config.yaml`
3. Integrate signal weights into Evolver mutation space
4. Run evolution to calibrate weights

**Benefit**: Self-tuning trigger system that improves with more data.

---

## 11. Configuration Design

### 11.1 New `global_config.yaml` section

```yaml
sniper:
  # Existing config preserved...

  # --- Signal Stack Engine ---
  signal_stack:
    enabled: true
    # Base threshold for confluence score to trigger AI session
    trigger_threshold: 0.35
    # Emergency override: fire immediately if any single signal exceeds this
    emergency_threshold: 0.85
    # Regime modifiers (multiplied with trigger_threshold)
    regime_modifiers:
      trending: 0.85
      ranging: 1.15
      squeeze: 0.70
      chaos: 1.50
    # Decay half-lives (minutes) per signal category
    decay:
      flow_tick: 4
      flow_macro: 15
      energy: 20
      sentiment: 60
      structural: 10

  # --- Adaptive Cooldown ---
  cooldown:
    # Existing pulse_cooldown_multiplier preserved as fallback
    adaptive_enabled: true
    regime_base_minutes:
      trending: 25
      ranging: 45
      squeeze: 20
      chaos: 60
    # Condition-change break thresholds
    break_on_cvd_flip: true
    break_on_volatility_double: true
    break_on_strength_ratio: 1.8
    # Stacked Wait mode
    stacked_wait_enabled: false
    stacked_wait_fire_count: 3  # fire if 3+ signals stack same direction

  # --- Pre-AI Gate ---
  pre_ai_gate:
    enabled: true
    checks:
      entry_feasibility: true
      rr_feasibility: true
      directional_sanity: true
      chaos_survival: true

  # --- Signal Confidence Weights (evolvable) ---
  signal_weights:
    # FLOW
    cvd_momentum: 0.65
    cvd_divergence: 0.70
    cvd_absorption: 0.65
    taker_imbalance: 0.60
    # ENERGY
    volatility_surge: 0.55
    squeeze: 0.75
    # STRUCTURAL
    boundary_test: 0.50
    poc_gravity: 0.55
    liquidation_hunt: 0.60
    trend_pullback: 0.75    # highest base confidence — trend+structure is the classic setup
    # POSITIONING
    retail_extreme: 0.43     # merged L/S + funding — common but often early
    oi_divergence: 0.70
    oi_surge: 0.55
    # CROSS-SYMBOL
    leader_sync: 0.40        # amplification only, never triggers alone
```

---

## 12. Expected Impact

| Metric | Current | Target | Mechanism |
|--------|---------|--------|-----------|
| AI sessions per hour (per symbol) | 2–3 | 1–2 | Confluence gating reduces low-quality triggers |
| NEUTRAL outcome rate | ~30% | <15% | Pre-AI gate filters untradeable setups |
| R1 PASS rate | ~33% | >50% | Pre-brief gives SessionAgent starting hypothesis |
| Tokens per session | ~80K–120K | ~50K–80K | Fewer debate rounds (better initial thesis) |
| Missed profitable setups | Unknown | Reduced | Adaptive cooldown + stacked signals |
| Trigger type diversity | 100% FLOW_ASYMMETRY | Mixed | New signal types + regime-appropriate weighting |
| False trigger rate (signal fired → price went opposite) | Unknown | Measured → optimized | Feedback loop calibrates weights |

---

## 13. Resolved Questions

1. **Critic visibility**: The Critic stays completely blind to trigger signals. It is not part of the Sniper trigger loop — it operates purely inside the Binary Star debate, auditing proposals against market physics. The pre-brief is injected exclusively into the SessionAgent's observation.

2. **Stacked signals during cooldown**: Break cooldown immediately when 3+ signals stack in the same direction, or when a single signal exceeds `emergency_threshold` (0.85). The market is telling us something important — don't wait.

3. **Cross-symbol signals**: Yes. Implement Leader Sync (signal #14) with a boost capped at 0.15. Computed from rolling 24h correlation of 15m returns between tracked symbols.

4. **Legacy compatibility**: None. Full replacement — old `SniperTrigger` code is deleted when the new signal stack engine lands. No flags, no fallback, clean cut.

---
---
---
---

# IMPLEMENTATION SPECIFICATION

> **Target audience**: A fresh Claude Code instance with no prior context. Read this section and implement everything below. Do not ask questions — all decisions are made.

---

## 15. File Manifest

| Action | File Path | Description |
|--------|-----------|-------------|
| **REWRITE** | `src/sniper/trigger.py` | Full replacement. Delete all old `SniperTrigger` code. New file contains: `SignalCard`, `SignalType`, `Direction`, `TriggerResult`, `ConfluenceEngine`, `SniperTrigger` |
| **MODIFY** | `src/analyzer/market_observer.py` | Add `taker_imbalance` field to `_derive_sentiment()` return dict (~3 lines) |
| **MODIFY** | `src/sniper/scout.py` | Pass `raw.micro_klines` taker data into distilled metrics (~5 lines in `scout()`) |
| **MODIFY** | `run_sniper.py` | Update `_attempt_trade_execution` to use new `TriggerResult`; update trigger evaluation call in `run_forever()` |
| **MODIFY** | `src/agent/binary_star_orchestrator.py` | Accept optional `pre_brief` in `execute_flow()`, inject into observation before session prompt |
| **MODIFY** | `config/global_config.yaml` | Add `signal_stack`, `signal_weights`, and `pre_ai_gate` blocks under `sniper:` |
| **MODIFY** | `config/prompts/session.md` | Add `{trigger_pre_brief}` placeholder and interpretation instructions |

No files are created from scratch — `src/sniper/trigger.py` is rewritten in-place.

---

## 16. Data Structures (exact Python)

### 16.1 Enums and Dataclasses

```python
from enum import Enum
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List, Tuple


class SignalCategory(str, Enum):
    FLOW = "FLOW"
    ENERGY = "ENERGY"
    STRUCTURAL = "STRUCTURAL"
    POSITIONING = "POSITIONING"
    CROSS_SYMBOL = "CROSS_SYMBOL"


class Direction(str, Enum):
    BULLISH = "BULLISH"
    BEARISH = "BEARISH"
    NEUTRAL = "NEUTRAL"


@dataclass
class SignalCard:
    """A single detected market signal with continuous scoring."""
    signal_id: str                          # unique per pulse: "<SUBTYPE>_<timestamp>"
    category: SignalCategory
    sub_type: str                           # e.g., "cvd_momentum", "trend_pullback"
    direction: Direction
    strength: float                         # 0.0–1.0 continuous
    confidence: float                       # 0.0–1.0 per-signal-type reliability
    urgency: float                          # 0.0–1.0 time-sensitivity
    timestamp: datetime
    decay_half_life_minutes: float
    evidence: Dict[str, Any] = field(default_factory=dict)
    regime_compatibility: float = 1.0       # 0.0–1.0, applied at scoring time

    @property
    def weighted_score(self) -> float:
        """The effective score used in confluence stacking."""
        return self.strength * self.confidence

    def decayed_strength(self, now: datetime) -> float:
        """Strength after applying temporal decay."""
        elapsed = (now - self.timestamp).total_seconds() / 60.0
        if elapsed <= 0:
            return self.strength
        return self.strength * (0.5 ** (elapsed / self.decay_half_life_minutes))

    def decayed_weighted_score(self, now: datetime) -> float:
        """Weighted score after temporal decay."""
        return self.decayed_strength(now) * self.confidence


@dataclass
class TriggerResult:
    """Output of trigger evaluation — replaces old (bool, str, str) tuple."""
    triggered: bool
    confluence_score: float                 # 0.0–1.0 final score that crossed threshold
    confluence_direction: Direction         # dominant direction
    signals: List[SignalCard]               # all signals from this pulse (including decayed survivors)
    active_signals: List[SignalCard]        # signals that contributed to the trigger
    gate_result: str                        # "PASS" | "WEAK_PASS" | "FAIL"
    gate_reason: str                        # human-readable explanation
    pre_brief: Optional[Dict[str, Any]]     # None if not triggered, else the pre-brief JSON
    cooldown_minutes: float                 # the cooldown that will be applied after this trigger
```

### 16.2 Signal Persistence State

```python
@dataclass
class SignalMemory:
    """Tracks signals across pulses for decay and persistence."""
    active_signals: Dict[str, SignalCard] = field(default_factory=dict)
    
    def ingest(self, new_signals: List[SignalCard], now: datetime) -> List[SignalCard]:
        """Add new signals, decay existing ones, purge expired (strength < 0.05)."""
        # Decay existing
        decayed = []
        for sid, card in self.active_signals.items():
            d_strength = card.decayed_strength(now)
            if d_strength > 0.05:
                card.strength = d_strength
                decayed.append(card)
        
        # Merge new signals (replace existing with same sub_type)
        for ns in new_signals:
            key = f"{ns.sub_type}"
            self.active_signals[key] = ns
        
        # Return all alive signals for confluence evaluation
        return decayed + [ns for ns in new_signals 
                          if f"{ns.sub_type}" not in {d.sub_type for d in decayed}]
```

---

## 17. Core Algorithm: ConfluenceEngine

### 17.1 Class Interface

```python
class ConfluenceEngine:
    """Evaluates a stack of SignalCards and produces a confluence score + trigger decision."""
    
    def __init__(self, config: dict):
        self.base_threshold = config['signal_stack']['trigger_threshold']        # 0.35
        self.emergency_threshold = config['signal_stack']['emergency_threshold'] # 0.85
        self.regime_modifiers = config['signal_stack']['regime_modifiers']
        self.signal_weights = config['signal_weights']
        self.min_strength_for_stack = 0.15
        self.break_on_strength_ratio = config['cooldown'].get('break_on_strength_ratio', 1.8)
```

### 17.2 Main Evaluation Method

```python
    def evaluate(
        self,
        signals: List[SignalCard],
        prev_trigger_score: Optional[float],
        prev_trigger_time: Optional[datetime],
        now: datetime,
        regime: str,  # 'trending', 'ranging', 'squeeze', 'chaos'
        is_cooldown_active: bool,
    ) -> Tuple[float, Direction, bool]:
        """
        Returns (confluence_score, dominant_direction, should_trigger).
        
        Algorithm:
        1. Filter out signals with strength < min_strength_for_stack (0.15)
        2. Compute directional_score for BULLISH and BEARISH separately
           directional_score(dir) = 1 - ∏(1 - signal.weighted_score) across all signals in that direction
        3. Compute noise_factor = 1.0 - (bullish_score × bearish_score)
        4. Pick dominant direction = argmax(bullish_score, bearish_score)
        5. confluence_score = max(bullish_score, bearish_score) × noise_factor
        6. Compute effective_threshold = base_threshold × regime_modifier[regime]
        7. Check emergency override: any single signal.strength > emergency_threshold
        8. Check cooldown break: if in cooldown and any signal.strength ≥ prev_trigger_score × break_on_strength_ratio
        9. Return (confluence_score, dominant_direction, should_trigger)
        """
```

### 17.3 Exact Formula

```python
def _directional_score(self, signals: List[SignalCard], direction: Direction) -> float:
    """1 - ∏(1 - s.weighted_score) for all signals matching direction."""
    matching = [s for s in signals if s.direction == direction]
    if not matching:
        return 0.0
    product = 1.0
    for s in matching:
        product *= (1.0 - s.weighted_score)
    return 1.0 - product

def _compute_confluence(self, signals: List[SignalCard]) -> Tuple[float, Direction]:
    """Returns (confluence_score, dominant_direction)."""
    bullish_score = self._directional_score(signals, Direction.BULLISH)
    bearish_score = self._directional_score(signals, Direction.BEARISH)
    
    noise_factor = 1.0 - (bullish_score * bearish_score)
    
    if bullish_score >= bearish_score:
        dominant = Direction.BULLISH
        raw_score = bullish_score
    else:
        dominant = Direction.BEARISH
        raw_score = bearish_score
    
    confluence_score = raw_score * noise_factor
    return confluence_score, dominant
```

---

## 18. Signal Detection Functions (exact implementations)

Each detection function has this signature:
```python
def _detect_<name>(self, curr: dict, prev: Optional[dict], now: datetime) -> Optional[SignalCard]
```

Returns `None` if signal not detected, else a `SignalCard`.

### 18.1 FLOW Signals

#### CVD Momentum (signal #1)
```python
def _detect_cvd_momentum(self, curr, prev, now) -> Optional[SignalCard]:
    cvd = curr['sentiment_signals']['cvd_intensity_ratio']
    threshold = self.regime_cfg['micro_sentiment']['cvd_intensity_threshold']  # 0.10
    if abs(cvd) <= threshold:
        return None
    
    # Growth gate: require growing if prev exists
    if prev:
        prev_cvd = prev['sentiment_signals']['cvd_intensity_ratio']
        growth_ratio = self.sniper_cfg['probes']['cvd_growth_significance_ratio']  # 1.4
        if abs(cvd) <= abs(prev_cvd) * growth_ratio:
            return None
    
    direction = Direction.BULLISH if cvd > 0 else Direction.BEARISH
    strength = min(abs(cvd) / (threshold * 3), 1.0)  # saturates at 3× threshold (0.30)
    confidence = self.signal_weights['cvd_momentum']
    
    return SignalCard(
        signal_id=f"cvd_momentum_{now.strftime('%Y%m%d_%H%M%S')}",
        category=SignalCategory.FLOW,
        sub_type="cvd_momentum",
        direction=direction,
        strength=strength,
        confidence=confidence,
        urgency=0.5,
        timestamp=now,
        decay_half_life_minutes=15.0,
        evidence={"cvd_intensity": cvd, "threshold": threshold}
    )
```

#### CVD Divergence (signal #2)
```python
def _detect_cvd_divergence(self, curr, prev, now) -> Optional[SignalCard]:
    if not prev:
        return None
    cvd = curr['sentiment_signals']['cvd_intensity_ratio']
    prev_cvd = prev['sentiment_signals']['cvd_intensity_ratio']
    cvd_delta = cvd - prev_cvd
    threshold = self.sniper_cfg['probes']['cvd_divergence_tick_delta']  # 0.22
    if abs(cvd_delta) <= threshold:
        return None
    
    price_delta = curr['price_dynamics']['current_price'] - prev['price_dynamics']['current_price']
    # Divergence: price and CVD move opposite
    if not ((price_delta > 0 and cvd_delta < 0) or (price_delta < 0 and cvd_delta > 0)):
        return None
    
    # Price↑ CVD↓ = distribution → BEARISH; Price↓ CVD↑ = accumulation → BULLISH
    direction = Direction.BEARISH if price_delta > 0 else Direction.BULLISH
    strength = min(abs(cvd_delta) / (threshold * 3), 1.0)
    confidence = self.signal_weights['cvd_divergence']
    
    return SignalCard(
        signal_id=f"cvd_divergence_{now.strftime('%Y%m%d_%H%M%S')}",
        category=SignalCategory.FLOW,
        sub_type="cvd_divergence",
        direction=direction,
        strength=strength,
        confidence=confidence,
        urgency=0.7,
        timestamp=now,
        decay_half_life_minutes=4.0,
        evidence={"cvd_delta": cvd_delta, "price_delta": price_delta, "threshold": threshold}
    )
```

#### CVD Absorption (signal #3)
```python
def _detect_cvd_absorption(self, curr, prev, now) -> Optional[SignalCard]:
    cvd = curr['sentiment_signals']['cvd_intensity_ratio']
    extreme_threshold = self.regime_cfg['micro_sentiment']['cvd_intensity_extreme']  # 0.25
    if abs(cvd) <= extreme_threshold:
        return None
    if not prev:
        return None
    price_delta = abs(curr['price_dynamics']['current_price'] - prev['price_dynamics']['current_price'])
    atr_micro = curr['price_dynamics']['atr_micro']
    if price_delta >= 0.3 * max(atr_micro, 0.01):
        return None  # price IS moving — not absorption
    
    direction = Direction.BEARISH if cvd > 0 else Direction.BULLISH  # opposite to CVD
    strength = min((abs(cvd) - extreme_threshold) / 0.15, 1.0)
    confidence = self.signal_weights['cvd_absorption']
    
    return SignalCard(
        signal_id=f"cvd_absorption_{now.strftime('%Y%m%d_%H%M%S')}",
        category=SignalCategory.FLOW,
        sub_type="cvd_absorption",
        direction=direction,
        strength=strength,
        confidence=confidence,
        urgency=0.6,
        timestamp=now,
        decay_half_life_minutes=10.0,
        evidence={"cvd_intensity": cvd, "price_delta": price_delta}
    )
```

#### Taker Imbalance (signal #4)
```python
def _detect_taker_imbalance(self, curr, prev, now) -> Optional[SignalCard]:
    ratio = curr['sentiment_signals'].get('taker_imbalance_ratio')
    if ratio is None:
        return None
    if ratio > 0.60:
        direction = Direction.BULLISH
        strength = min((ratio - 0.60) / 0.40, 1.0)  # saturates at 1.0
    elif ratio < 0.40:
        direction = Direction.BEARISH
        strength = min((0.40 - ratio) / 0.40, 1.0)
    else:
        return None
    confidence = self.signal_weights['taker_imbalance']
    
    return SignalCard(
        signal_id=f"taker_imbalance_{now.strftime('%Y%m%d_%H%M%S')}",
        category=SignalCategory.FLOW,
        sub_type="taker_imbalance",
        direction=direction,
        strength=strength,
        confidence=confidence,
        urgency=0.6,
        timestamp=now,
        decay_half_life_minutes=4.0,
        evidence={"taker_ratio": ratio}
    )
```

### 18.2 ENERGY Signals

#### Volatility Surge (signal #5)
```python
def _detect_volatility_surge(self, curr, prev, now) -> Optional[SignalCard]:
    vii = curr['price_dynamics']['volatility_intensity_index']
    vpr = curr['market_regime']['volume_participation_ratio']
    baseline = self.regime_cfg['volatility']['volatility_baseline_ratio']  # 1.25
    vol_threshold = self.regime_cfg['volume']['volume_participation_threshold']  # 1.5
    
    if not (vii > baseline and vpr > vol_threshold):
        return None
    # Acceleration gate
    if prev:
        prev_vii = prev['price_dynamics']['volatility_intensity_index']
        growth_ratio = self.sniper_cfg['probes'].get('volatility_growth_significance_ratio', 1.03)
        if vii <= prev_vii * growth_ratio:
            return None
    
    cvd = curr['sentiment_signals']['cvd_intensity_ratio']
    # Direction from CVD, fallback to trend
    if abs(cvd) > 0.05:
        direction = Direction.BULLISH if cvd > 0 else Direction.BEARISH
    else:
        trend = curr['market_regime'].get('trend_intensity', 0)
        direction = Direction.BULLISH if trend > 0 else Direction.BEARISH
    
    strength = min((vii - baseline) / (baseline * 2), 1.0)
    confidence = self.signal_weights['volatility_surge']
    
    return SignalCard(
        signal_id=f"volatility_surge_{now.strftime('%Y%m%d_%H%M%S')}",
        category=SignalCategory.ENERGY,
        sub_type="volatility_surge",
        direction=direction,
        strength=strength,
        confidence=confidence,
        urgency=0.5,
        timestamp=now,
        decay_half_life_minutes=20.0,
        evidence={"vii": vii, "vpr": vpr}
    )
```

#### Squeeze (signal #6)
```python
def _detect_squeeze(self, curr, prev, now) -> Optional[SignalCard]:
    sf = curr['market_regime']['squeeze_factor']
    threshold = (self.regime_cfg['volatility']['squeeze_threshold'] * 
                 self.sniper_cfg['probes']['squeeze_trigger_multiplier'])  # 1.0 * 0.75 = 0.75
    if sf >= threshold:
        return None
    # Intensifying gate
    if prev:
        prev_sf = prev['market_regime']['squeeze_factor']
        if sf >= prev_sf * 0.98:  # not tightening at least 2%
            return None
    
    strength = min((threshold - sf) / threshold, 1.0)
    confidence = self.signal_weights['squeeze']
    
    return SignalCard(
        signal_id=f"squeeze_{now.strftime('%Y%m%d_%H%M%S')}",
        category=SignalCategory.ENERGY,
        sub_type="squeeze",
        direction=Direction.NEUTRAL,
        strength=strength,
        confidence=confidence,
        urgency=0.9,  # squeeze = time-sensitive
        timestamp=now,
        decay_half_life_minutes=20.0,
        evidence={"squeeze_factor": sf, "threshold": threshold}
    )
```

### 18.3 STRUCTURAL Signals

#### Boundary Test (signal #7), POC Gravity (signal #8), Liquidation Hunt (signal #9)

These three reuse the existing `_check_structural_approach` logic but produce `SignalCard` objects instead of boolean tuples. Implementation pattern:

```python
def _detect_boundary_test(self, curr, prev, now) -> Optional[SignalCard]:
    """VAH/VAL boundary approach."""
    topo = curr['volume_profile']
    atr = curr['price_dynamics']['atr_macro']
    price = curr['price_dynamics']['current_price']
    part = curr['market_regime']['volume_participation_ratio']
    
    if atr <= 0:
        return None
    
    dist_vh = abs(price - topo['vah']) / atr
    dist_val = abs(price - topo['val']) / atr
    threshold = self.sniper_cfg['proximity']['proximity_vah_val_atr']  # 0.70
    
    nearest_dist = min(dist_vh, dist_val)
    nearest = 'VAH' if dist_vh < dist_val else 'VAL'
    
    if nearest_dist >= threshold or part <= self.regime_cfg['volume']['min_volume_participation_ratio']:
        return None
    
    # Directional gate: must be approaching, not retreating
    if prev:
        prev_price = prev['price_dynamics']['current_price']
        approaching_up = nearest == 'VAH' and price > prev_price
        approaching_down = nearest == 'VAL' and price < prev_price
        if not (approaching_up or approaching_down):
            return None
    
    direction = Direction.BULLISH if nearest == 'VAH' else Direction.BEARISH
    strength = min(threshold / max(nearest_dist, 0.01) * 0.25, 1.0)
    confidence = self.signal_weights['boundary_test']
    
    return SignalCard(
        signal_id=f"boundary_test_{now.strftime('%Y%m%d_%H%M%S')}",
        category=SignalCategory.STRUCTURAL,
        sub_type="boundary_test",
        direction=direction,
        strength=strength,
        confidence=confidence,
        urgency=0.4,
        timestamp=now,
        decay_half_life_minutes=10.0,
        evidence={"boundary": nearest, "dist_atr": nearest_dist, "threshold": threshold}
    )
```

POC Gravity and Liquidation Hunt follow the same pattern — port the existing `_check_structural_approach` sub-checks into individual `_detect_*` methods returning `SignalCard`.

#### Trend Pullback (signal #10) — NEW
```python
def _detect_trend_pullback(self, curr, prev, now) -> Optional[SignalCard]:
    trend = curr['market_regime'].get('trend_intensity', 0)
    strong_threshold = self.regime_cfg['trend']['trend_intensity_strong']  # 0.35
    if abs(trend) <= strong_threshold:
        return None
    
    direction = Direction.BULLISH if trend > 0 else Direction.BEARISH
    price = curr['price_dynamics']['current_price']
    atr = curr['price_dynamics']['atr_macro']
    vp = curr['volume_profile']
    
    # Find nearest HVN or POC in the trend direction (behind price for a pullback)
    if direction == Direction.BULLISH:
        # In uptrend: price should be pulling BACK (down) toward structure below
        target_price = vp.get('poc', price)
        # Check anchors_below for HVNs
        for anchor in vp.get('anchors_below', []):
            if anchor.get('type') == 'HVN':
                target_price = anchor['price']
                break
        dist_atr = abs(price - target_price) / max(atr, 0.01)
        # Must be above the structure (pullback target is below)
        if price <= target_price:
            return None
    else:
        # In downtrend: price should be pulling BACK (up) toward structure above
        target_price = vp.get('poc', price)
        for anchor in vp.get('anchors_above', []):
            if anchor.get('type') == 'HVN':
                target_price = anchor['price']
                break
        dist_atr = abs(price - target_price) / max(atr, 0.01)
        if price >= target_price:
            return None
    
    max_dist = self.regime_cfg['structural'].get('max_entry_distance_atr', 1.0)
    if dist_atr > max_dist:
        return None  # structure too far — not a meaningful pullback
    
    strength = abs(trend) * (1.0 - dist_atr / max_dist)
    confidence = self.signal_weights['trend_pullback']
    
    return SignalCard(
        signal_id=f"trend_pullback_{now.strftime('%Y%m%d_%H%M%S')}",
        category=SignalCategory.STRUCTURAL,
        sub_type="trend_pullback",
        direction=direction,
        strength=strength,
        confidence=confidence,
        urgency=0.6,
        timestamp=now,
        decay_half_life_minutes=10.0,
        evidence={"trend_intensity": trend, "dist_to_structure_atr": dist_atr}
    )
```

### 18.4 POSITIONING Signals

#### Retail Extreme (signal #11) — merged L/S + funding
```python
def _detect_retail_extreme(self, curr, prev, now) -> Optional[SignalCard]:
    ls = curr['sentiment_signals'].get('ls_ratio_micro', 1.0)
    funding = curr['sentiment_signals'].get('funding_rate', 0.0)
    cfg = self.regime_cfg['imbalance']
    
    direction = None
    evidence = {}
    
    if ls > cfg['long_short_imbalance_ratio']:  # 1.5
        direction = Direction.BEARISH
        strength = min((ls - 1.0) / (cfg['long_short_imbalance_ratio'] * 2), 1.0)
        evidence['trigger'] = 'ls_long'
        evidence['ls_ratio'] = ls
    elif ls < cfg['short_heavy_imbalance_ratio']:  # 0.6
        direction = Direction.BULLISH
        strength = min((1.0 - ls) / (1.0 - cfg['short_heavy_imbalance_ratio'] * 2), 1.0)
        evidence['trigger'] = 'ls_short'
        evidence['ls_ratio'] = ls
    
    funding_threshold = self.regime_cfg['micro_sentiment']['funding_extreme_threshold']  # 0.0005
    if abs(funding) > funding_threshold:
        f_direction = Direction.BEARISH if funding > 0 else Direction.BULLISH
        f_strength = min(abs(funding) / (funding_threshold * 4), 1.0)
        if direction is None or f_strength > strength:
            direction = f_direction
            strength = f_strength
            evidence['trigger'] = 'funding'
            evidence['funding_rate'] = funding
    
    if direction is None:
        return None
    
    confidence = self.signal_weights['retail_extreme']
    
    return SignalCard(
        signal_id=f"retail_extreme_{now.strftime('%Y%m%d_%H%M%S')}",
        category=SignalCategory.POSITIONING,
        sub_type="retail_extreme",
        direction=direction,
        strength=strength,
        confidence=confidence,
        urgency=0.3,  # sentiment is slow-burn
        timestamp=now,
        decay_half_life_minutes=60.0,
        evidence=evidence
    )
```

#### OI Divergence (signal #12)
```python
def _detect_oi_divergence(self, curr, prev, now) -> Optional[SignalCard]:
    if not prev:
        return None
    oi_delta = curr['sentiment_signals'].get('oi_delta_micro', 0.0)
    price_delta = curr['price_dynamics']['current_price'] - prev['price_dynamics']['current_price']
    
    if oi_delta == 0 or price_delta == 0:
        return None
    # Divergence: OI and price move opposite
    if (oi_delta > 0 and price_delta > 0) or (oi_delta < 0 and price_delta < 0):
        return None  # aligned — no divergence signal
    
    direction = Direction.BEARISH if price_delta > 0 else Direction.BULLISH
    strength = min(abs(oi_delta) / 0.03, 1.0)  # saturates at 3% OI change
    confidence = self.signal_weights['oi_divergence']
    
    return SignalCard(
        signal_id=f"oi_divergence_{now.strftime('%Y%m%d_%H%M%S')}",
        category=SignalCategory.POSITIONING,
        sub_type="oi_divergence",
        direction=direction,
        strength=strength,
        confidence=confidence,
        urgency=0.5,
        timestamp=now,
        decay_half_life_minutes=15.0,
        evidence={"oi_delta": oi_delta, "price_delta": price_delta}
    )
```

#### OI Surge (signal #13)
```python
def _detect_oi_surge(self, curr, prev, now) -> Optional[SignalCard]:
    oi_delta = curr['sentiment_signals'].get('oi_delta_micro', 0.0)
    if abs(oi_delta) <= 0.02:
        return None
    if not prev:
        return None
    price_delta = curr['price_dynamics']['current_price'] - prev['price_dynamics']['current_price']
    # Must be aligned: OI and price moving same direction
    if (oi_delta > 0 and price_delta <= 0) or (oi_delta < 0 and price_delta >= 0):
        return None
    
    direction = Direction.BULLISH if price_delta > 0 else Direction.BEARISH
    strength = min((abs(oi_delta) - 0.02) / 0.04, 1.0)
    confidence = self.signal_weights['oi_surge']
    
    return SignalCard(
        signal_id=f"oi_surge_{now.strftime('%Y%m%d_%H%M%S')}",
        category=SignalCategory.POSITIONING,
        sub_type="oi_surge",
        direction=direction,
        strength=strength,
        confidence=confidence,
        urgency=0.4,
        timestamp=now,
        decay_half_life_minutes=20.0,
        evidence={"oi_delta": oi_delta, "price_delta": price_delta}
    )
```

### 18.5 CROSS-SYMBOL Signal

#### Leader Sync (signal #14)
```python
def _detect_leader_sync(self, own_signals: List[SignalCard], 
                        leader_confluence_score: float,
                        leader_direction: Direction,
                        correlation: float,
                        now: datetime) -> Optional[SignalCard]:
    """Amplify existing weak directional alignment when leader fires."""
    if leader_confluence_score <= 0:
        return None
    
    # Find own signals matching leader direction
    aligned = [s for s in own_signals if s.direction == leader_direction]
    if not aligned:
        return None  # no alignment to amplify
    
    boost = min(leader_confluence_score * correlation * 0.30, 0.15)
    strength = boost  # the signal IS the amplification
    confidence = self.signal_weights['leader_sync']
    
    return SignalCard(
        signal_id=f"leader_sync_{now.strftime('%Y%m%d_%H%M%S')}",
        category=SignalCategory.CROSS_SYMBOL,
        sub_type="leader_sync",
        direction=leader_direction,
        strength=strength,
        confidence=confidence,
        urgency=0.5,
        timestamp=now,
        decay_half_life_minutes=8.0,
        evidence={"leader_score": leader_confluence_score, "correlation": correlation}
    )
```

---

## 19. Deterministic Signal Detection Registry

All detection functions are registered in a list for sequential evaluation:

```python
class SniperTrigger:
    def __init__(self, strategy_cfg, global_cfg):
        # ... config loading ...
        
        # Ordered signal detection registry (all 13 direct signals)
        # Order matters: FLOW first (fastest), then ENERGY, STRUCTURAL, POSITIONING
        self._signal_detectors = [
            # FLOW
            self._detect_cvd_momentum,
            self._detect_cvd_divergence,
            self._detect_cvd_absorption,
            self._detect_taker_imbalance,
            # ENERGY
            self._detect_volatility_surge,
            self._detect_squeeze,
            # STRUCTURAL
            self._detect_boundary_test,
            self._detect_poc_gravity,
            self._detect_liquidation_hunt,
            self._detect_trend_pullback,
            # POSITIONING
            self._detect_retail_extreme,
            self._detect_oi_divergence,
            self._detect_oi_surge,
        ]
        
        self.engine = ConfluenceEngine(self.sniper_cfg)
        self.memory = SignalMemory()
```

---

## 20. Main evaluate() Method (replaces old method)

```python
    def evaluate(self, current_metrics: Dict[str, Any], 
                 prev_metrics: Optional[Dict[str, Any]] = None) -> TriggerResult:
        """
        NEW evaluate() — full replacement of old (bool, str, str) method.
        
        Returns TriggerResult with confluence score, signals, gate result, and pre_brief.
        """
        now = datetime.now(timezone.utc)
        
        # 0. Cooldown check (regime-adaptive)
        regime = self._determine_regime(current_metrics)
        cooldown_active, cooldown_reason = self._check_adaptive_cooldown(now, regime)
        
        # 1. Detect all signals from current pulse
        fresh_signals = []
        for detector in self._signal_detectors:
            card = detector(current_metrics, prev_metrics, now)
            if card:
                fresh_signals.append(card)
        
        # 2. Merge with decayed signal memory
        all_signals = self.memory.ingest(fresh_signals, now)
        
        # 3. Compute confluence
        confluence_score, dominant_direction = self.engine._compute_confluence(all_signals)
        
        # 4. Determine trigger threshold based on regime
        modifier = self.engine.regime_modifiers.get(regime, 1.0)
        effective_threshold = self.engine.base_threshold * modifier
        
        # 5. Emergency override: fire if any single signal exceeds emergency_threshold
        emergency = any(s.strength >= self.engine.emergency_threshold for s in fresh_signals)
        
        # 6. Cooldown break: stacked signals during cooldown
        cooldown_break = False
        if cooldown_active and not emergency:
            # Break if 3+ fresh signals stack in same direction
            dir_counts = {}
            for s in fresh_signals:
                if s.direction != Direction.NEUTRAL:
                    dir_counts[s.direction] = dir_counts.get(s.direction, 0) + 1
            if any(c >= 3 for c in dir_counts.values()):
                cooldown_break = True
        
        should_trigger = (not cooldown_active) or emergency or cooldown_break
        if should_trigger:
            should_trigger = confluence_score >= effective_threshold or emergency
        
        # 7. Pre-AI Gate (only if should_trigger)
        gate_result = "PASS"
        gate_reason = ""
        if should_trigger:
            gate_result, gate_reason = self._run_pre_ai_gate(
                current_metrics, all_signals, dominant_direction, regime
            )
            if gate_result == "FAIL":
                should_trigger = False
        
        # 8. Build pre-brief if triggering
        pre_brief = None
        if should_trigger:
            pre_brief = self._build_pre_brief(
                all_signals, confluence_score, dominant_direction, regime, gate_result
            )
        
        # 9. Determine cooldown after this trigger
        cooldown_mins = self._get_regime_cooldown(regime)
        
        result = TriggerResult(
            triggered=should_trigger,
            confluence_score=confluence_score,
            confluence_direction=dominant_direction,
            signals=all_signals,
            active_signals=[s for s in fresh_signals if s.strength >= 0.15],
            gate_result=gate_result,
            gate_reason=gate_reason,
            pre_brief=pre_brief,
            cooldown_minutes=cooldown_mins,
        )
        
        if should_trigger:
            logger.info(f"SNIPER WAKE UP! [{dominant_direction.value}] confluence={confluence_score:.2f} "
                       f"signals={len(fresh_signals)} gate={gate_result} regime={regime}")
        
        return result
```

---

## 21. Configuration Changes

### 21.1 `config/global_config.yaml` additions

Insert the following under the existing `sniper:` block (KEEP all existing `heartbeat`, `cooldown`, `probes`, `proximity` sections — add the new sections below them):

```yaml
  # --- Signal Stack Engine ---
  signal_stack:
    enabled: true
    trigger_threshold: 0.35
    emergency_threshold: 0.85
    regime_modifiers:
      trending: 0.85
      ranging: 1.15
      squeeze: 0.70
      chaos: 1.50
    decay:
      flow_tick: 4
      flow_macro: 15
      energy: 20
      sentiment: 60
      structural: 10

  # --- Pre-AI Gate ---
  pre_ai_gate:
    enabled: true
    checks:
      entry_feasibility: true
      rr_feasibility: true
      directional_sanity: true
      chaos_survival: true

  # --- Signal Confidence Weights (evolvable) ---
  signal_weights:
    cvd_momentum: 0.65
    cvd_divergence: 0.70
    cvd_absorption: 0.65
    taker_imbalance: 0.60
    volatility_surge: 0.55
    squeeze: 0.75
    boundary_test: 0.50
    poc_gravity: 0.55
    liquidation_hunt: 0.60
    trend_pullback: 0.75
    retail_extreme: 0.43
    oi_divergence: 0.70
    oi_surge: 0.55
    leader_sync: 0.40
```

**IMPORTANT**: Also update the existing `cooldown:` section. Keep `pulse_cooldown_multiplier` and `chaos_cooldown_multiplier` and `state_lockout_hours` but add:

```yaml
  cooldown:
    # ... existing fields preserved ...
    # NEW: Adaptive cooldown
    adaptive_enabled: true
    regime_base_minutes:
      trending: 25
      ranging: 45
      squeeze: 20
      chaos: 60
    break_on_cvd_flip: true
    break_on_volatility_double: true
    break_on_strength_ratio: 1.8
    break_min_gap_minutes: 10
    stacked_break_count: 3
```

### 21.2 `config/prompts/session.md` addition

Insert after the `# INPUT_DATUM` section, before `# LOGIC_MACROS`:

```markdown
- **Trigger Pre-Brief**: `{trigger_pre_brief}` — The Sniper trigger system's intelligence report. This is your starting hypothesis. You are NOT bound to it; use it as a compass, not a map. If physical evidence contradicts the pre-brief, the physics wins.
```

---

## 22. Integration Point Changes

### 22.1 `src/sniper/scout.py` — Pass taker data

In `scout()`, add one field to the distilled metrics. After the existing `sentiment_signals` block, add taker imbalance calculation:

```python
# In SniperScout.scout(), after line ~109 where distilled is built:
# Add taker imbalance ratio to sentiment_signals
if hasattr(raw, 'micro_klines') and raw.micro_klines:
    lookback = min(4, len(raw.micro_klines))
    recent = raw.micro_klines[-lookback:]
    total_taker_buy = sum(k.taker_buy_base for k in recent if k.taker_buy_base is not None)
    total_vol = sum(k.volume for k in recent)
    distilled['sentiment_signals']['taker_imbalance_ratio'] = (
        total_taker_buy / total_vol if total_vol > 0 else None
    )
```

### 22.2 `src/analyzer/market_observer.py` — Forward taker data

In `_derive_sentiment()`, add one line to the return dict after the `cvd_lookback_candles` line (~line 555):

```python
"taker_imbalance_ratio": None,  # filled by SniperScout for trigger evaluation
```

### 22.3 `run_sniper.py` — Use new TriggerResult

Change the trigger evaluation call in `run_forever()` from:

```python
# OLD:
is_noteworthy, t_type, reason = self.triggers[sym].evaluate(
    metrics[sym], self.prev_metrics.get(sym)
)
if not is_noteworthy:
    status = reason if "COOLDOWN" in reason else "SLEEPING"
    print(f"[{now_str}] [{sym}] 💤 {status} | No actionable asymmetry detected.")
else:
    # ... print trigger and append to triggered list
    triggered.append((sym, t_type, reason))
```

To:

```python
# NEW:
result = self.triggers[sym].evaluate(
    metrics[sym], self.prev_metrics.get(sym)
)
if not result.triggered:
    status = result.gate_reason or "SLEEPING"
    print(f"[{now_str}] [{sym}] 💤 {status}")
else:
    print("\n" + "!" * 60)
    print(f"       🔫 SNIPER WAKE UP! [{sym}] [{result.confluence_direction.value}]")
    print("!" * 60)
    print(f"[{sym}] Confluence: {result.confluence_score:.2f} | "
          f"Signals: {len(result.active_signals)} | Gate: {result.gate_result}")
    print(f"[{sym}] Signals: {[s.sub_type for s in result.active_signals]}")
    print("!" * 60 + "\n")
    triggered.append((sym, result))
```

Update the AI session dispatch block:

```python
# OLD:
for sym, t_type, reason in triggered:

# NEW:
for sym, result in triggered:
```

And pass the pre-brief to the session engine:

```python
# OLD:
session_result = self.session_engines[sym].execute_cycle()

# NEW:
session_result = self.session_engines[sym].execute_cycle(
    pre_brief=result.pre_brief
)
```

Update `set_triggered`:

```python
# OLD:
self.triggers[sym].set_triggered(t_type)

# NEW:
self.triggers[sym].set_triggered(result)
```

### 22.4 `src/agent/binary_star_orchestrator.py` — Accept pre_brief

In `execute_flow()`, add optional `pre_brief` parameter:

```python
def execute_flow(self, observation: dict, symbol: str, 
                 pre_brief: Optional[Dict[str, Any]] = None) -> dict:
```

When building the session prompt, inject the pre-brief into the observation or as a separate template variable. The simplest approach: add it to the observation dict under `trigger_pre_brief` key before the session agent reads it.

### 22.5 `run_session.py` — Thread pre_brief through

`SessionEngine.execute_cycle()` needs to accept and forward `pre_brief` to `execute_flow()`. Add `pre_brief` parameter and pass it through.

---

## 23. Implementation Order (sequential, each phase complete before next)

### Step 1: Data structures and config — `trigger.py` + `global_config.yaml`
1. Delete ALL old code in `src/sniper/trigger.py`
2. Add `SignalCard`, `SignalType`, `Direction`, `TriggerResult`, `SignalMemory` dataclasses
3. Add `ConfluenceEngine` class with `_directional_score()` and `_compute_confluence()`
4. Add new config sections to `config/global_config.yaml`
5. Verify: `python -c "from src.sniper.trigger import SignalCard, ConfluenceEngine; print('OK')"`

### Step 2: Port existing 9 signal detectors to SignalCard format
1. Implement `_detect_cvd_momentum`, `_detect_cvd_divergence` (port from old `_check_flow_asymmetry`)
2. Implement `_detect_volatility_surge`, `_detect_squeeze` (port from old `_check_energy_buildup`)
3. Implement `_detect_boundary_test`, `_detect_poc_gravity`, `_detect_liquidation_hunt` (port from old `_check_structural_approach`)
4. Implement `_detect_retail_extreme` (merge old `_check_retail_sentiment` + `_check_funding_extreme`)
5. Build `_signal_detectors` registry list
6. Implement new `evaluate()` method using ConfluenceEngine
7. Implement `_determine_regime()`, `_check_adaptive_cooldown()`, `_get_regime_cooldown()`
8. Implement `_run_pre_ai_gate()` with the 4 checks
9. Implement `_build_pre_brief()` and `set_triggered()`
10. Verify: existing behavior roughly preserved (run sniper in dry-run, check log output)

### Step 3: Add new signal types
1. Implement `_detect_cvd_absorption`
2. Implement `_detect_taker_imbalance` + add `taker_imbalance_ratio` to scout/observer
3. Implement `_detect_trend_pullback`
4. Implement `_detect_oi_divergence`
5. Implement `_detect_oi_surge`
6. Add all to `_signal_detectors` registry
7. Verify: run sniper, check that new signal types appear in log output

### Step 4: Integration
1. Update `run_sniper.py` to use `TriggerResult` instead of `(bool, str, str)`
2. Update `SessionEngine.execute_cycle()` to accept and forward `pre_brief`
3. Update `BinaryStarOrchestrator.execute_flow()` to accept and inject `pre_brief`
4. Update `config/prompts/session.md` with trigger pre-brief placeholder
5. End-to-end test: `python run.py sniper -p data/prod --symbol BTC --trade 800`

### Step 5: Cross-symbol
1. Implement `_detect_leader_sync`
2. Add cross-symbol loop in `SniperDaemon.run_forever()`: after all symbols evaluate, compute Leader Sync boosts and re-evaluate followers
3. Add per-pair correlation config or compute from kline data

---

## 24. Testing Strategy

### Unit tests (add to `tests/unit/test_trigger.py`)
1. `test_signal_card_decay` — verify half-life math
2. `test_directional_score_empty` — empty signals → 0.0
3. `test_directional_score_single` — one signal → weighted_score
4. `test_directional_score_stacking` — two signals → sub-linear amplification
5. `test_confluence_noise_cancellation` — equal bullish+bearish → suppressed score
6. `test_confluence_dominant_direction` — asymmetric signals → correct direction
7. `test_emergency_override` — single signal > 0.85 fires regardless
8. `test_cooldown_break_stacked` — 3+ same-direction signals break cooldown
9. `test_regime_modifier` — chaos threshold > trending threshold
10. `test_pre_ai_gate_rr_fail` — impossible RR → FAIL
11. `test_each_detector_with_real_data` — load a session JSON, feed metrics, verify SignalCard output

### Integration test
```bash
# Dry run (no trade) for 10 minutes, verify output
python run.py sniper -p data/prod --symbol BTC --trade 0
```

---

## 25. Resolved Questions

1. **Critic visibility**: Completely blind. Pre-brief injected into SessionAgent only.
2. **Stacked signals during cooldown**: Break immediately at 3+ same-direction signals.
3. **Cross-symbol**: Leader Sync boost capped at 0.15.
4. **Legacy compatibility**: None. Full replacement. Old code deleted.

## 26. Design Decisions Still Open (pick one, implement it)

1. **Min strength for stacking**: Exclude signals < 0.15. Decision: **YES, exclude.**
2. **Leader Sync correlation**: Use fixed per-pair values. Decision: **BTC→XAUT: 0.40, BTC→ETH: 0.75.**
3. **Taker data plumbing**: Add `taker_imbalance_ratio` to `_derive_sentiment()` and `scout()`. Decision: **YES.**
4. **Cooldown break minimum gap**: 10 minutes. Decision: **YES, enforce.**
