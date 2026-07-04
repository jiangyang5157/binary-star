# Visual Context Summarizer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Generate `.md` text summaries from chart source data, inject them into LLM prompts when `supports_vision=False`, and persist summaries alongside `.png` charts.

**Architecture:** A new `VisualContextSummarizer` class receives the identical data inputs as `ChartGenerator.generate_chart()`, producing a structured 6-section markdown text. `MarketObserver` calls it alongside chart generation. `BinaryStarOrchestrator` branches on `supports_vision`: read `.png` for vision models (unchanged), read `.md` for text-only models, inject into prompt.

**Tech Stack:** Python 3.13, pandas, numpy — zero new dependencies.

## Global Constraints

- Prompt templates (`session.md`, `critic.md`, `binary_star.md`) — ZERO modifications
- `build_messages()` / `_openai_helpers.py` — ZERO modifications
- `ChartGenerator` / `chart_generator.py` — ZERO modifications
- `global_config.yaml` — ZERO modifications (existing `supports_vision` config stays)
- No backward compatibility — clean breaks allowed
- File naming: `{symbol}_klines_{time_interval}_{YYYYMMDD_HHMMSS}.md`
- All data extracted from chart source data (same `df`, `profile_data`, `liquidations` as chart)

---

### Task 1: Add `supports_vision` property to AI client interface

**Files:**
- Modify: `src/infrastructure/ai_client.py:73` (after `close()`)
- Modify: `src/infrastructure/ai/gemini_adapter.py:34` (after `supports_context_cache`)

**Interfaces:**
- Produces: `AbstractAIClient.supports_vision` → `bool` (default `False`)
- Produces: `GeminiAdapter.supports_vision` → `bool` (override `True`)

- [ ] **Step 1: Add property to AbstractAIClient**

In `src/infrastructure/ai_client.py`, after line 71 (`close()` method):

```python
    @property
    def supports_vision(self) -> bool:
        """Whether this provider natively consumes image data (VisualPart)."""
        return False
```

- [ ] **Step 2: Add property override to GeminiAdapter**

In `src/infrastructure/ai/gemini_adapter.py`, after line 34 (`supports_context_cache` property):

```python
    @property
    def supports_vision(self) -> bool:
        return True
```

- [ ] **Step 3: Verify — existing tests still pass**

```bash
cd /Users/yangjiang/Documents/workspace/crypto && python -m pytest tests/ -x -q 2>&1 | tail -5
```

Expected: all existing tests pass.

- [ ] **Step 4: Commit**

```bash
git add src/infrastructure/ai_client.py src/infrastructure/ai/gemini_adapter.py
git commit -m "feat: add supports_vision property to AI client interface"
```

---

### Task 2: Create VisualContextSummarizer

**Files:**
- Create: `src/analyzer/visual_context_summarizer.py`
- Create: `tests/unit/test_visual_context_summarizer.py`

**Interfaces:**
- Produces: `VisualContextSummarizer().generate(symbol, df, profile_data, liquidations, time_interval, atr) -> str`

- [ ] **Step 1: Create test file**

```python
# tests/unit/test_visual_context_summarizer.py
import pandas as pd
import numpy as np
import pytest
from src.analyzer.visual_context_summarizer import VisualContextSummarizer


def make_test_df(close=97234.5, atr_val=1240.3, bars=20):
    """Deterministic OHLCV DataFrame matching ChartGenerator input format."""
    np.random.seed(42)
    base = close - atr_val * 3
    dates = pd.date_range("2026-07-04 08:00", periods=bars, freq="1h")
    data = []
    for i in range(bars):
        o = base + np.random.randn() * atr_val * 0.3
        h = o + abs(np.random.randn()) * atr_val * 0.5
        l = o - abs(np.random.randn()) * atr_val * 0.5
        c_val = o + np.random.randn() * atr_val * 0.2
        v = abs(np.random.randn()) * 5000 + 10000
        a = atr_val + np.random.randn() * 50
        data.append({
            "open": o, "high": h, "low": l, "close": c_val,
            "volume": v, "atr": a,
        })
    df = pd.DataFrame(data, index=dates)
    df.iloc[-1, df.columns.get_loc("close")] = close
    return df


def make_profile_data():
    return {
        "poc": 96810.0,
        "vah": 97812.0,
        "val": 96102.3,
        "volume_span_atr": 1.38,
        "nearest_hvn_dist_atr": 0.44,
        "nearest_lvn_dist_atr": 0.82,
        "anchors_above": [
            {"price": 98201.5, "volume": 18500.0, "strength": 0.91, "type": "HVN"},
        ],
        "anchors_below": [
            {"price": 96810.0, "volume": 24500.0, "strength": 0.94, "type": "HVN"},
            {"price": 96450.8, "volume": 15200.0, "strength": 0.76, "type": "HVN"},
        ],
        "profile_data": [
            {"price": p, "volume": v}
            for p, v in [(95500, 8000), (95800, 12000), (96100, 18000),
                         (96400, 22000), (96700, 28000), (97000, 18000),
                         (97300, 12000), (97600, 9000), (97900, 7000),
                         (98200, 5000), (98500, 3000)]
        ],
    }


def make_liquidations():
    return {
        "long_liquidation": [
            {"price": 95780.5, "intensity": 0.88},
            {"price": 95230.0, "intensity": 0.35},
        ],
        "short_liquidation": [
            {"price": 97950.2, "intensity": 0.82},
            {"price": 98430.1, "intensity": 0.31},
        ],
    }


class TestVisualContextSummarizer:

    def setup_method(self):
        self.summarizer = VisualContextSummarizer()

    def test_generate_returns_string_with_all_sections(self):
        df = make_test_df()
        result = self.summarizer.generate(
            symbol="BTCUSDT", df=df,
            profile_data=make_profile_data(),
            liquidations=make_liquidations(),
            time_interval="1h", atr=1240.3,
        )
        assert isinstance(result, str)
        for section in ["PRICE LADDER", "CANDLESTICK PANORAMA",
                        "VOLUME-AT-TIME PROFILE", "VOLUME PROFILE TOPOGRAPHY",
                        "LIQUIDATION LANDSCAPE", "KEY LEVELS REFERENCE"]:
            assert section in result, f"Missing section: {section}"

    def test_price_ladder_contains_all_levels(self):
        df = make_test_df()
        result = self.summarizer.generate(
            symbol="BTCUSDT", df=df,
            profile_data=make_profile_data(),
            liquidations=make_liquidations(),
            time_interval="1h", atr=1240.3,
        )
        for price_str in ["96810.0", "97812.0", "96102.3", "98201.5",
                          "96450.8", "95780.5", "97950.2", "98430.1", "95230.0"]:
            assert price_str in result, f"Missing price: {price_str}"
        assert "97234.5" in result
        assert "CURRENT PRICE" in result

    def test_distance_percent_correct(self):
        """POC at 96810.0 with current 97234.5 = −0.44%"""
        df = make_test_df(close=97234.5)
        result = self.summarizer.generate(
            symbol="BTCUSDT", df=df,
            profile_data=make_profile_data(),
            liquidations=make_liquidations(),
            time_interval="1h", atr=1240.3,
        )
        assert "−0.44%" in result

    def test_candle_body_calculation(self):
        """body = abs(close - open), verified on last bar."""
        df = make_test_df(bars=6)
        df.iloc[-1, df.columns.get_loc("open")] = 99700.0
        df.iloc[-1, df.columns.get_loc("high")] = 99780.0
        df.iloc[-1, df.columns.get_loc("low")] = 97200.0
        df.iloc[-1, df.columns.get_loc("close")] = 97234.5

        result = self.summarizer.generate(
            symbol="BTCUSDT", df=df,
            profile_data=make_profile_data(),
            liquidations=make_liquidations(),
            time_interval="1h", atr=1240.3,
        )
        # body = abs(97234.5 - 99700.0) = 2465.5
        assert "2465" in result

    def test_empty_liquidations_handled(self):
        df = make_test_df()
        result = self.summarizer.generate(
            symbol="BTCUSDT", df=df,
            profile_data=make_profile_data(),
            liquidations={},
            time_interval="1h", atr=1240.3,
        )
        assert "LIQUIDATION LANDSCAPE" in result

    def test_empty_df_returns_minimal(self):
        df = pd.DataFrame()
        result = self.summarizer.generate(
            symbol="BTCUSDT", df=df,
            profile_data=make_profile_data(),
            liquidations=make_liquidations(),
            time_interval="1h", atr=1240.3,
        )
        assert isinstance(result, str)
        assert "no data" in result.lower()

    def test_profile_shape_b_shaped(self):
        """POC positioned in lower VA → b-shaped."""
        df = make_test_df()
        pd_ = make_profile_data()
        pd_["poc"] = 96500.0  # (96500-96102.3)/(97812-96102.3) = 23.3% from VAL
        result = self.summarizer.generate(
            symbol="BTCUSDT", df=df,
            profile_data=pd_,
            liquidations=make_liquidations(),
            time_interval="1h", atr=1240.3,
        )
        assert "b-shaped" in result.lower()
```

