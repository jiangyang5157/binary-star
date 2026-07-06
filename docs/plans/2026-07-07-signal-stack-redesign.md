# Signal Stack Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reduce the 13-signal trigger stack to 9 signals by removing 4 redundant/dead detectors, merging 3 positioning detectors into 1, and adding 2 new detectors (large_trade + positioning_extreme).

**Architecture:** Signal stack = market anomaly detector. Each of 9 signals detects one distinct type of unusual activity. CVD signals are reduced from 4→3. A new SIZE category detects large-player activity via `klines.trades`. Three dead positioning signals merge into one with three trigger paths. Direction and quality decisions remain the Binary Star's responsibility.

**Tech Stack:** Python 3.11+, existing codebase patterns (dataclass SignalCard, SniperTrigger class with per-detector methods)

## Global Constraints

- Do NOT touch `config/strategy_config.yaml` (regime parameters are strategy-owned)
- Do NOT touch `src/agent/order_executor.py`, `run_sniper.py`, `run_session.py` (order management + daemon/session interfaces unchanged)
- `TriggerResult` and `SignalCard` dataclasses unchanged — backward-compatible
- `situation_brief` structure unchanged — `activated_by` still uses `sub_type.UPPER()`
- Signal confidence weights in `config/global_config.yaml` → `sniper.signal_stack.weights`
- Per-symbol thresholds in `config/symbol_config.yaml` → `XAUTUSDT.overrides`

---
````

### Task 1: Add avg_trade_size to market observer sentiment data

**Files:**
- Modify: `src/analyzer/market_observer.py:556-576`

**Interfaces:**
- Produces: `sentiment_signals.avg_trade_size` (float), `sentiment_signals.trade_count` (int) — consumed by Task 4's large_trade detector

- [ ] **Step 1: Add avg_trade_size and trade_count to _derive_sentiment return dict**

In `src/analyzer/market_observer.py`, inside `_derive_sentiment`, add after the CVD calculation block (line 543):

```python
        # 2. Calculate avg trade size (large-player activity proxy)
        avg_trade_size = 0.0
        trade_count = 0
        if len(raw.micro_klines) >= lookback_candles:
            curr_window = raw.micro_klines[-lookback_candles:]
            total_trades = sum(
                k.trades for k in curr_window if k.trades is not None
            )
            if total_trades > 0 and cvd_total_vol > 0:
                avg_trade_size = cvd_total_vol / total_trades
                trade_count = total_trades
```

Then add these two fields to the return dict (after `"cvd_lookback_candles": lookback_candles,`):

```python
            "avg_trade_size": avg_trade_size,
            "trade_count": trade_count,
```

- [ ] **Step 2: Commit**

```bash
git add src/analyzer/market_observer.py
git commit -m "feat: add avg_trade_size and trade_count to sentiment signals

Derived from micro klines — avg_trade_size = total_volume / total_trades
across the CVD lookback window. Zero additional API cost."
```

---

### Task 2: Update config/global_config.yaml signal_stack section

**Files:**
- Modify: `config/global_config.yaml:169-197`

**Interfaces:**
- Produces: `signal_stack.weights` with updated keys, `signal_stack.thresholds` with new entries
- Consumed by: Task 3-5 (trigger.py reads config at init)

- [ ] **Step 1: Replace weights block**

Replace lines 169-188 (the `weights:` block) with:

```yaml
    weights:
      # FLOW — 资金流（快变量，可靠但短命）
      cvd_momentum: 0.65      # CVD 方向+极端：合并原 taker_imbalance 的静态检测
      cvd_divergence: 0.70    # CVD-价格背离：强信号，聪明钱 vs 散户
      cvd_absorption: 0.50    # CVD 吸收：无 OB 数据佐证，降权（原 0.65）
      # SIZE — 大单/机构活动
      large_trade: 0.55       # 平均成交额异常：大资金进场 proxy
      # ENERGY — 波动能量
      volatility_surge: 0.55  # 波动率激增：不具方向性，需叠加其他信号
      squeeze: 0.75           # 布林带压缩：最佳前置信号，突破 precursor
      # STRUCTURAL — 结构锚点
      boundary_test: 0.50     # VAH/VAL 触碰：假突破多，权重最低
      liquidation_hunt: 0.60  # 猎杀流动性：需方向配合，单独不够
      # POSITIONING — 持仓极端（合并 retail_extreme + oi_divergence + oi_surge）
      positioning_extreme: 0.50  # LS/费率/OI 三者任一极端：反向信号，降权
      # CROSS-SYMBOL — 跨币种联动
      leader_sync: 0.40       # 龙头带动：相关性噪声大，仅作辅助叠加
```

