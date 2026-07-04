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
            if p > current_price and abs(p - poc) > 0.01:
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

        elif poc and poc >= current_price:
            poc_strength = 0.0
            for a in anchors_above:
                if abs(a.get("price", 0) - poc) < 0.01:
                    poc_strength = a.get("strength", a.get("volume", 0))
                    break
            if not poc_strength:
                poc_strength = 0.94
            above_entries.append((poc, "POC", poc_strength, "Point of Control"))

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