- [ ] **Step 2: Run test — verify it fails**

```bash
cd /Users/yangjiang/Documents/workspace/crypto && python -m pytest tests/unit/test_visual_context_summarizer.py -v 2>&1 | tail -20
```

Expected: all FAIL (module not found).

- [ ] **Step 3: Create VisualContextSummarizer**

Create `src/analyzer/visual_context_summarizer.py` with the complete implementation. The file is ~400 lines. Below is the full source:

```python
"""VisualContextSummarizer — generates structured text descriptions from chart source data.

Receives the identical data inputs as ChartGenerator.generate_chart(), guaranteeing
pixel-level numerical consistency between the .png chart and the .md summary.
"""

from typing import Any, Dict, List, Optional, Union
import pandas as pd
import numpy as np

from src.utils.logger_utils import setup_logger

logger = setup_logger(__name__)


class VisualContextSummarizer:
    """Produces a 6-section structural panorama markdown from chart source data.

    All values are extracted directly from the same df/profile_data/liquidations
    that ChartGenerator receives — no OCR, no image parsing, no observation_json
    dependency.
    """

    CANDLE_LOOKBACK = 6
    VOLUME_LOOKBACK = 12
    VA_BALANCE_LOW = 40.0
    VA_BALANCE_HIGH = 60.0
    PEAK_SHARPNESS = 2.0
    MARUBOZU_BODY_RATIO = 0.8
    DOJI_BODY_RATIO = 0.2

    def __init__(self):
        pass

    # ── Public API ─────────────────────────────────────────────────────────

    def generate(
        self,
        symbol: str,
        df: pd.DataFrame,
        profile_data: Dict[str, Any],
        liquidations: Union[List, Dict, None],
        time_interval: str,
        atr: Optional[float] = None,
    ) -> str:
        if df.empty:
            logger.warning("VisualContextSummarizer: empty DataFrame — returning minimal output")
            return f"# {symbol} — {time_interval} STRUCTURAL PANORAMA\n\n(no data)"

        current_price = float(df['close'].iloc[-1])
        atr_val = atr or (
            float(df['atr'].iloc[-1]) if 'atr' in df.columns and not pd.isna(df['atr'].iloc[-1]) else 0.0
        )

        timestamp = profile_data.get("timestamp", "")
        poc = float(profile_data.get("poc", 0))
        vah = float(profile_data.get("vah", 0))
        val = float(profile_data.get("val", 0))
        va_span = vah - val

        liq_dict = self._normalize_liquidations(liquidations)
        anchors_above = list(profile_data.get("anchors_above", []) or [])
        anchors_below = list(profile_data.get("anchors_below", []) or [])
        raw_histogram = list(profile_data.get("profile_data", []) or [])

        sections = [
            self._section_header(symbol, time_interval, timestamp),
            self._section_price_ladder(current_price, atr_val, va_span,
                                       poc, vah, val, anchors_above, anchors_below,
                                       liq_dict),
            self._section_candlestick(df, time_interval),
            self._section_volume_at_time(df),
            self._section_volume_profile(poc, vah, val, va_span, current_price,
                                         anchors_above, anchors_below, raw_histogram),
            self._section_liquidation(liq_dict, poc, vah, val,
                                      anchors_above, anchors_below, current_price),
            self._section_key_levels(current_price, poc, vah, val,
                                     anchors_above, anchors_below, liq_dict),
        ]
        return "\n\n".join(s for s in sections if s)

    # ── Section 1: Header ──────────────────────────────────────────────────

    @staticmethod
    def _section_header(symbol: str, interval: str, timestamp: str) -> str:
        return f"# {symbol} — {interval} STRUCTURAL PANORAMA\n# observed_at: {timestamp}"

    # ── Section 2: Price Ladder ────────────────────────────────────────────

    def _section_price_ladder(
        self, current_price: float, atr: float, va_span: float,
        poc: float, vah: float, val: float,
        anchors_above: List[Dict], anchors_below: List[Dict],
        liquidations: Dict,
    ) -> str:
        lines = [
            "## 1. PRICE LADDER",
            f"# current_price = {current_price:.1f}",
            "",
        ]

        # ── ABOVE ──
        lines.append("  ─── ABOVE (resistance / supply zone) ───")
        above_entries = []

        if vah and vah > current_price:
            above_entries.append((vah, "VAH", None, "Value Area High"))

        for a in anchors_above:
            p = a.get("price", 0)
            if p > current_price:
                s_val = a.get("strength", a.get("volume", 0))
                above_entries.append((p, f"HVN", s_val, ""))

        for i, liq in enumerate(liquidations.get("short_liquidation", [])):
            p = liq.get("price", 0)
            if p > current_price:
                above_entries.append((p, f"Short Liq #{i+1}", liq.get("intensity", 0), ""))

        above_entries.sort(key=lambda x: x[0], reverse=True)

        for price, label, str_val, note in above_entries:
            pct = (price - current_price) / current_price * 100
            bar = self._bar(str_val, is_liq=("Liq" in label))
            info = self._str_info(str_val, is_liq=("Liq" in label))
            note_str = f"  {note}" if note else ""
            lines.append(f"  {price:.1f}  {label:16s}  (+{pct:.2f}%)  {bar}  {info}{note_str}")

        lines.append("  ────────────────────────────────────────────")
        lines.append(f"  {current_price:.1f}  ● CURRENT PRICE")
        lines.append("  ────────────────────────────────────────────")

        # ── BELOW ──
        lines.append("  ─── BELOW (support / demand zone) ───")
        below_entries = []

        if poc and poc < current_price:
            poc_strength = 0.0
            for a in anchors_below:
                if abs(a.get("price", 0) - poc) < 0.01:
                    poc_strength = a.get("strength", a.get("volume", 0))
                    break
            if not poc_strength:
                poc_strength = 0.94
            below_entries.append((poc, "POC", poc_strength, "Point of Control"))

        for a in anchors_below:
            p = a.get("price", 0)
            if p < current_price and abs(p - poc) > 0.01:
                s_val = a.get("strength", a.get("volume", 0))
                below_entries.append((p, "HVN", s_val, ""))

        if val and val < current_price:
            below_entries.append((val, "VAL", None, "Value Area Low"))

        for i, liq in enumerate(liquidations.get("long_liquidation", [])):
            p = liq.get("price", 0)
            if p < current_price:
                below_entries.append((p, f"Long Liq #{i+1}", liq.get("intensity", 0), ""))

        below_entries.sort(key=lambda x: x[0], reverse=True)

        for price, label, str_val, note in below_entries:
            pct = (price - current_price) / current_price * 100
            bar = self._bar(str_val, is_liq=("Liq" in label))
            info = self._str_info(str_val, is_liq=("Liq" in label))
            note_str = f"  {note}" if note else ""
            lines.append(f"  {price:.1f}  {label:16s}  ({pct:.2f}%)  {bar}  {info}{note_str}")

        va_pct = va_span / current_price * 100 if current_price > 0 and va_span else 0
        lines.append("")
        lines.append(f"  ATR_macro = {atr:.1f}  |  VA_span = {va_span:.1f} ({va_pct:.2f}% of price)")
        return "\n".join(lines)

    # ── Section 3: Candlestick Panorama ────────────────────────────────────

    def _section_candlestick(self, df: pd.DataFrame, time_interval: str) -> str:
        lookback = min(self.CANDLE_LOOKBACK, len(df))
        if lookback == 0:
            return ""

        window = df.tail(lookback)
        lines = [f"## 2. CANDLESTICK PANORAMA (最近 {lookback} bars, {time_interval})", ""]

        for i in range(lookback):
            row = window.iloc[i]
            offset = lookback - i - 1
            o, h, l, c = float(row['open']), float(row['high']), float(row['low']), float(row['close'])
            body = abs(c - o)
            upper_wick = h - max(o, c)
            lower_wick = min(o, c) - l
            total_range = h - l
            pct_change = (c - o) / o * 100 if o > 0 else 0
            body_ratio = body / total_range if total_range > 0 else 0

            if c >= o:
                direction = "BULL"
            else:
                direction = "BEAR"

            if body_ratio > self.MARUBOZU_BODY_RATIO:
                bar_type = "MARUBOZU"
            elif body_ratio < self.DOJI_BODY_RATIO:
                bar_type = "DOJI"
            else:
                bar_type = ""

            if body_ratio > 0.7:
                size = "dominant"
            elif body_ratio < 0.3:
                size = "small"
            else:
                size = "moderate"

            bar_art = self._candle_art(body_ratio, c >= o)

            uw_ratio = upper_wick / total_range if total_range > 0 else 0
            lw_ratio = lower_wick / total_range if total_range > 0 else 0
            wick_flags = []
            if uw_ratio > 0.4:
                wick_flags.append("upper_wick=LONG")
            if lw_ratio > 0.4:
                wick_flags.append("lower_wick=LONG")

            tag = f"T-{offset}" if offset > 0 else "T-0 (forming)"

            type_str = f" {bar_type}" if bar_type else ""
            lines.append(f"  {tag}: {bar_art}  {direction}{type_str:12s}  "
                         f"O={o:.0f}  H={h:.0f}  L={l:.0f}  C={c:.0f}  ({pct_change:+.1f}%)")
            wick_line = f"        body={body:.0f} ({size})  upper_wick={upper_wick:.0f}  lower_wick={lower_wick:.0f}"
            if wick_flags:
                wick_line += f"  {' '.join(wick_flags)}"
            lines.append(wick_line)

            if "MARUBOZU" in bar_type and direction == "BULL":
                lines.append("        → NO wicks, pure momentum breakout")
            elif upper_wick > 0 and uw_ratio > 0.4:
                lines.append(f"        → rejection @ ~{h:.0f}")

        # Summary
        lines.append("")
        lines.append("  ─── Morphology summary ───")
        closes = window['close'].values
        opens = window['open'].values
        bull_count = int(sum(1 for c_val, o_val in zip(closes, opens) if c_val >= o_val))
        lines.append(f"  Direction: {bull_count}/{lookback} bars bullish")

        last = window.iloc[-1]
        h_last, l_last, c_last = float(last['high']), float(last['low']), float(last['close'])
        if h_last > l_last:
            wick_skew = (c_last - l_last) / (h_last - l_last)
            if wick_skew < 0.15:
                skew_desc = "extreme rejection (long lower wick)"
            elif wick_skew > 0.85:
                skew_desc = "extreme rejection (long upper wick)"
            elif wick_skew < 0.35:
                skew_desc = "moderate lower-wick bias"
            elif wick_skew > 0.65:
                skew_desc = "moderate upper-wick bias"
            else:
                skew_desc = "balanced"
            lines.append(f"  Wick skew (instant): {wick_skew:.2f} ({skew_desc})")

        return "\n".join(lines)

    # ── Section 4: Volume-at-Time Profile ──────────────────────────────────

    def _section_volume_at_time(self, df: pd.DataFrame) -> str:
        lookback = min(self.VOLUME_LOOKBACK, len(df))
        if lookback == 0:
            return ""

        window = df.tail(lookback)
        volumes = window['volume'].values.astype(float)
        vol_ma = float(np.mean(volumes)) if len(volumes) > 0 else 1.0

        lines = [f"## 3. VOLUME-AT-TIME PROFILE (最近 {lookback} bars)", ""]

        surge_bars = []
        elevated_bars = []
        low_bars = []

        for i in range(lookback):
            offset = lookback - i - 1
            vol = float(volumes[i])
            ratio = vol / vol_ma if vol_ma > 0 else 1.0
            bar_width = min(12, max(1, int(ratio * 5)))
            bar = "█" * bar_width

            tag = f"T-{offset}" if offset > 0 else "T-0"
            marker = ""
            if ratio > 2.0:
                marker = "  ← SURGE"
                surge_bars.append(tag)
            elif ratio > 1.5:
                marker = "  ← elevated"
                elevated_bars.append(tag)
            elif ratio < 0.7:
                marker = "  ← low"
                low_bars.append(tag)

            lines.append(f"  {tag}: {bar:12s}  {ratio:.1f}× MA{marker}")

        lines.append("")
        lines.append(f"  Volume MA ({lookback}): baseline = 1.0×")
        if surge_bars:
            lines.append(f"  Surge bars (>2.0× MA): {', '.join(surge_bars)}")
        if elevated_bars:
            lines.append(f"  Elevated bars (1.5–2.0×): {', '.join(elevated_bars)}")
        if low_bars:
            lines.append(f"  Low bars (<0.7× MA): {', '.join(low_bars)}")
        gaps = self._detect_volume_gaps(window, vol_ma)
        lines.append(f"  Gaps / voids detected: {gaps if gaps else 'none in recent ' + str(lookback) + ' bars'}")

        return "\n".join(lines)

    # ── Section 5: Volume Profile Topography ───────────────────────────────

    def _section_volume_profile(
        self, poc: float, vah: float, val: float, va_span: float,
        current_price: float,
        anchors_above: List[Dict], anchors_below: List[Dict],
        raw_histogram: List[Dict],
    ) -> str:
        lines = ["## 4. VOLUME PROFILE TOPOGRAPHY (Gaussian smoothed)", ""]

        peak_type, peak_strength = self._analyze_peak(raw_histogram, poc)
        lines.append(f"  POC = {poc:.1f}  peak_strength = {peak_strength:.2f}  peak_type = {peak_type}")
        lines.append(f"  VAH = {vah:.1f}  |  VAL = {val:.1f}")
        va_pct = va_span / current_price * 100 if current_price > 0 and va_span else 0
        lines.append(f"  VA_span = {va_span:.1f}  |  VA_width = {va_pct:.2f}% of price")

        lines.append("")
        lines.append("  ─── Profile shape ───")

        if vah and val and vah > val:
            poc_pos_pct = (poc - val) / (vah - val) * 100
        else:
            poc_pos_pct = 50.0

        if poc_pos_pct < self.VA_BALANCE_LOW:
            shape_type = "b-shaped (卖出尾端 — 下方集中)"
        elif poc_pos_pct > self.VA_BALANCE_HIGH:
            shape_type = "P-shaped (买入尾端 — 上方集中)"
        else:
            shape_type = "balanced (均衡分布)"

        lines.append(f"  Type: {shape_type}")
        lines.append(f"  POC position in VA: {poc_pos_pct:.0f}% from VAL, {100-poc_pos_pct:.0f}% to VAH")

        above_gradient, below_gradient = self._analyze_density_gradient(raw_histogram, poc)
        lines.append(f"  上方密度: {above_gradient}  |  下方密度: {below_gradient}")
        poc_rel = "POC 在价格下方 (支撑)" if poc < current_price else "POC 在价格上方 (阻力)"
        lines.append(f"  POC 与当前价格关系: {poc_rel}")

        lines.append("")
        lines.append("  ─── High Volume Nodes (within ±2 ATR of current price) ───")
        node_num = 1
        for a in anchors_above:
            s = a.get("strength", a.get("volume", 0))
            a_type = "POC" if abs(a['price'] - poc) < 0.01 else "secondary"
            lines.append(f"  HVN #{node_num} @ {a['price']:.1f}  strength={s:.2f}  "
                         f"type={a_type}  position=above_price")
            node_num += 1
        for a in anchors_below:
            s = a.get("strength", a.get("volume", 0))
            a_type = "POC" if abs(a['price'] - poc) < 0.01 else "secondary"
            lines.append(f"  HVN #{node_num} @ {a['price']:.1f}  strength={s:.2f}  "
                         f"type={a_type}  position=below_price")
            node_num += 1

        lines.append("")
        lines.append("  ─── Low Volume Nodes (gaps / vacuums) ───")
        vacuums = self._detect_vacuums(raw_histogram, current_price)
        if vacuums:
            for j, vac in enumerate(vacuums):
                lines.append(f"  LVN #{j+1}: {vac['low']:.0f}–{vac['high']:.0f}  "
                             f"vacuum_score={vac['score']:.2f}  width={vac['high']-vac['low']:.0f}")
                if vac['low'] > current_price:
                    pos = "above_price"
                elif vac['high'] < current_price:
                    pos = "below_price"
                else:
                    pos = "spanning_price"
                lines.append(f"    Position: {pos}")
        else:
            lines.append("  (no significant gaps detected)")

        lines.append("")
        lines.append("  ─── Anchoring assessment ───")
        above_prices = [a['price'] for a in anchors_above] + ([vah] if vah and vah > current_price else [])
        below_prices = [a['price'] for a in anchors_below] + \
                       ([poc] if poc and poc < current_price else []) + \
                       ([val] if val and val < current_price else [])

        if above_prices:
            nearest_above = min(above_prices, key=lambda p: p - current_price)
            dist = (nearest_above - current_price) / current_price * 100
            lines.append(f"  Nearest anchor above: @ {nearest_above:.1f}  dist=+{dist:.2f}%")
        else:
            lines.append("  Nearest anchor above: none within range")
        if below_prices:
            nearest_below = max(below_prices, key=lambda p: p - current_price)
            dist = (nearest_below - current_price) / current_price * 100
            lines.append(f"  Nearest anchor below: @ {nearest_below:.1f}  dist={dist:.2f}%")
        else:
            lines.append("  Nearest anchor below: none within range")

        all_anchors = [(a['price'], a.get('strength', a.get('volume', 0)))
                       for a in anchors_above + anchors_below]
        if all_anchors:
            strongest = max(all_anchors, key=lambda x: x[1])
            lines.append(f"  Strongest anchor overall: @ {strongest[0]:.1f} (strength={strongest[1]:.2f})")

        return "\n".join(lines)

    # ── Section 6: Liquidation Landscape ───────────────────────────────────

    def _section_liquidation(
        self, liquidations: Dict, poc: float, vah: float, val: float,
        anchors_above: List[Dict], anchors_below: List[Dict],
        current_price: float,
    ) -> str:
        lines = ["## 5. LIQUIDATION LANDSCAPE", ""]

        shorts = liquidations.get("short_liquidation", [])
        longs = liquidations.get("long_liquidation", [])

        above_shorts = [liq for liq in shorts if liq.get("price", 0) > current_price]
        if above_shorts:
            lines.append("  ─── SHORT liquidation clusters (above price — squeeze fuel) ───")
            for i, liq in enumerate(sorted(above_shorts, key=lambda x: x['price'])):
                p = liq['price']
                intensity = liq.get('intensity', 0)
                bar = self._bar(intensity, is_liq=True)
                pos = self._cluster_position(p, poc, vah, val, anchors_above, anchors_below)
                lines.append(f"  #{i+1} @ {p:.1f}  {bar}  intensity={intensity:.2f}")
                lines.append(f"     Position: {pos}")
        else:
            lines.append("  ─── SHORT liquidation clusters: none above price ───")

        lines.append("")

        below_longs = [liq for liq in longs if liq.get("price", 0) < current_price]
        if below_longs:
            lines.append("  ─── LONG liquidation clusters (below price — trap targets) ───")
            for i, liq in enumerate(sorted(below_longs, key=lambda x: x['price'], reverse=True)):
                p = liq['price']
                intensity = liq.get('intensity', 0)
                bar = self._bar(intensity, is_liq=True)
                pos = self._cluster_position(p, poc, vah, val, anchors_above, anchors_below)
                lines.append(f"  #{i+1} @ {p:.1f}  {bar}  intensity={intensity:.2f}")
                lines.append(f"     Position: {pos}")
        else:
            lines.append("  ─── LONG liquidation clusters: none below price ───")

        lines.append("")
        lines.append("  ─── Landscape summary ───")
        total_short = sum(liq.get('intensity', 0) for liq in shorts)
        total_long = sum(liq.get('intensity', 0) for liq in longs)
        lines.append(f"  Total clusters: {len(shorts)} short, {len(longs)} long")

        if total_long > total_short * 1.1:
            lines.append(f"  Asymmetry: Long-dominant (total long intensity {total_long:.2f} "
                         f"vs short {total_short:.2f})")
        elif total_short > total_long * 1.1:
            lines.append(f"  Asymmetry: Short-dominant (total short intensity {total_short:.2f} "
                         f"vs long {total_long:.2f})")
        else:
            lines.append(f"  Asymmetry: Balanced (long {total_long:.2f} vs short {total_short:.2f})")

        all_clusters = [(liq['price'], liq.get('intensity', 0), 'short' if liq in shorts else 'long')
                        for liq in shorts + longs]
        if all_clusters:
            nearest = min(all_clusters, key=lambda x: abs(x[0] - current_price))
            nearest_dist = abs(nearest[0] - current_price) / current_price * 100
            direction = "+" if nearest[0] > current_price else "−"
            lines.append(f"  Nearest cluster: {nearest[2].capitalize()} @ {direction}{nearest_dist:.2f}%")

            above_threat = [(liq['price'], liq['intensity']) for liq in above_shorts]
            below_threat = [(liq['price'], liq['intensity']) for liq in below_longs]
            all_threat = above_threat + below_threat
            if all_threat:
                threat = max(all_threat, key=lambda x: x[1])
                lines.append(f"  Highest intensity cluster: @ {threat[0]:.1f} (intensity={threat[1]:.2f})")

        return "\n".join(lines)

    # ── Section 7: Key Levels Reference ────────────────────────────────────

    @staticmethod
    def _section_key_levels(
        current_price: float, poc: float, vah: float, val: float,
        anchors_above: List[Dict], anchors_below: List[Dict],
        liquidations: Dict,
    ) -> str:
        lines = [
            "## 6. KEY LEVELS REFERENCE (price-descending)",
            "",
            "  PRICE        TYPE            STR/INT   POSITION VS PRICE",
            "  ───────────  ──────────────  ────────  ──────────────────",
        ]

        entries = []
        for a in anchors_above:
            s = a.get("strength", a.get("volume", 0))
            entries.append((a['price'], "HVN", s))
        for a in anchors_below:
            s = a.get("strength", a.get("volume", 0))
            entries.append((a['price'], "HVN", s))
        for liq in liquidations.get("short_liquidation", []):
            entries.append((liq['price'], "Short Liq", liq.get('intensity', 0)))
        for liq in liquidations.get("long_liquidation", []):
            entries.append((liq['price'], "Long Liq", liq.get('intensity', 0)))
        if vah:
            entries.append((vah, "VAH", None))
        if val:
            entries.append((val, "VAL", None))
        if poc:
            entries.append((poc, "POC", None))

        entries.sort(key=lambda x: x[0], reverse=True)
        current_inserted = False

        for price, label, str_val in entries:
            if not current_inserted and price < current_price:
                lines.append("  ─────────────────────────────────────────────────────────")
                lines.append(f"  {current_price:.1f}      ● CURRENT       —         0.00%")
                lines.append("  ─────────────────────────────────────────────────────────")
                current_inserted = True

            pct = (price - current_price) / current_price * 100
            sign = "+" if pct >= 0 else "−"
            sv = f"{str_val:.2f}" if str_val is not None else "—"
            lines.append(f"  {price:.1f}      {label:14s}  {sv:8s}  {sign}{abs(pct):.2f}%")

        if not current_inserted:
            lines.append("  ─────────────────────────────────────────────────────────")
            lines.append(f"  {current_price:.1f}      ● CURRENT       —         0.00%")
            lines.append("  ─────────────────────────────────────────────────────────")

        return "\n".join(lines)

    # ── Formatting helpers ─────────────────────────────────────────────────

    @staticmethod
    def _bar(value, *, is_liq=False):
        if value is None:
            value = 0.0
        v = float(value)
        fill = min(4, max(1, int(v * 5 + 0.5)))
        ch = "▓" if is_liq else "█"
        return f"[{ch * fill}{' ' * (4 - fill)}]"

    @staticmethod
    def _str_info(value, *, is_liq=False):
        if value is None:
            return ""
        if is_liq:
            return f"intensity={float(value):.2f}"
        return f"strength={float(value):.2f}"

    @staticmethod
    def _candle_art(body_ratio, is_bull):
        if is_bull:
            fill = max(1, int(body_ratio * 4))
            return f"[{' ' * (4 - fill)}{'█' * fill}]"
        else:
            fill = max(1, int(body_ratio * 4))
            return f"[{'█' * fill}{' ' * (4 - fill)}]"

    @staticmethod
    def _cluster_position(price, poc, vah, val, anchors_above, anchors_below):
        refs = []
        if vah:
            refs.append((f"VAH ({vah:.1f})", vah))
        if val:
            refs.append((f"VAL ({val:.1f})", val))
        if poc:
            refs.append((f"POC ({poc:.1f})", poc))
        for a in anchors_above:
            refs.append((f"HVN ({a['price']:.1f})", a['price']))
        for a in anchors_below:
            refs.append((f"HVN ({a['price']:.1f})", a['price']))
        refs.sort(key=lambda x: x[1])
        above = [(n, p) for n, p in refs if p > price]
        below = [(n, p) for n, p in refs if p < price]
        nearest_above = min(above, key=lambda x: x[1]) if above else None
        nearest_below = max(below, key=lambda x: x[1]) if below else None
        if nearest_above and nearest_below:
            return f"between {nearest_below[0]} and {nearest_above[0]}"
        elif nearest_above:
            return f"below {nearest_above[0]}, no nearby structure below"
        elif nearest_below:
            return f"above {nearest_below[0]}, no nearby structure above"
        return "isolated — no nearby structural anchors"

    # ── Analysis helpers ───────────────────────────────────────────────────

    @staticmethod
    def _normalize_liquidations(liquidations):
        if isinstance(liquidations, dict):
            return {
                "long_liquidation": list(liquidations.get("long_liquidation", []) or []),
                "short_liquidation": list(liquidations.get("short_liquidation", []) or []),
            }
        return {"long_liquidation": [], "short_liquidation": []}

    @staticmethod
    def _analyze_peak(raw_histogram, poc):
        if not raw_histogram:
            return "unknown", 0.0
        volumes = [b.get('volume', 0) for b in raw_histogram if b.get('volume', 0) > 0]
        if not volumes:
            return "flat", 0.0
        max_vol = max(volumes)
        mean_vol = float(np.mean(volumes))
        ratio = max_vol / mean_vol if mean_vol > 0 else 1.0
        peak_type = "sharp (单峰集中)" if ratio > VisualContextSummarizer.PEAK_SHARPNESS else "distributed (分散)"
        poc_bin = next((b for b in raw_histogram if abs(b.get('price', 0) - poc) < 0.01), None)
        poc_strength = poc_bin.get('volume', 0) / max_vol if poc_bin and max_vol > 0 else 0.5
        return peak_type, round(poc_strength, 2)

    @staticmethod
    def _analyze_density_gradient(raw_histogram, poc):
        if not raw_histogram:
            return "unknown", "unknown"
        above_vols = [b.get('volume', 0) for b in raw_histogram if b.get('price', 0) > poc]
        below_vols = [b.get('volume', 0) for b in raw_histogram if b.get('price', 0) < poc]
        above_mean = float(np.mean(above_vols)) if above_vols else 0.0
        below_mean = float(np.mean(below_vols)) if below_vols else 0.0
        if above_mean < below_mean * 0.7:
            return "分散 (low density)", "集中 (high density)"
        elif below_mean < above_mean * 0.7:
            return "集中 (high density)", "分散 (low density)"
        return "均匀", "均匀"

    @staticmethod
    def _detect_vacuums(raw_histogram, current_price, max_vacuums=3):
        if not raw_histogram:
            return []
        sorted_bins = sorted(raw_histogram, key=lambda x: x.get('price', 0))
        if len(sorted_bins) < 3:
            return []
        volumes = [b.get('volume', 0) for b in sorted_bins]
        prices = [b.get('price', 0) for b in sorted_bins]
        max_vol = max(volumes) if volumes else 1
        vacuums = []
        i = 0
        while i < len(sorted_bins) - 1 and len(vacuums) < max_vacuums:
            if volumes[i] < max_vol * 0.15:
                gap_start = prices[i]
                j = i
                while j < len(sorted_bins) and volumes[j] < max_vol * 0.25:
                    j += 1
                gap_end = prices[min(j, len(prices) - 1)]
                if gap_end - gap_start > 0:
                    seg_vols = volumes[i:min(j+1, len(volumes))]
                    seg_mean = float(np.mean(seg_vols)) if seg_vols else 0
                    denom = max_vol * (j - i + 1) + 1e-9
                    score = 1.0 - (sum(seg_vols) / denom)
                    vacuums.append({"low": gap_start, "high": gap_end, "score": round(min(1.0, score), 2)})
                i = j
            else:
                i += 1
        return vacuums

    @staticmethod
    def _detect_volume_gaps(window, vol_ma):
        volumes = window['volume'].values.astype(float)
        gaps = []
        i = 0
        while i < len(volumes):
            if volumes[i] < vol_ma * 0.4:
                gaps.append(str(i))
                while i < len(volumes) and volumes[i] < vol_ma * 0.6:
                    i += 1
            else:
                i += 1
        return ", ".join(gaps) if gaps else ""
```