- [ ] **Step 2: Replace thresholds block**

Replace lines 190-197 (the `thresholds:` block) with:

```yaml
    thresholds:
      # 脉冲间 CVD 比率变化幅度。超过此值触发 cvd_divergence 检测。
      cvd_divergence_tick_delta: 0.25
      # CVD 极端阈值（替代原 taker_imbalance）。|cvd| 超过此值直接触发 cvd_momentum
      # 静态路径。XAUT 等低流动性资产可提高此值减少噪声。
      cvd_extreme_threshold: 0.18
      # large_trade: avg_trade_size Z-score 超过此值触发
      large_trade_zscore: 2.0
      # large_trade: 滚动窗口脉冲数（每个 pulse ≈ 2min）
      large_trade_lookback: 30
```

- [ ] **Step 3: Commit**

```bash
git add config/global_config.yaml
git commit -m "config: update signal_stack for 9-signal architecture

Remove weights: taker_imbalance, poc_gravity, trend_pullback, retail_extreme,
oi_divergence, oi_surge. Add weights: large_trade (0.55), positioning_extreme (0.50).
Reduce cvd_absorption 0.65→0.50. Rename taker_imbalance threshold to
cvd_extreme_threshold. Add large_trade_zscore and large_trade_lookback."
```

---

### Task 3: Update config/symbol_config.yaml XAUTUSDT overrides

**Files:**
- Modify: `config/symbol_config.yaml:38-43`

**Interfaces:**
- Consumed by: Task 4 (trigger.py reads per-symbol overrides via symbol_resolver)

- [ ] **Step 1: Rename taker_imbalance → cvd_extreme_threshold**

Replace the XAUTUSDT threshold overrides:

```yaml
      sniper:
        signal_stack:
          thresholds:
            # XAUT CVD 噪声高，提高门槛以减少误触发。
            cvd_divergence_tick_delta: 0.18
            cvd_extreme_threshold: 0.36
```

- [ ] **Step 2: Commit**

```bash
git add config/symbol_config.yaml
git commit -m "config: rename XAUT taker_imbalance override → cvd_extreme_threshold"
```

---

### Task 4: Rewrite trigger.py — detector registry, cvd_momentum, new detectors, remove old

**Files:**
- Modify: `src/sniper/trigger.py` (multiple sections — see steps below)

**Interfaces:**
- Consumes: `sentiment_signals.avg_trade_size` (from Task 1), `signal_stack.weights` + `thresholds` (from Task 2-3)
- Produces: `SignalCard` with sub_types `cvd_momentum`, `large_trade`, `positioning_extreme`
- Removes: `SignalCard` with sub_types `taker_imbalance`, `poc_gravity`, `trend_pullback`, `retail_extreme`, `oi_divergence`, `oi_surge`

- [ ] **Step 1: Add SIZE to SignalCategory enum and deque import**

At line 27-32, add `SIZE`:

```python
class SignalCategory(str, Enum):
    FLOW = "FLOW"
    SIZE = "SIZE"           # NEW — large-trade / institutional activity
    ENERGY = "ENERGY"
    STRUCTURAL = "STRUCTURAL"
    POSITIONING = "POSITIONING"
    CROSS_SYMBOL = "CROSS_SYMBOL"
```

At line 12 (imports), add:

```python
from collections import deque
```

- [ ] **Step 2: Add rolling stats storage in __init__**

In `SniperTrigger.__init__`, after `self.state_locks` (line 258), add:

```python
        # Rolling stats for large_trade detector (per-symbol deque of avg_trade_size)
        large_trade_cfg = self.sniper_cfg.get('signal_stack', {}).get('thresholds', {})
        self._trade_size_window = deque(maxlen=large_trade_cfg.get('large_trade_lookback', 30))
```

- [ ] **Step 3: Replace _signal_detectors registry**

Replace lines 263-282 with:

```python
        # Ordered signal detection registry
        self._signal_detectors = [
            # FLOW (fastest, most direct)
            self._detect_cvd_momentum,
            self._detect_cvd_divergence,
            self._detect_cvd_absorption,
            # SIZE
            self._detect_large_trade,
            # ENERGY
            self._detect_volatility_surge,
            self._detect_squeeze,
            # STRUCTURAL
            self._detect_boundary_test,
            self._detect_liquidation_hunt,
            # POSITIONING
            self._detect_positioning_extreme,
        ]
```

- [ ] **Step 4: Rewrite _detect_cvd_momentum**

Replace lines 693-722 (the old `_detect_cvd_momentum`) with the two-path version:

```python
    def _detect_cvd_momentum(self, curr: Dict[str, Any],
                              prev: Optional[Dict[str, Any]],
                              now: datetime) -> Optional[SignalCard]:
        cvd = curr['sentiment_signals']['cvd_intensity_ratio']
        base_threshold = self.regime_cfg['micro_sentiment']['cvd_intensity_threshold']
        extreme_threshold = self.sniper_cfg.get('signal_stack', {}).get(
            'thresholds', {}).get('cvd_extreme_threshold', 0.18)

        # Path A (growth): CVD above base threshold AND still growing
        path_a = False
        if abs(cvd) > base_threshold:
            if prev:
                prev_cvd = prev['sentiment_signals']['cvd_intensity_ratio']
                growth_ratio = self.sniper_cfg['probes']['cvd_growth_significance_ratio']
                if abs(cvd) >= abs(prev_cvd) * growth_ratio:
                    path_a = True
            else:
                path_a = True  # first pulse, no growth check possible

        # Path B (extreme static): CVD above the higher extreme threshold
        path_b = abs(cvd) > extreme_threshold

        if not (path_a or path_b):
            return None

        direction = Direction.BULLISH if cvd > 0 else Direction.BEARISH
        if path_b:
            strength = min((abs(cvd) - extreme_threshold) / extreme_threshold, 1.0)
        else:
            strength = min(abs(cvd) / (base_threshold * 3), 1.0)
        confidence = self.signal_weights.get('cvd_momentum', 0.65)

        trigger_path = 'extreme' if path_b else 'growth'
        return SignalCard(
            signal_id=self._make_id('cvd_momentum', now),
            category=SignalCategory.FLOW,
            sub_type='cvd_momentum',
            direction=direction,
            strength=strength,
            confidence=confidence,
            urgency=0.5,
            timestamp=now,
            decay_half_life_minutes=15.0,
            evidence={'cvd_intensity': cvd, 'threshold': base_threshold,
                      'trigger_path': trigger_path},
        )
```

- [ ] **Step 5: Add _detect_large_trade (new detector)**

Insert after `_detect_cvd_absorption` (before the ENERGY section, around line 797):

```python
    # ── SIZE: Large Trade / Institutional Activity (#4) ─────────────────

    def _detect_large_trade(self, curr: Dict[str, Any],
                             prev: Optional[Dict[str, Any]],
                             now: datetime) -> Optional[SignalCard]:
        avg_size = curr['sentiment_signals'].get('avg_trade_size', 0.0)
        if avg_size <= 0:
            return None

        thresholds = self.sniper_cfg.get('signal_stack', {}).get('thresholds', {})
        zscore_threshold = thresholds.get('large_trade_zscore', 2.0)

        # Record current value in rolling window
        self._trade_size_window.append(avg_size)
        if len(self._trade_size_window) < 5:
            return None  # need minimum history for meaningful Z-score

        mean = sum(self._trade_size_window) / len(self._trade_size_window)
        variance = sum((x - mean) ** 2 for x in self._trade_size_window) / len(self._trade_size_window)
        std = variance ** 0.5
        if std <= 1e-9:
            return None

        z_score = (avg_size - mean) / std
        if z_score <= zscore_threshold:
            return None

        cvd = curr['sentiment_signals']['cvd_intensity_ratio']
        if abs(cvd) <= 0.01:
            direction = Direction.NEUTRAL
        else:
            direction = Direction.BULLISH if cvd > 0 else Direction.BEARISH

        strength = min(z_score / (zscore_threshold * 2), 1.0)
        confidence = self.signal_weights.get('large_trade', 0.55)

        return SignalCard(
            signal_id=self._make_id('large_trade', now),
            category=SignalCategory.SIZE,
            sub_type='large_trade',
            direction=direction,
            strength=strength,
            confidence=confidence,
            urgency=0.7,
            timestamp=now,
            decay_half_life_minutes=10.0,
            evidence={'avg_trade_size': avg_size, 'z_score': z_score,
                      'trade_count': curr['sentiment_signals'].get('trade_count', 0)},
        )
```

