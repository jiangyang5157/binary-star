import os
from typing import Dict, Any, Tuple, Optional, List
from datetime import datetime, timezone

from src.utils.path_utils import resolve_project_root
from src.utils.logger_utils import setup_logger

logger = setup_logger(__name__)

class SniperTrigger:
    """
    The Decision Node of the 'Sniper Mode' (v7.1).
    
    ZERO-ENTROPY: This class is now completely standalone. 
    It no longer loads its own config file. Instead, it extracts 
    all 100% of its thresholds and cooldowns from strategy_config.yaml.
    """
    
    def __init__(self):
        self.last_trigger_time: Optional[datetime] = None
        
        # v7.1: Absolute DNA Convergence
        # All monitoring sensitivity is physically identical to strategy parameters.
        from src.utils.pipeline_utils import load_combined_config, load_global_config
        self.strat_cfg = load_combined_config()
        self.global_cfg = load_global_config()
        self.regime_cfg = self.strat_cfg['regime_parameters']
        
        # v7.1: EXPLICIT CONFIG ENFORCEMENT
        self.sniper_cfg = self.global_cfg['sniper']
        
        # Derive cooldown from micro-context (e.g., 15m) + Multiplier
        micro_interval = self.strat_cfg['analysis_window']['micro_context']['time_interval']
        base_cooldown = self._parse_interval_to_minutes(micro_interval)
        self.cooldown_minutes = base_cooldown * self.sniper_cfg['pulse_cooldown_multiplier']
        
        logger.info(f"SniperTrigger: Physically standalone. Cooldown={self.cooldown_minutes}m (Mult: {self.sniper_cfg['pulse_cooldown_multiplier']}).")

    def _parse_interval_to_minutes(self, interval_str: str) -> float:
        """Parses '15m', '1h' etc. into float minutes."""
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

        # 1. Evaluate DNA Traps (Type A -> B -> C)
        # v6.71: CHAOS_MUTE (Extreme Volatility Protection)
        vol = current_metrics['price_dynamics']['volatility_intensity_index']
        if vol > self.regime_cfg['volatility_extreme_ratio']:
            if self.last_trigger_time:
                elapsed = (now - self.last_trigger_time).total_seconds() / 60.0
                chaos_mult = self.sniper_cfg['chaos_cooldown_multiplier']
                if elapsed < (self.cooldown_minutes * chaos_mult):
                    return False, None, f"CHAOS_MUTE (Extreme Volatility: {vol:.2f} | Cooldown x{chaos_mult})"

        checks = [
            (self._check_type_a, "TYPE_A (Breakout)"),
            (self._check_type_b, "TYPE_B (Asymmetry)"),
            (self._check_type_c, "TYPE_C (Structural)")
        ]

        for check_fn, type_tag in checks:
            is_hit, reason = check_fn(current_metrics, prev_metrics)
            if is_hit:
                logger.info(f"SNIPER WAKE UP! [{type_tag}] | {reason}")
                return True, type_tag, reason

        return False, None, "SLEEPING"

    def _check_state_lock(self, lock_key: str, now: datetime) -> bool:
        """Returns True if permitted to trigger, False if muted by state lock."""
        if not hasattr(self, 'state_locks'):
            self.state_locks = {}
        cooldown_hours = self.sniper_cfg['state_lockout_hours']
        
        if lock_key in self.state_locks:
            elapsed_hours = (now - self.state_locks[lock_key]).total_seconds() / 3600.0
            if elapsed_hours < cooldown_hours:
                return False
        self.state_locks[lock_key] = now
        return True

    def _check_type_a(self, curr: Dict[str, Any], prev: Optional[Dict[str, Any]] = None) -> Tuple[bool, Optional[str]]:
        """势能破局: [波动率爆发+量能突增] OR [极致物理挤压]"""
        vol = curr['price_dynamics']['volatility_intensity_index']
        part = curr['market_regime']['volume_participation_ratio']
        squeeze = curr['market_regime']['squeeze_factor']
        
        # 1. 动能释放 (Volatility Expansion)
        vol_threshold = self.regime_cfg['volatility_baseline_ratio']
        is_vol_hit = vol > vol_threshold
        
        part_threshold = self.regime_cfg['volume_participation_threshold']
        is_volume_hit = part > part_threshold
        
        # 2. 势能蓄力 (Physical Squeeze)
        squeeze_mult = self.sniper_cfg['squeeze_trigger_multiplier']
        squeeze_threshold = self.regime_cfg['squeeze_threshold'] * squeeze_mult
        is_squeeze_hit = squeeze < squeeze_threshold
        
        # 逻辑分支：要么是携量暴走，要么是极致静音收缩
        if (is_vol_hit and is_volume_hit) or is_squeeze_hit:
            reason = "势能破局: "
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
        """动能失衡: CVD 脉冲/背离、资金费极值或多空比极值"""
        sent = curr.get('sentiment_signals', {})
        
        # 1. 基准阈值直接对接 Agent，实现 1:1 无损映射 (零熵架构)
        cvd_threshold = self.regime_cfg['cvd_intensity_threshold']
        cvd = sent.get('cvd_intensity_ratio', 0.0)
        
        # --- [极高优] 动态微观事件探针 (Event-Driven Dynamics) ---
        if prev:
            prev_sent = prev.get('sentiment_signals', {})
            prev_cvd = prev_sent.get('cvd_intensity_ratio', 0.0)
            
            cvd_delta_raw = cvd - prev_cvd
            cvd_delta_abs = abs(cvd_delta_raw)
            
            # A. 吸筹/派发背离 (Divergence) - v6.71: Tick Delta Acceleration
            divergence_threshold = self.sniper_cfg['cvd_divergence_tick_delta']
            
            if cvd_delta_abs > divergence_threshold:
                curr_price = curr['price_dynamics']['current_price']
                prev_price = prev['price_dynamics']['current_price']
                price_delta = curr_price - prev_price
                
                # Bullish: Price down, CVD up | Bearish: Price up, CVD down
                if (price_delta > 0 and cvd_delta_raw < 0) or (price_delta < 0 and cvd_delta_raw > 0):
                    return True, f"CVD Acceleration Divergence (Price:{price_delta:.1f}, CVD Delta:{cvd_delta_raw:.3f} | Threshold: {divergence_threshold})"

            # B. 暴力大单脉冲 (Impulse) - v6.71: Tick Delta Acceleration
            pulse_threshold = self.sniper_cfg['cvd_impulse_tick_delta']
            if cvd_delta_abs > pulse_threshold:
                return True, f"CVD Impulse Detected (Delta: {cvd_delta_abs:.3f} | Threshold: {pulse_threshold})"

        # --- [高优] 全局绝对动量锁定 (Absolute Momentum) ---
        if abs(cvd) > cvd_threshold:
            should_trigger = True
            if prev:
                # 必须保持在显着增长（当前比上一次强 x 阻尼系数），否则进入静默，防止持续报警
                growth_ratio = self.sniper_cfg['cvd_growth_significance_ratio']
                is_significant = abs(cvd) > abs(prev_cvd) * growth_ratio
                if not is_significant:
                    should_trigger = False
                    
            if should_trigger:
                cvd_vol_delta = sent.get('cvd_volume_delta', 0.0)
                cvd_vol = sent.get('cvd_total_volume', 0.0)
                cvd_lookback_candles = sent.get('cvd_lookback_candles', 0)
                micro_int = self.strat_cfg['analysis_window']['micro_context']['time_interval']
                return True, (
                    f"Institutional CVD flow (Intensity: {cvd:.3f} | "
                    f"Delta: {cvd_vol_delta:.1f} | Vol: {cvd_vol:.1f} | "
                    f"Window: {cvd_lookback_candles}k @ {micro_int} | Threshold: {cvd_threshold:.2f})"
                )

        # --- [常态保底] 散户情绪与资金环境极值 (Ambient Sentiment) ---
        ls = sent.get('ls_ratio_micro', 1.0)
        if ls > self.regime_cfg['long_short_imbalance_ratio'] or \
           ls < self.regime_cfg['short_heavy_imbalance_ratio']:
            now = datetime.now(timezone.utc)
            if self._check_state_lock("AMBIENT_LS_RATIO", now):
                return True, f"Retail Sentiment Over-extension (L/S: {ls:.2f})"

        funding = sent.get('funding_rate', 0.0)
        if abs(funding) > self.regime_cfg['funding_extreme_threshold']:
            now = datetime.now(timezone.utc)
            if self._check_state_lock("AMBIENT_FUNDING", now):
                return True, f"Funding Rate Extreme (Rate: {funding:.5f})"

        return False, None

    def _check_type_c(self, curr: Dict[str, Any], prev: Optional[Dict[str, Any]] = None) -> Tuple[bool, Optional[str]]:
        """关键拓扑碰撞: 边界极压 or 清算磁吸"""
        now = datetime.now(timezone.utc)
        topo = curr['volume_profile']
        atr = curr['price_dynamics']['atr_macro']
        price = curr['price_dynamics']['current_price']
        part = curr['market_regime']['volume_participation_ratio']
        
        # DNA Mapping: boundary_dist -> structural_proximity_threshold (v6.80 Granular Multipliers)
        dist_vh = abs(price - topo['vah']) / atr if atr > 0 else float('inf')
        dist_val = abs(price - topo['val']) / atr if atr > 0 else float('inf')
        dist_poc = abs(price - topo['poc']) / atr if atr > 0 else float('inf')

        base_struct_threshold = self.regime_cfg['structural_proximity_threshold']
        
        vah_val_threshold = base_struct_threshold * self.sniper_cfg['vah_val_trigger_multiplier']
        poc_trigger_threshold = base_struct_threshold * self.sniper_cfg['poc_trigger_multiplier']
        liq_trigger_threshold = base_struct_threshold * self.sniper_cfg['liq_trigger_multiplier']

        if min(dist_vh, dist_val) < vah_val_threshold and \
           part > self.regime_cfg['min_volume_participation_ratio']:
            side = "VAH" if dist_vh < dist_val else "VAL"
            if self._check_state_lock(f"BOUNDARY_{side}", now):
                return True, f"携量撞墙 (Heavy Boundary Test): Dist to {side}={min(dist_vh, dist_val):.2f} ATR (Threshold: {vah_val_threshold:.2f})"

        if dist_poc < poc_trigger_threshold:
            if self._check_state_lock("POC_MAGNET", now):
                return True, f"POC 磁吸/回踩 (Gravity Test): Dist to POC={dist_poc:.2f} ATR (Threshold: {poc_trigger_threshold:.2f})"

        # DNA Mapping: liquidation_magnet -> liq_trigger_threshold (v7.0 Aligned with granular multiplier)
        liq_clusters = curr['sentiment_signals'].get('liquidation_clusters')
        if liq_clusters and isinstance(liq_clusters, dict):
            # Process Long Liquidations (Support magnets)
            for cluster in liq_clusters.get('long_liquidation', []):
                p = float(cluster['price'])
                dist_atr = abs(price - p) / atr if atr > 0 else float('inf')
                if dist_atr < liq_trigger_threshold:
                    if self._check_state_lock(f"LONG_LIQ_{int(p/100)*100}", now):
                        return True, f"多头爆仓磁吸 (Long Liq Magnet - Support Test): Price={p:.2f}, Dist={dist_atr:.2f} ATR (Threshold: {liq_trigger_threshold:.2f})"
            
            # Process Short Liquidations (Squeeze magnets)
            for cluster in liq_clusters.get('short_liquidation', []):
                p = float(cluster['price'])
                dist_atr = abs(price - p) / atr if atr > 0 else float('inf')
                if dist_atr < liq_trigger_threshold:
                    if self._check_state_lock(f"SHORT_LIQ_{int(p/100)*100}", now):
                        return True, f"空头爆仓磁吸 (Short Liq Magnet - Squeeze Test): Price={p:.2f}, Dist={dist_atr:.2f} ATR (Threshold: {liq_trigger_threshold:.2f})"

        return False, None

    def set_triggered(self, t_type: str):
        """Sets the last trigger time for physical cooldown."""
        self.last_trigger_time = datetime.now(timezone.utc)