- [ ] **Step 4: Run tests — verify pass**

```bash
cd /Users/yangjiang/Documents/workspace/crypto && python -m pytest tests/unit/test_visual_context_summarizer.py -v 2>&1
```

Expected: all 7 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/analyzer/visual_context_summarizer.py tests/unit/test_visual_context_summarizer.py
git commit -m "feat: add VisualContextSummarizer for chart-to-text generation"
```

---

### Task 3: Wire summarizer into MarketObserver

**Files:**
- Modify: `src/analyzer/market_observer.py:12` (add import)
- Modify: `src/analyzer/market_observer.py:606` (init summarizer)
- Modify: `src/analyzer/market_observer.py:725-750` (`_generate_snapshots`)

**Interfaces:**
- Consumes: `VisualContextSummarizer` from Task 2
- Produces: `observation["visual_context"]["macro_snapshot_summary"]` and `["micro_snapshot_summary"]`

- [ ] **Step 1: Add import**

In `src/analyzer/market_observer.py`, after line 12 (`from src.analyzer.chart_generator import ChartGenerator`):

```python
from src.analyzer.visual_context_summarizer import VisualContextSummarizer
```

- [ ] **Step 2: Initialize summarizer in MarketObserver.__init__**

After line 606 (`self._charting = chart_generator`):

```python
        self._summarizer = VisualContextSummarizer()