- [ ] **Step 6: Add _detect_positioning_extreme (merge of retail_extreme + oi_divergence + oi_surge)**

Insert at the end of the POSITIONING section (after where `_detect_oi_surge` was, around line 1236):

```python
    # ── POSITIONING: Unified Positioning Extreme (#9) ───────────────────

    def _detect_positioning_extreme(self, curr: Dict[str, Any],
                                     prev: Optional[Dict[str, Any]],
                                     now: datetime) -> Optional[SignalCard]:
        """Unifies retail_extreme, oi_divergence, and oi_surge into one detector.
        Three independent trigger paths — strongest one wins if multiple fire."""

        best_direction = None
        best_strength = 0.0
        best_evidence: Dict[str, Any] = {}

        # Path 1: LS extreme (retail positioning)
        ls = curr['sentiment_signals'].get('ls_ratio_micro', 1.0)
        cfg = self.regime_cfg['imbalance']
        if ls > cfg['long_short_imbalance_ratio']:
            strength = min((ls - 1.0) / (cfg['long_short_imbalance_ratio'] * 2), 1.0)
            if strength > best_strength:
                best_direction = Direction.BEARISH
                best_strength = strength
                best_evidence = {'trigger': 'ls_long', 'ls_ratio': ls}
        elif ls < cfg['short_heavy_imbalance_ratio']:
            strength = min((1.0 - ls) / ((1.0 - cfg['short_heavy_imbalance_ratio']) * 2), 1.0)
            if strength > best_strength:
                best_direction = Direction.BULLISH
                best_strength = strength
                best_evidence = {'trigger': 'ls_short', 'ls_ratio': ls}

        # Path 2: Funding extreme
        funding = curr['sentiment_signals'].get('funding_rate', 0.0)
        funding_threshold = self.regime_cfg['micro_sentiment']['funding_extreme_threshold']
        if abs(funding) > funding_threshold:
            f_direction = Direction.BEARISH if funding > 0 else Direction.BULLISH
            f_strength = min(abs(funding) / (funding_threshold * 4), 1.0)
            if f_strength > best_strength:
                best_direction = f_direction
                best_strength = f_strength
                best_evidence = {'trigger': 'funding', 'funding_rate': funding}

        # Path 3: OI divergence (OI and price move opposite)
        if prev:
            oi_delta = curr['sentiment_signals'].get('oi_delta_micro', 0.0)
            price_delta = (curr['price_dynamics']['current_price'] -
                           prev['price_dynamics']['current_price'])
            if abs(oi_delta) > 1e-10 and abs(price_delta) > 1e-10 and abs(oi_delta) > 0.01:
                if (oi_delta > 0 and price_delta < 0) or (oi_delta < 0 and price_delta > 0):
                    oi_dir = Direction.BEARISH if price_delta > 0 else Direction.BULLISH
                    oi_strength = min(abs(oi_delta) / 0.03, 1.0)
                    if oi_strength > best_strength:
                        best_direction = oi_dir
                        best_strength = oi_strength
                        best_evidence = {'trigger': 'oi_divergence', 'oi_delta': oi_delta,
                                         'price_delta': price_delta}

        # Path 4: OI surge (OI and price move same direction)
        if prev and best_direction is None:
            oi_delta = curr['sentiment_signals'].get('oi_delta_micro', 0.0)
            price_delta = (curr['price_dynamics']['current_price'] -
                           prev['price_dynamics']['current_price'])
            if abs(oi_delta) > 0.02:
                if (oi_delta > 0 and price_delta > 0) or (oi_delta < 0 and price_delta < 0):
                    oi_dir = Direction.BULLISH if price_delta > 0 else Direction.BEARISH
                    oi_strength = min((abs(oi_delta) - 0.02) / 0.04, 1.0)
                    if oi_strength > best_strength:
                        best_direction = oi_dir
                        best_strength = oi_strength
                        best_evidence = {'trigger': 'oi_surge', 'oi_delta': oi_delta,
                                         'price_delta': price_delta}

        if best_direction is None:
            return None

        if not self._check_state_lock("POSITIONING_EXTREME", now):
            return None

        confidence = self.signal_weights.get('positioning_extreme', 0.50)

        return SignalCard(
            signal_id=self._make_id('positioning_extreme', now),
            category=SignalCategory.POSITIONING,
            sub_type='positioning_extreme',
            direction=best_direction,
            strength=best_strength,
            confidence=confidence,
            urgency=0.3,
            timestamp=now,
            decay_half_life_minutes=60.0,
            evidence=best_evidence,
        )
```

