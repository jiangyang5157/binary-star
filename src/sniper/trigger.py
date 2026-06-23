import os
from typing import Dict, Any, Tuple, Optional, List
from datetime import datetime, timezone

from src.utils.path_utils import resolve_project_root
from src.utils.logger_utils import setup_logger

logger = setup_logger(__name__)

class SniperTrigger:
    """
    The Decision Node of the 'Sniper Mode'.
    
    All thresholds and cooldowns are injected via strategy_cfg/global_cfg
    constructor parameters (or loaded from strategy_config.yaml if omitted).
    """
    
    def __init__(self, strategy_cfg: Optional[dict] = None, global_cfg: Optional[dict] = None):
        self.last_trigger_time: Optional[datetime] = None

        # Accept pre-loaded configs (with per-symbol overrides applied) or load defaults
        from src.utils.pipeline_utils import load_combined_config, load_global_config
        self.strat_cfg = strategy_cfg if strategy_cfg is not None else load_combined_config()
        self.global_cfg = global_cfg if global_cfg is not None else load_global_config()
        self.regime_cfg = self.strat_cfg['regime_parameters']

        # EXPLICIT CONFIG ENFORCEMENT
        self.sniper_cfg = self.global_cfg['sniper']

        # Derive cooldown from micro-context (e.g., 15m) + Multiplier
        micro_interval = self.strat_cfg['analysis_window']['micro_context']['time_interval']
        base_cooldown = self._parse_interval_to_minutes(micro_interval)
        self.cooldown_minutes = base_cooldown * self.sniper_cfg['cooldown']['pulse_cooldown_multiplier']

        logger.info(f"SniperTrigger: Physically standalone. Cooldown={self.cooldown_minutes}m (Mult: {self.sniper_cfg['cooldown']['pulse_cooldown_multiplier']}).")

    def _parse_interval_to_minutes(self, interval_str: str) -> float:
        """Parse a Binance interval string ('15m', '1h', '1d') into float minutes."""
        val = int(interval_str[:-1])
        unit = interval_str[-1].lower()
        if unit == 'h': return val * 60.0
        if unit == 'd': return val * 1440.0
        return float(val) # Default for 'm'

    def evaluate(self, current_metrics: Dict[str, Any], prev_metrics: Optional[Dict[str, Any]] = None) -> Tuple[bool, Optional[str], Optional[str]]:
        """
        Evaluates the current market state for 'noteworthy' asymmetry.
        """
        now = datetime.now(timezone.utc)

        # 0. Global Physical Cooldown Check
        if self.last_trigger_time:
            elapsed = (now - self.last_trigger_time).total_seconds() / 60.0
            if elapsed < self.cooldown_minutes:
                return False, None, f"GLOBAL_COOLDOWN (Aligned: {elapsed:.1f}m/{self.cooldown_minutes}m)"

        # 1. Evaluate DNA Traps — score all three, return the strongest hit
        # CHAOS_MUTE (Extreme Volatility Protection)
        vol = current_metrics['price_dynamics']['volatility_intensity_index']
        if vol > self.regime_cfg['volatility']['volatility_extreme_ratio']:
            if self.last_trigger_time:
                elapsed = (now - self.last_trigger_time).total_seconds() / 60.0
                chaos_mult = self.sniper_cfg['cooldown']['chaos_cooldown_multiplier']
                if elapsed < (self.cooldown_minutes * chaos_mult):
                    return False, None, f"CHAOS_MUTE (Extreme Volatility: {vol:.2f} | Cooldown x{chaos_mult})"

        checks = [
            (self._check_type_a, "TYPE_A (Breakout)"),
            (self._check_type_b, "TYPE_B (Asymmetry)"),
            (self._check_type_c, "TYPE_C (Structural)"),
        ]

        # Score all types, pick the strongest hit
        hits: list[tuple[int, str, str]] = []  # (strength, type_tag, reason)
        for check_fn, type_tag in checks:
            is_hit, reason = check_fn(current_metrics, prev_metrics)
            if is_hit and reason:
                # Parse strength from reason string: "[strength=N/10] ..."
                strength = 5  # default
                if reason.startswith("[strength="):
                    try:
                        end = reason.index("]")
                        strength = int(reason[10:end].split("/")[0])
                    except (ValueError, IndexError):
                        pass
                hits.append((strength, type_tag, reason))

        if hits:
            hits.sort(key=lambda x: x[0], reverse=True)  # highest strength first
            strength, type_tag, reason = hits[0]
            logger.info(f"SNIPER WAKE UP! [{type_tag}] | {reason}")
            return True, type_tag, reason

        return False, None, "SLEEPING"

    def _check_state_lock(self, lock_key: str, now: datetime) -> bool:
        """Returns True if permitted to trigger, False if muted by state lock."""
        if not hasattr(self, 'state_locks'):
            self.state_locks = {}
        cooldown_hours = self.sniper_cfg['cooldown']['state_lockout_hours']
        
        if lock_key in self.state_locks:
            elapsed_hours = (now - self.state_locks[lock_key]).total_seconds() / 3600.0
            if elapsed_hours < cooldown_hours:
                return False
        self.state_locks[lock_key] = now
        return True

    def _check_type_a(self, curr: Dict[str, Any], prev: Optional[Dict[str, Any]] = None) -> Tuple[bool, Optional[str]]:
        """TYPE_A (Breakout): volatility expansion + volume surge, or extreme physical squeeze."""
        vol = curr['price_dynamics']['volatility_intensity_index']
        part = curr['market_regime']['volume_participation_ratio']
        squeeze = curr['market_regime']['squeeze_factor']

        # 1. Volatility Expansion + Volume Surge
        vol_threshold = self.regime_cfg['volatility']['volatility_baseline_ratio']
        is_vol_hit = vol > vol_threshold

        part_threshold = self.regime_cfg['volume']['volume_participation_threshold']
        is_volume_hit = part > part_threshold

        # Confirmation gate: require vol to be NEWLY expanding (not just sustained)
        if is_vol_hit and is_volume_hit and prev:
            prev_vol = prev['price_dynamics']['volatility_intensity_index']
            growth_ratio = self.sniper_cfg['probes'].get('vol_growth_significance_ratio', 1.03)
            if vol <= prev_vol * growth_ratio:
                is_vol_hit = False  # vol is elevated but not accelerating — skip

        # 2. Physical Squeeze
        squeeze_mult = self.sniper_cfg['probes']['squeeze_trigger_multiplier']
        squeeze_threshold = self.regime_cfg['volatility']['squeeze_threshold'] * squeeze_mult
        is_squeeze_hit = squeeze < squeeze_threshold

        # Confirmation gate: require squeeze to be INTENSIFYING (getting tighter)
        if is_squeeze_hit and prev:
            prev_squeeze = prev['market_regime']['squeeze_factor']
            if squeeze >= prev_squeeze * 0.98:  # less than 2% tighter
                is_squeeze_hit = False

        # Signal strength for priority scoring
        strength = 0
        if is_vol_hit and is_volume_hit:
            strength = max(1, min(10, int((vol / max(vol_threshold, 0.01)) * 5)))
        elif is_squeeze_hit:
            strength = max(1, min(10, int((squeeze_threshold / max(squeeze, 0.001)) * 4)))

        if (is_vol_hit and is_volume_hit) or is_squeeze_hit:
            reason = f"[strength={strength}/10] TYPE_A 势能破局: "
            if is_vol_hit and is_volume_hit:
                reason += f"[暴走] Vol={vol:.2f}(>{vol_threshold:.2f}) | Vol_Ratio={part:.2f}"
            elif is_squeeze_hit:
                now = datetime.now(timezone.utc)
                if not self._check_state_lock("SQUEEZE_STATE", now):
                    return False, None
                reason += f"[挤压] Squeeze={squeeze:.2f}(<{squeeze_threshold:.2f}) | Multiplier={squeeze_mult}"
            return True, reason

        return False, None

    def _check_type_b(self, curr: Dict[str, Any], prev: Optional[Dict[str, Any]] = None) -> Tuple[bool, Optional[str]]:
        """TYPE_B (Asymmetry): five sub-strategies evaluating CVD divergence/impulse,
        CVD momentum, retail sentiment extremes, and funding rate extremes."""
        sent = curr.get('sentiment_signals', {})
        cvd_threshold = self.regime_cfg['micro_sentiment']['cvd_intensity_threshold']
        cvd = sent.get('cvd_intensity_ratio', 0.0)

        # --- [Priority 1] Dynamic micro-event probes (tick-delta acceleration) ---
        if prev:
            prev_sent = prev.get('sentiment_signals', {})
            prev_cvd = prev_sent.get('cvd_intensity_ratio', 0.0)
            cvd_delta_raw = cvd - prev_cvd
            cvd_delta_abs = abs(cvd_delta_raw)

            # A. CVD divergence: price and CVD move in opposite directions
            divergence_threshold = self.sniper_cfg['probes']['cvd_divergence_tick_delta']
            if cvd_delta_abs > divergence_threshold:
                curr_price = curr['price_dynamics']['current_price']
                prev_price = prev['price_dynamics']['current_price']
                price_delta = curr_price - prev_price
                if (price_delta > 0 and cvd_delta_raw < 0) or (price_delta < 0 and cvd_delta_raw > 0):
                    strength = max(1, min(10, int((cvd_delta_abs / max(divergence_threshold, 0.001)) * 5)))
                    trend = "顶部派发 [警惕见顶回撤]" if price_delta > 0 else "底部吸筹 [关注止跌反弹]"
                    return True, (
                        f"[strength={strength}/10] TYPE_B CVD 超速背离 [量价背离] "
                        f"(价格变动:{price_delta:.1f}, CVD变动:{cvd_delta_raw:.3f} | 阈值: {divergence_threshold}) | "
                        f"**趋势推演: {trend}**"
                    )

            # B. CVD impulse: large single-pulse order
            pulse_threshold = self.sniper_cfg['probes']['cvd_impulse_tick_delta']
            if cvd_delta_abs > pulse_threshold:
                strength = max(1, min(10, int((cvd_delta_abs / max(pulse_threshold, 0.001)) * 4)))
                trend = "多头大单突袭" if cvd_delta_raw > 0 else "空头大单压制"
                return True, (
                    f"[strength={strength}/10] TYPE_B CVD 异常脉冲 [大单突袭] "
                    f"(变动值: {cvd_delta_abs:.3f} | 阈值: {pulse_threshold}) | **趋势推演: {trend}**"
                )

        # --- [Priority 2] Absolute CVD momentum ---
        if abs(cvd) > cvd_threshold:
            should_trigger = True
            if prev:
                prev_cvd = prev.get('sentiment_signals', {}).get('cvd_intensity_ratio', 0.0)
                growth_ratio = self.sniper_cfg['probes']['cvd_growth_significance_ratio']
                if abs(cvd) <= abs(prev_cvd) * growth_ratio:
                    should_trigger = False
                if should_trigger:
                    strength = max(1, min(10, int((abs(cvd) / max(cvd_threshold, 0.01)) * 5)))
                    cvd_vol_delta = sent.get('cvd_volume_delta', 0.0)
                    cvd_vol = sent.get('cvd_total_volume', 0.0)
                    cvd_lookback_candles = sent.get('cvd_lookback_candles', 0)
                    micro_int = self.strat_cfg['analysis_window']['micro_context']['time_interval']
                    trend = "激进多头主导，短期持续看涨" if cvd > 0 else "激进空头主导，短期持续看跌"
                    return True, (
                        f"[strength={strength}/10] TYPE_B 机构级 CVD 异常流向 [绝对动量突破] "
                        f"(强度: {cvd:.3f} | 累计差值: {cvd_vol_delta:.1f} | 成交量: {cvd_vol:.1f} | "
                        f"窗口: {cvd_lookback_candles}k @ {micro_int} | 阈值: {cvd_threshold:.2f}) | "
                        f"**趋势推演: {trend}**"
                    )

        # --- [Priority 3] Retail sentiment extremes (ambient) ---
        ls = sent.get('ls_ratio_micro', 1.0)
        if ls > self.regime_cfg['imbalance']['long_short_imbalance_ratio'] or \
           ls < self.regime_cfg['imbalance']['short_heavy_imbalance_ratio']:
            now = datetime.now(timezone.utc)
            if self._check_state_lock("AMBIENT_LS_RATIO", now):
                strength = max(1, min(10, int(
                    max(ls / max(self.regime_cfg['imbalance']['long_short_imbalance_ratio'], 0.01),
                        self.regime_cfg['imbalance']['short_heavy_imbalance_ratio'] / max(ls, 0.01)) * 3
                )))
                trend = "多头拥挤，防范爆多踩踏风险" if ls > 1.0 else "空头拥挤，防范空头回补/空头挤压爆发"
                return True, (
                    f"[strength={strength}/10] TYPE_B 零售情绪过度扩张 [反向指标提醒] "
                    f"(多空比: {ls:.2f}) | **趋势推演: {trend}**"
                )

        funding = sent.get('funding_rate', 0.0)
        if abs(funding) > self.regime_cfg['micro_sentiment']['funding_extreme_threshold']:
            now = datetime.now(timezone.utc)
            if self._check_state_lock("AMBIENT_FUNDING", now):
                strength = max(1, min(10, int(
                    (abs(funding) / max(abs(self.regime_cfg['micro_sentiment']['funding_extreme_threshold']), 1e-9)) * 4
                )))
                trend = "多头过热，警惕力竭回撤" if funding > 0 else "空头过热，警惕力竭反弹"
                return True, (
                    f"[strength={strength}/10] TYPE_B 资金费率极端值 [情绪偏振检测] "
                    f"(费率: {funding:.5f}) | **趋势推演: {trend}**"
                )

        return False, None

    def _check_type_c(self, curr: Dict[str, Any], prev: Optional[Dict[str, Any]] = None) -> Tuple[bool, Optional[str]]:
        """TYPE_C (Structural): boundary collision, POC magnet, or liquidation magnet"""
        now = datetime.now(timezone.utc)
        topo = curr['volume_profile']
        atr = curr['price_dynamics']['atr_macro']
        price = curr['price_dynamics']['current_price']
        part = curr['market_regime']['volume_participation_ratio']

        # Directional context: is price moving toward or away from the structure?
        approaching_from_below = False
        approaching_from_above = False
        if prev:
            prev_price = prev['price_dynamics']['current_price']
            approaching_from_below = price > prev_price  # moving up
            approaching_from_above = price < prev_price  # moving down

        dist_vh = abs(price - topo['vah']) / atr if atr > 0 else float('inf')
        dist_val = abs(price - topo['val']) / atr if atr > 0 else float('inf')
        dist_poc = abs(price - topo['poc']) / atr if atr > 0 else float('inf')

        vah_val_threshold = self.sniper_cfg['proximity']['proximity_vah_val_atr']
        poc_trigger_threshold = self.sniper_cfg['proximity']['proximity_poc_atr']
        liq_trigger_threshold = self.sniper_cfg['proximity']['proximity_liq_atr']

        # ── VAH/VAL boundary test ────────────────────────────────────
        nearest_boundary = "VAH" if dist_vh < dist_val else "VAL"
        nearest_dist = min(dist_vh, dist_val)

        if nearest_dist < vah_val_threshold and part > self.regime_cfg['volume']['min_volume_participation_ratio']:
            # Directional gate: only trigger if approaching the boundary
            approaching = (nearest_boundary == "VAH" and approaching_from_below) or \
                          (nearest_boundary == "VAL" and approaching_from_above)
            if prev and not approaching:
                pass  # retreating from boundary — skip
            elif self._check_state_lock(f"BOUNDARY_{nearest_boundary}", now):
                strength = max(1, min(10, int((vah_val_threshold / max(nearest_dist, 0.01)) * 4)))
                direction_note = "向上测试" if nearest_boundary == "VAH" else "向下测试"
                trend = (
                    f"测试 {nearest_boundary} 关键阻力，若无法带量突破则倾向于回转 POC"
                    if nearest_boundary == "VAH" else
                    f"测试 {nearest_boundary} 关键支撑，若放量跌破则下方空间打开"
                )
                return True, (
                    f"[strength={strength}/10] TYPE_C 携量撞墙 [{direction_note}] "
                    f"距离 {nearest_boundary}={nearest_dist:.2f} ATR (阈值: {vah_val_threshold:.2f}) | "
                    f"**趋势推演: {trend}**"
                )

        # ── POC magnet ──────────────────────────────────────────────
        if dist_poc < poc_trigger_threshold:
            approaching_poc = (price < topo['poc'] and approaching_from_below) or \
                              (price > topo['poc'] and approaching_from_above)
            if prev and not approaching_poc:
                pass  # retreating from POC — skip
            elif self._check_state_lock("POC_MAGNET", now):
                strength = max(1, min(10, int((poc_trigger_threshold / max(dist_poc, 0.01)) * 3)))
                return True, (
                    f"[strength={strength}/10] TYPE_C POC 磁吸/回踩 [引力回归测试] "
                    f"距离 POC={dist_poc:.2f} ATR (阈值: {poc_trigger_threshold:.2f}) | "
                    f"**趋势推演: 引力回归中，价格倾向于在成交最密集区域震荡或企稳**"
                )

        # ── Liquidation cluster magnets ─────────────────────────────
        liq_clusters = curr['sentiment_signals'].get('liquidation_clusters')
        if liq_clusters and isinstance(liq_clusters, dict):
            for cluster in liq_clusters.get('long_liquidation', []):
                p = float(cluster['price'])
                dist_atr = abs(price - p) / atr if atr > 0 else float('inf')
                if dist_atr < liq_trigger_threshold:
                    # Long liquidation magnet: price moves DOWN to sweep longs
                    if prev and not approaching_from_above:
                        continue
                    if self._check_state_lock(f"LONG_LIQ_{int(p/100)*100}", now):
                        strength = max(1, min(10, int((liq_trigger_threshold / max(dist_atr, 0.01)) * 3)))
                        return True, (
                            f"[strength={strength}/10] TYPE_C 多头爆仓磁吸 [支撑位测试] "
                            f"价格={p:.2f}, 距离={dist_atr:.2f} ATR (阈值: {liq_trigger_threshold:.2f}) | "
                            f"**趋势推演: 多头清算磁吸，价格大概率下探以清除多头流动性点位**"
                        )

            for cluster in liq_clusters.get('short_liquidation', []):
                p = float(cluster['price'])
                dist_atr = abs(price - p) / atr if atr > 0 else float('inf')
                if dist_atr < liq_trigger_threshold:
                    # Short liquidation magnet: price moves UP to squeeze shorts
                    if prev and not approaching_from_below:
                        continue
                    if self._check_state_lock(f"SHORT_LIQ_{int(p/100)*100}", now):
                        strength = max(1, min(10, int((liq_trigger_threshold / max(dist_atr, 0.01)) * 3)))
                        return True, (
                            f"[strength={strength}/10] TYPE_C 空头爆仓磁吸 [挤压位测试] "
                            f"价格={p:.2f}, 距离={dist_atr:.2f} ATR (阈值: {liq_trigger_threshold:.2f}) | "
                            f"**趋势推演: 空头清算磁吸，价格大概率上攻以清除空头流动性点位**"
                        )

        return False, None

    def set_triggered(self, t_type: str):
        """Sets the last trigger time for physical cooldown."""
        self.last_trigger_time = datetime.now(timezone.utc)