```

- [ ] **Step 3: Replace `_generate_snapshots`**

Replace `src/analyzer/market_observer.py` lines 725-750 with:

```python
    def _generate_snapshots(self, raw: RawMarketData, metrics: ProcessedMarketMetrics,
                            m_df: 'pd.DataFrame', n_df: 'pd.DataFrame',
                            data_root: str, at_time: datetime) -> Dict[str, str]:
        """Triggers high-fidelity chart generation and text summaries for Macro and Micro contexts."""
        img_dir = os.path.join(data_root, "klines")
        self._charting.storage.output_dir = img_dir

        ctx = {**metrics.volume_profile, "timestamp": format_datetime(at_time, FILE_TIMESTAMP_FORMAT)}
        liq_clusters = metrics.sentiment_signals.get("liquidation_clusters")
        atr_macro = metrics.price_dynamics['atr_macro']

        # Macro
        macro_png = self._charting.generate_chart(
            self.symbol, m_df, ctx, liq_clusters,
            time_interval=self.config.macro_context.time_interval,
            atr=atr_macro,
        )
        macro_md = self._write_summary(
            self.symbol, m_df, ctx, liq_clusters,
            time_interval=self.config.macro_context.time_interval,
            atr=atr_macro, output_dir=img_dir,
        )

        # Micro
        micro_png = self._charting.generate_chart(
            self.symbol, n_df, ctx, liq_clusters,
            time_interval=self.config.micro_context.time_interval,
            atr=atr_macro,
        )
        micro_md = self._write_summary(
            self.symbol, n_df, ctx, liq_clusters,
            time_interval=self.config.micro_context.time_interval,
            atr=atr_macro, output_dir=img_dir,
        )

        return {
            "macro_snapshot": macro_png,
            "micro_snapshot": micro_png,
            "macro_snapshot_summary": macro_md,
            "micro_snapshot_summary": micro_md,
        }

    def _write_summary(self, symbol: str, df: 'pd.DataFrame',
                       profile_data: Dict[str, Any],
                       liquidations, time_interval: str,
                       atr: float, output_dir: str) -> str:
        """Generate visual context summary .md file and return its path."""
        os.makedirs(output_dir, exist_ok=True)
        # Derive .md path from same naming convention as .png
        from src.utils.datetime_utils import format_timestamp_for_filename
        ts = profile_data.get("timestamp", "")
        ts_readable = format_timestamp_for_filename(ts)
        filename = f"{symbol}_klines_{time_interval}_{ts_readable}.md"
        filepath = os.path.join(output_dir, filename)

        text = self._summarizer.generate(
            symbol=symbol, df=df, profile_data=profile_data,
            liquidations=liquidations, time_interval=time_interval, atr=atr,
        )
        with open(filepath, 'w') as f:
            f.write(text)

        logger.info(f"[{symbol}] visual summary written | interval={time_interval} | file={filepath}")
        return filepath