- [ ] **Step 7: Delete old detector methods**

Remove these six methods entirely:
- `_detect_taker_imbalance` (lines 801-828)
- `_detect_poc_gravity` (lines 956-990)
- `_detect_trend_pullback` (lines 1059-1112)
- `_detect_retail_extreme` (lines 1116-1164)
- `_detect_oi_divergence` (lines 1168-1202)
- `_detect_oi_surge` (lines 1206-1235)

Note: The old `_detect_cvd_momentum` was already replaced in Step 4.

- [ ] **Step 8: Commit — detector changes**

```bash
git add src/sniper/trigger.py
git commit -m "refactor: 13→9 signal detectors — add large_trade, positioning_extreme, merge cvd_momentum

Add SIZE category to SignalCategory enum. Add rolling stats deque for large_trade.
Rewrite cvd_momentum with two-path logic (growth + extreme static).
Add _detect_large_trade using avg_trade_size Z-score from klines.trades.
Add _detect_positioning_extreme merging retail_extreme + oi_divergence + oi_surge.
Remove 6 detectors: taker_imbalance, poc_gravity, trend_pullback, retail_extreme,
oi_divergence, oi_surge."
```

---

### Task 5: Update trigger.py — thesis, evidence, risk caveats, entry suggestion, diagnostics

**Files:**
- Modify: `src/sniper/trigger.py:_suggest_thesis`, `_format_evidence`, `_build_risk_caveats`, `_build_entry_suggestion`, `_run_pre_ai_gate`, `_log_signal_diagnostics`

**Interfaces:**
- Produces: `situation_brief` with updated signal vocabulary
- Consumes: SignalCards from Task 4

- [ ] **Step 1: Update _suggest_thesis (lines 508-564)**

Replace the entire `_suggest_thesis` method's `theses` dict:

```python
    def _suggest_thesis(self, sub_type: str, direction: Direction) -> str:
        theses = {
            'cvd_momentum': (
                "Bearish momentum building — seek short on pullback to nearest HVN"
                if direction == Direction.BEARISH else
                "Bullish momentum building — seek long on dip to nearest HVN"
            ),
            'cvd_divergence': (
                "Distribution detected — smart money selling into strength, prepare short"
                if direction == Direction.BEARISH else
                "Accumulation detected — smart money buying into weakness, prepare long"
            ),
            'cvd_absorption': (
                "Selling absorption suspected — large player may be accumulating shorts"
                if direction == Direction.BEARISH else
                "Buying absorption suspected — large player may be accumulating longs"
            ),
            'large_trade': (
                "Institutional selling detected — large avg trade size with bearish flow"
                if direction == Direction.BEARISH else
                "Institutional buying detected — large avg trade size with bullish flow"
            ),
            'volatility_surge': (
                "Breakout energy with bearish flow — momentum short entry"
                if direction == Direction.BEARISH else
                "Breakout energy with bullish flow — momentum long entry"
            ),
            'squeeze': "Coiling spring — prepare for violent expansion, direction TBD on breakout",
            'boundary_test': (
                "Testing resistance — if rejection, fade short; if breakout with volume, follow"
                if direction == Direction.BULLISH else
                "Testing support — if rejection, fade long; if breakdown with volume, follow"
            ),
            'liquidation_hunt': "Liquidity sweep in progress — enter after cluster is cleared",
            'positioning_extreme': (
                "Retail overcrowded — squeeze fuel for downside cascade"
                if direction == Direction.BEARISH else
                "Retail overcrowded short — squeeze fuel for upside cascade"
            ),
        }
        return theses.get(sub_type, f"Signal detected — evaluate against market structure")
```

- [ ] **Step 2: Update _format_evidence (lines 566-601)**

Replace the entire `_format_evidence` method:

```python
    def _format_evidence(self, s: SignalCard) -> str:
        """One-line summary of signal evidence for the pre-brief."""
        ev = s.evidence
        if s.sub_type == 'cvd_momentum':
            path = ev.get('trigger_path', 'growth')
            return f"CVD intensity {ev.get('cvd_intensity', 0.0):.3f} (path={path})"
        if s.sub_type == 'cvd_divergence':
            return f"CVD delta {ev.get('cvd_delta', 0.0):.3f} vs price delta {ev.get('price_delta', 0.0):.1f}"
        if s.sub_type == 'cvd_absorption':
            return f"CVD {ev.get('cvd_intensity', 0.0):.3f} with flat price (delta {ev.get('price_delta', 0.0):.1f})"
        if s.sub_type == 'large_trade':
            return f"Avg trade size {ev.get('avg_trade_size', 0.0):.3f} BTC (z={ev.get('z_score', 0.0):.1f})"
        if s.sub_type == 'volatility_surge':
            return f"VII={ev.get('vii', 0.0):.2f}, VPR={ev.get('vpr', 0.0):.2f}"
        if s.sub_type == 'squeeze':
            return f"Squeeze factor {ev.get('squeeze_factor', 0.0):.2f}"
        if s.sub_type == 'boundary_test':
            return f"Distance to {ev.get('boundary', '?')}: {ev.get('dist_atr', 0.0):.2f} ATR"
        if s.sub_type == 'liquidation_hunt':
            return f"Cluster at {ev.get('cluster_price', 0.0):.1f}, distance: {ev.get('dist_atr', 0.0):.2f} ATR"
        if s.sub_type == 'positioning_extreme':
            trigger = ev.get('trigger', '?')
            if trigger == 'ls_long':
                return f"LS ratio {ev.get('ls_ratio', 0.0):.2f} — retail heavily long"
            elif trigger == 'ls_short':
                return f"LS ratio {ev.get('ls_ratio', 0.0):.2f} — retail heavily short"
            elif trigger == 'funding':
                return f"Funding rate {ev.get('funding_rate', 0.0):.5f} — extreme"
            elif trigger == 'oi_divergence':
                return f"OI delta {ev.get('oi_delta', 0.0):.3f} vs price delta {ev.get('price_delta', 0.0):.1f}"
            elif trigger == 'oi_surge':
                return f"OI delta {ev.get('oi_delta', 0.0):.3f} aligned with price delta {ev.get('price_delta', 0.0):.1f}"
        return str(ev)[:120]
```

- [ ] **Step 3: Update _build_risk_caveats (lines 603-632)**

Replace references to old sub_types:

```python
    def _build_risk_caveats(self, signals: List[SignalCard],
                            direction: Direction, regime: str) -> List[str]:
        caveats = []
        sub_types = {s.sub_type for s in signals}

        if 'positioning_extreme' in sub_types:
            caveats.append(
                "Positioning extreme can persist for hours — do not force entry without structural confirmation"
            )
        if 'cvd_momentum' in sub_types and 'cvd_absorption' not in sub_types:
            caveats.append(
                "CVD momentum is strong but watch for absorption — extreme CVD without price movement = reversal risk"
            )
        if regime == 'chaos':
            caveats.append(
                "CHAOS regime active — use hit-and-run strategy, compress TP to first structural boundary"
            )
        if regime == 'squeeze':
            caveats.append(
                "Squeeze active — expect violent breakout, use wider stop or wait for direction confirmation"
            )
        if 'cvd_divergence' in sub_types and direction == Direction.BEARISH:
            caveats.append(
                "Distribution divergence — smart money may be selling into strength, size conservatively"
            )
        return caveats
```

- [ ] **Step 4: Update _build_entry_suggestion (lines 634-661)**

Remove `trend_pullback` reference (lines 642-644), keep rest:

```python
    def _build_entry_suggestion(self, signals: List[SignalCard],
                                 direction: Direction, regime: str) -> Dict[str, Any]:
        max_dist = self.sniper_cfg.get('signal_stack', {}).get('gate', {}).get(
            'max_price_to_structure_atr', 1.0)
        suggestion = {
            "max_distance_atr": max_dist,
        }

        if any(s.sub_type == 'cvd_divergence' for s in signals):
            suggestion["type"] = "divergence_fade"
            suggestion["target_area"] = "proximal structural boundary"
        elif any(s.sub_type == 'squeeze' for s in signals):
            suggestion["type"] = "squeeze_breakout"
            suggestion["target_area"] = "beyond VAH/VAL on confirmed breakout direction"
        elif any(s.sub_type == 'large_trade' for s in signals):
            suggestion["type"] = "institutional_follow"
            suggestion["target_area"] = "nearest HVN in flow direction"
        elif regime == 'chaos':
            suggestion["type"] = "hit_and_run"
            suggestion["target_area"] = "nearest liquidation cluster or VAH/VAL boundary"
        elif direction == Direction.BEARISH:
            suggestion["type"] = "shallow_pullback_dle"
            suggestion["target_area"] = "nearest HVN above current price"
        else:
            suggestion["type"] = "shallow_dip_dle"
            suggestion["target_area"] = "nearest HVN below current price"

        return suggestion
```

- [ ] **Step 5: Update _run_pre_ai_gate chaos survival check (lines 456-465)**

Update signal name references in the chaos survival check:

```python
        # 3. Chaos survival
        if checks.get('chaos_survival', True) and regime == 'chaos':
            # Directional momentum signals in chaos are prohibited
            momentum_signals = [s for s in signals
                              if s.sub_type in ('cvd_momentum', 'volatility_surge')
                              and s.direction == direction]
            if momentum_signals and not any(
                s.sub_type in ('squeeze', 'cvd_absorption', 'large_trade') for s in signals
            ):
                return "FAIL", "CHAOS_SURVIVAL: directional momentum prohibited in chaos regime"
```

(Adds `large_trade` to the balancing signals list.)

- [ ] **Step 6: Update _log_signal_diagnostics (lines 1313-1404)**

Replace the entire method with the 9-signal version:

```python
    def _log_signal_diagnostics(self, metrics: Dict[str, Any],
                                 fresh_signals: List[SignalCard]) -> None:
        """Log a compact per-pulse summary of key decision metrics for all 9
        signal detectors."""
        fired = {s.sub_type: s for s in fresh_signals}
        parts: List[str] = []

        # ── FLOW category ──
        cvd = metrics['sentiment_signals']['cvd_intensity_ratio']
        cvd_thresh = self.regime_cfg['micro_sentiment']['cvd_intensity_threshold']
        parts.append(f"cvd={cvd:+.3f}")

        s = fired.get('cvd_momentum')
        extreme_thresh = self.sniper_cfg.get('signal_stack', {}).get(
            'thresholds', {}).get('cvd_extreme_threshold', 0.18)
        parts.append(f"cvd_momentum={'F:'+str(round(s.strength,2)) if s else f'R:|cvd|<={cvd_thresh}&<={extreme_thresh}'}")

        s = fired.get('cvd_divergence')
        parts.append(f"cvd_divergence={'F:'+str(round(s.strength,2)) if s else 'R:no-prev/div-low'}")
        s = fired.get('cvd_absorption')
        parts.append(f"cvd_absorption={'F:'+str(round(s.strength,2)) if s else f'R:|cvd|<=extreme'}")

        # ── SIZE category ──
        avg_size = metrics['sentiment_signals'].get('avg_trade_size', 0.0)
        trade_n = metrics['sentiment_signals'].get('trade_count', 0)
        z_thresh = self.sniper_cfg.get('signal_stack', {}).get('thresholds', {}).get('large_trade_zscore', 2.0)
        s = fired.get('large_trade')
        parts.append(f"trade_sz={avg_size:.4f}/n={trade_n} | large_trade={'F:'+str(round(s.strength,2)) if s else f'R:z<={z_thresh}'}")

        # ── ENERGY category ──
        vii = metrics['price_dynamics']['volatility_intensity_index']
        vpr = metrics['market_regime']['volume_participation_ratio']
        parts.append(f"vii={vii:.2f},vpr={vpr:.2f}")

        s = fired.get('volatility_surge')
        vol_base = self.regime_cfg['volatility']['volatility_baseline_ratio']
        vol_thresh = self.regime_cfg['volume']['volume_participation_threshold']
        parts.append(f"vol_surge={'F:'+str(round(s.strength,2)) if s else f'R:vii<={vol_base}|vpr<={vol_thresh}'}")

        sf = metrics['market_regime']['squeeze_factor']
        sq_thresh = (self.regime_cfg['volatility']['squeeze_threshold'] *
                     self.sniper_cfg['probes']['squeeze_trigger_multiplier'])
        s = fired.get('squeeze')
        parts.append(f"squeeze={'F:'+str(round(s.strength,2)) if s else f'R:sf={sf:.3f}>={sq_thresh:.3f}'}")

        # ── STRUCTURAL category ──
        price = metrics['price_dynamics']['current_price']
        atr = metrics['price_dynamics'].get('atr_macro', 0)
        topo = metrics['volume_profile']
        parts.append(f"price={price:.1f},atr={atr:.2f}")

        s = fired.get('boundary_test')
        if atr > 0:
            dist_vh = abs(price - topo['vah']) / atr
            dist_val = abs(price - topo['val']) / atr
            prox_thresh = self.sniper_cfg['proximity']['vah_val_atr']
            parts.append(f"boundary_test={'F:'+str(round(s.strength,2)) if s else f'R:dist_vh={dist_vh:.1f},dist_val={dist_val:.1f}>={prox_thresh}'}")
        else:
            parts.append("boundary_test=R:atr=0")

        s = fired.get('liquidation_hunt')
        parts.append(f"liq_hunt={'F:'+str(round(s.strength,2)) if s else 'R:no-cluster-in-range'}")

        # ── POSITIONING category ──
        ls = metrics['sentiment_signals'].get('ls_ratio_micro', 1.0)
        funding = metrics['sentiment_signals'].get('funding_rate', 0.0)
        oi_delta = metrics['sentiment_signals'].get('oi_delta_micro', 0.0)
        parts.append(f"ls={ls:.2f},fund={funding:.4f},oi_d={oi_delta:.4f}")

        s = fired.get('positioning_extreme')
        ls_imb = self.regime_cfg['imbalance']['long_short_imbalance_ratio']
        ls_short = self.regime_cfg['imbalance']['short_heavy_imbalance_ratio']
        fund_ext = self.regime_cfg['micro_sentiment']['funding_extreme_threshold']
        parts.append(f"pos_ext={'F:'+str(round(s.strength,2)) if s else f'R:ls<={ls_imb}&ls>={ls_short}&|fund|<={fund_ext}&oi<0.01'}")

        logger.info("[%s] SIGNAL DIAG | %s", self.symbol, " | ".join(parts))
```