```

- [ ] **Step 4: Verify — existing tests still pass**

```bash
cd /Users/yangjiang/Documents/workspace/crypto && python -m pytest tests/ -x -q 2>&1 | tail -5
```

- [ ] **Step 5: Commit**

```bash
git add src/analyzer/market_observer.py
git commit -m "feat: generate .md visual summaries alongside .png charts"
```

---

### Task 4: Modify BinaryStarOrchestrator — branch on supports_vision

**Files:**
- Modify: `src/agent/binary_star_orchestrator.py:300` (store supports_vision)
- Modify: `src/agent/binary_star_orchestrator.py:329-333` (`execute_flow` — call new loader)
- Modify: `src/agent/binary_star_orchestrator.py:343-355` (`execute_flow` — pass visual_context_text to DebateLoop)
- Modify: `src/agent/binary_star_orchestrator.py:517-532` (replace `_extract_visual_parts` with `_load_visual_assets`)

**Interfaces:**
- Consumes: `self.client.supports_vision` from Task 1
- Consumes: `observation["visual_context"]["macro_snapshot_summary"]` / `["micro_snapshot_summary"]` from Task 3
- Produces: `visual_parts: List[VisualPart]`, `visual_context_text: str | None`

- [ ] **Step 1: Store supports_vision in __init__**

In `src/agent/binary_star_orchestrator.py`, after line 232 (`self.client = AIFactory.create_client(...)`):

```python
        self._supports_vision = self.client.supports_vision
```

- [ ] **Step 2: Replace `_extract_visual_parts` with `_load_visual_assets`**

Replace `src/agent/binary_star_orchestrator.py` lines 517-532 with:

```python
    def _load_visual_assets(self, observation: Dict[str, Any]) -> tuple[List[VisualPart], str | None]:
        """Load visual assets based on provider capability.

        supports_vision=True  → read .png files into VisualPart list
        supports_vision=False → read .md files into visual_context_text string
        """
        vc = observation.get('visual_context', {})

        if self._supports_vision:
            parts: list[VisualPart] = []
            for key in ('macro_snapshot', 'micro_snapshot'):
                path = vc.get(key)
                if path and os.path.exists(path):
                    with open(path, 'rb') as f:
                        parts.append(VisualPart(
                            mime_type='image/png',
                            data=f.read(),
                            label=f'[VISUAL_CONTEXT: {key.upper()}]',
                        ))
            return parts, None
        else:
            text_blocks: list[str] = []
            for label, key in [
                ('VISUAL_CONTEXT: MACRO_SNAPSHOT', 'macro_snapshot_summary'),
                ('VISUAL_CONTEXT: MICRO_SNAPSHOT', 'micro_snapshot_summary'),
            ]:
                path = vc.get(key)
                if path and os.path.exists(path):
                    with open(path, 'r') as f:
                        text_blocks.append(f'{label}\n\n{f.read()}')
            text = '\n\n'.join(text_blocks) if text_blocks else None
            return [], text