- [ ] **Step 7: Update module docstring (line 7)**

Change "14 signal types" to "9 signal types":

```python
    engine. 9 signal types across 5 categories are detected per pulse, scored on
```

- [ ] **Step 8: Commit**

```bash
git add src/sniper/trigger.py
git commit -m "refactor: update thesis, evidence, caveats, entry, diagnostics for 9-signal stack

Update _suggest_thesis: add large_trade and positioning_extreme, remove old signals.
Update _format_evidence: add new signal evidence formatters.
Update _build_risk_caveats: replace retail_extreme→positioning_extreme, remove
trend_pullback reference.
Update _build_entry_suggestion: add large_trade/institutional_follow entry type,
remove trend_pullback reference.
Update _run_pre_ai_gate chaos survival: add large_trade to balancing signals.
Rewrite _log_signal_diagnostics: 9-signal layout with SIZE category, merged
POSITIONING line, removed poc_gravity/trend_pullback/taker_imb lines."
```

---

### Task 6: Run existing tests and verify no regressions

**Files:**
- None (verification only)

- [ ] **Step 1: Run the test suite**

```bash
python -m pytest tests/ -x -q 2>&1 | tail -30
```

Expected: All tests pass. If any test references removed signal names, update the test to use the new names.

- [ ] **Step 2: Verify trigger.py imports correctly**

```bash
python -c "from src.sniper.trigger import SniperTrigger, SignalCategory; print('SIZE' in SignalCategory.__members__); t = SniperTrigger(symbol='BTCUSDT'); print(f'detectors={len(t._signal_detectors)}'); print([d.__name__ for d in t._signal_detectors])"
```

Expected output:
```
True
detectors=9
['_detect_cvd_momentum', '_detect_cvd_divergence', '_detect_cvd_absorption', '_detect_large_trade', '_detect_volatility_surge', '_detect_squeeze', '_detect_boundary_test', '_detect_liquidation_hunt', '_detect_positioning_extreme']
```

- [ ] **Step 3: Commit (if any test fixes were needed)**

```bash
git add tests/
git commit -m "test: update tests for 9-signal vocabulary"
```

---