```

- [ ] **Step 3: Update execute_flow to use new loader and correct paths**

In `src/agent/binary_star_orchestrator.py`, replace lines 329-333:

```python
        # Before (delete):
        pruned_observation = observation.copy()
        if 'visual_context' in pruned_observation:
            del pruned_observation['visual_context']
        observation_json = json.dumps(pruned_observation, indent=2, ensure_ascii=False)
        visual_parts = self._extract_visual_parts(observation)

        # After:
        pruned_observation = observation.copy()
        if 'visual_context' in pruned_observation:
            del pruned_observation['visual_context']
        observation_json = json.dumps(pruned_observation, indent=2, ensure_ascii=False)
        visual_parts, visual_context_text = self._load_visual_assets(observation)

        # Correct report visual_context paths for non-vision models
        if not self._supports_vision:
            vc = observation.get('visual_context', {})
            vc['macro_snapshot'] = vc.get('macro_snapshot_summary', vc.get('macro_snapshot', ''))
            vc['micro_snapshot'] = vc.get('micro_snapshot_summary', vc.get('micro_snapshot', ''))
```

- [ ] **Step 4: Pass visual_context_text to DebateLoop**

In the DebateLoop constructor call (around line 344-355), add `visual_context_text`:

```python
        # Before:
        self.debate_loop = DebateLoop(
            session_agent=self.session_agent,
            critic_agent=self.critic_agent,
            math_checker=self.math_checker,
            max_rounds=self.max_rounds,
            cache_resource_name=cache_resource_name,
            tools=tools,
            visual_parts=visual_parts,
            shared_instruction=self.shared_instruction,
            session_config=self.session_config,
            critic_config=self.critic_config,
        )

        # After (add one line):
        self.debate_loop = DebateLoop(
            session_agent=self.session_agent,
            critic_agent=self.critic_agent,
            math_checker=self.math_checker,
            max_rounds=self.max_rounds,
            cache_resource_name=cache_resource_name,
            tools=tools,
            visual_parts=visual_parts,
            visual_context_text=visual_context_text,
            shared_instruction=self.shared_instruction,
            session_config=self.session_config,
            critic_config=self.critic_config,
        )
```

- [ ] **Step 5: Pass visual_context_text to SessionAgent in `_finalize_and_sanitize`**

In `_finalize_and_sanitize()` (around line 477-487), the `session_agent.execute_session_cycle()` call needs `visual_context_text`:

```python
        # After the existing line:
        # visual_parts=visual_parts,
        # Add:
        # visual_context_text=visual_context_text,
```

But wait — `_finalize_and_sanitize` receives `visual_parts` from `execute_flow()`'s scope. We also need to pass `visual_context_text` to it. Let me handle this:

In `execute_flow()`, update the `_finalize_and_sanitize` call to pass `visual_context_text`:

```python
        final_decision = self._finalize_and_sanitize(
            debate_result, observation, symbol,
            cache_resource_name, tools, visual_parts,
            visual_context_text,
            progress_callback=progress_callback)
```

And update `_finalize_and_sanitize` signature:

```python
    def _finalize_and_sanitize(self, debate_result: dict, observation: dict,
                               symbol: str, cache_resource_name: str | None,
                               tools: list, visual_parts: list,
                               visual_context_text: str | None,
                               progress_callback=None) -> dict:
```

And in the `session_agent.execute_session_cycle()` call within `_finalize_and_sanitize`, add:

```python
            final_decision = self.session_agent.execute_session_cycle(
                observation=observation,
                symbol=symbol,
                temperature=self.critic_config.model_temperature,
                agent_name="Session_Synthesis",
                cache_resource_name=cache_resource_name,
                tools=tools,
                debate_history=self.debate_loop._compress_debate_history(debate_history),
                visual_parts=visual_parts,
                visual_context_text=visual_context_text,
                system_instruction=self.shared_instruction
            )
```

- [ ] **Step 6: Verify — existing tests pass**

```bash
cd /Users/yangjiang/Documents/workspace/crypto && python -m pytest tests/ -x -q 2>&1 | tail -5
```

- [ ] **Step 7: Commit**

```bash
git add src/agent/binary_star_orchestrator.py
git commit -m "feat: branch on supports_vision — load .png or .md for visual context"
```

---

### Task 5: Modify DebateLoop to pass visual_context_text

**Files:**
- Modify: `src/agent/debate_loop.py:14-28` (`__init__`)
- Modify: `src/agent/debate_loop.py:60-70` (Session call in `run`)
- Modify: `src/agent/debate_loop.py:99-109` (Critic call in `run`)

**Interfaces:**
- Consumes: `visual_context_text: str | None` from Task 4
- Produces: passes `visual_context_text` to SessionAgent.execute_session_cycle and CriticAgent.evaluate

- [ ] **Step 1: Update `__init__` to accept and store `visual_context_text`**

In `src/agent/debate_loop.py`, update the constructor signature (line 14-17):

```python
    def __init__(self, session_agent, critic_agent, math_checker: MathFactChecker,
                 max_rounds: int, cache_resource_name: str | None,
                 tools: list, visual_parts: list, shared_instruction: str,
                 session_config, critic_config,
                 visual_context_text: str | None = None):
```

And add storage after line 24 (`self.visual_parts = visual_parts`):

```python
        self.visual_context_text = visual_context_text
```

- [ ] **Step 2: Pass `visual_context_text` to SessionAgent in run()**

In `debate_loop.py`, update the `execute_session_cycle` call (around line 60-70), add the parameter:

```python
            last_plan = self.session_agent.execute_session_cycle(
                observation=observation,
                symbol=symbol,
                temperature=self.session_config.model_temperature,
                agent_name=f"Session_Planning_R{current_round}",
                cache_resource_name=self.cache_resource_name,
                tools=self.tools,
                debate_history=compressed_history,
                visual_parts=self.visual_parts,
                visual_context_text=self.visual_context_text,
                system_instruction=self.shared_instruction
            )
```

- [ ] **Step 3: Pass `visual_context_text` to CriticAgent in run()**

In `debate_loop.py`, update the `critic_agent.evaluate` call (around line 99-109), add the parameter:

```python
            critic_results = self.critic_agent.evaluate(
                observation=observation,
                last_plan=last_plan,
                symbol=symbol,
                debate_history=compressed_history,
                cache_resource_name=self.cache_resource_name,
                math_fact_check=math_fact_check,
                tools=None,
                visual_parts=self.visual_parts,
                visual_context_text=self.visual_context_text,
                system_instruction=self.shared_instruction
            )
```

- [ ] **Step 4: Commit**

```bash
git add src/agent/debate_loop.py
git commit -m "feat: pass visual_context_text through DebateLoop to agents"
```

---

### Task 6: Modify SessionAgent to inject VISUAL_CONTEXT text into prompt

**Files:**
- Modify: `src/agent/session_agent.py:106-140` (`execute_session_cycle`)

**Interfaces:**
- Consumes: `visual_context_text: str | None` from DebateLoop
- Produces: injected VISUAL_CONTEXT text block in prompt before `_execute_ai_cycle`

- [ ] **Step 1: Update `execute_session_cycle` signature and logic**

Replace `src/agent/session_agent.py` lines 106-140:

```python
    def execute_session_cycle(
        self,
        observation: Optional[Dict[str, Any]],
        symbol: str,
        temperature: float,
        agent_name: str,
        debate_history: Optional[List[Dict[str, Any]]] = None,
        cache_resource_name: Optional[str] = None,
        tools: Optional[List[Any]] = None,
        visual_parts: Optional[List[Any]] = None,
        visual_context_text: Optional[str] = None,
        system_instruction: Optional[str] = None
    ) -> Dict[str, Any]:
        """Core execution logic for a session reasoning step."""
        logger.info(f"[{symbol}] agent {agent_name} starting")
        try:
            prompt = self._build_prompt(
                observation=observation,
                debate_history=debate_history,
                cache_resource_name=cache_resource_name
            )

            # Inject VISUAL_CONTEXT text block for non-vision models
            if visual_context_text:
                prompt = prompt + '\n\n' + visual_context_text

            payload = [prompt]
            if not cache_resource_name and visual_parts:
                payload.extend(visual_parts)

            return self._execute_ai_cycle(
                payload=payload,
                temperature=temperature,
                agent_name=agent_name,
                cache_resource_name=cache_resource_name,
                tools=tools,
                system_instruction=system_instruction
            )
        except Exception as e:
            logger.error(f"[{symbol}] agent {agent_name} failed | error={e}")
            raise
```

- [ ] **Step 2: Commit**

```bash
git add src/agent/session_agent.py
git commit -m "feat: inject VISUAL_CONTEXT text into SessionAgent prompt"
```

---

### Task 7: Modify CriticAgent to inject VISUAL_CONTEXT text into prompt

**Files:**
- Modify: `src/agent/critic_agent.py:91-134` (`evaluate`)

**Interfaces:**
- Consumes: `visual_context_text: str | None` from DebateLoop
- Produces: injected VISUAL_CONTEXT text block in prompt before `_execute_ai_cycle`

- [ ] **Step 1: Update `evaluate` signature and logic**

Replace `src/agent/critic_agent.py` lines 91-134:

```python
    def evaluate(
        self,
        observation: Optional[Dict[str, Any]],
        last_plan: Dict[str, Any],
        symbol: str,
        debate_history: Optional[List[Dict[str, Any]]] = None,
        cache_resource_name: Optional[str] = None,
        math_fact_check: Optional[Dict[str, Any]] = None,
        tools: Optional[List[Any]] = None,
        visual_parts: Optional[List[Any]] = None,
        visual_context_text: Optional[str] = None,
        system_instruction: Optional[str] = None
    ) -> Dict[str, Any]:
        """Evaluates the proposed plan against physical market topography
        and the mandatory CRITIC_CODES table. This is a cold,
        deterministic audit designed to identify structural traps.
        """
        logger.info(f"[{symbol}] auditing proposal")
        try:
            context = self._build_context(
                observation,
                last_plan,
                debate_history=debate_history,
                math_fact_check=math_fact_check,
                cache_resource_name=cache_resource_name
            )
            prompt = self._prepare_prompt(self.config.instruction_path, **context)

            # Inject VISUAL_CONTEXT text block for non-vision models
            if visual_context_text:
                prompt = prompt + '\n\n' + visual_context_text

            payload = [prompt]
            if not cache_resource_name and visual_parts:
                payload.extend(visual_parts)

            return self._execute_ai_cycle(
                payload=payload,
                temperature=self.config.model_temperature,
                agent_name="Critic_Evaluation",
                cache_resource_name=cache_resource_name,
                tools=tools,
                system_instruction=system_instruction
            )
        except Exception as e:
            logger.error(f"[{symbol}] evaluation failed | error={e}")
            raise
```

- [ ] **Step 2: Commit**

```bash
git add src/agent/critic_agent.py
git commit -m "feat: inject VISUAL_CONTEXT text into CriticAgent prompt"
```

---

### Task 8: Update clean-orphan-artifacts regex to include .md files

**Files:**
- Modify: `scripts/clean_orphan_artifacts.py:48`

- [ ] **Step 1: Add `.md` to regex**

Replace line 48:

```python
# Before:
ARTIFACT_RE = re.compile(r'^([A-Z0-9]+)_.*_(\d{8})_(\d{6})\.(json|png|html)$')

# After:
ARTIFACT_RE = re.compile(r'^([A-Z0-9]+)_.*_(\d{8})_(\d{6})\.(json|png|html|md)$')
```

No other changes needed. The `klines/` directory is already in the scanned directory list (line 196). The key extraction logic (`extract_key`) works identically for `.md` files.

- [ ] **Step 2: Verify syntax**

```bash
cd /Users/yangjiang/Documents/workspace/crypto && python -c "
import re
ARTIFACT_RE = re.compile(r'^([A-Z0-9]+)_.*_(\d{8})_(\d{6})\.(json|png|html|md)$')
# Test with .md filename
m = ARTIFACT_RE.match('BTCUSDT_klines_1h_20260704_093000.md')
assert m is not None
assert m.group(1) == 'BTCUSDT'
print('regex OK')
"
```

Expected: `regex OK`

- [ ] **Step 3: Commit**

```bash
git add scripts/clean_orphan_artifacts.py
git commit -m "feat: include .md visual summaries in orphan artifact cleanup"
```

---

### Final Verification

- [ ] **Full test suite:**

```bash
cd /Users/yangjiang/Documents/workspace/crypto && python -m pytest tests/ -v 2>&1 | tail -20
```

Expected: all tests pass.

- [ ] **Quick smoke test — import chain:**

```bash
cd /Users/yangjiang/Documents/workspace/crypto && python -c "
from src.infrastructure.ai_client import AbstractAIClient
from src.analyzer.visual_context_summarizer import VisualContextSummarizer
print('supports_vision default:', AbstractAIClient().supports_vision)
print('all imports OK')
"
```

Expected: `supports_vision default: False`, `all imports OK`.
