import os
from typing import Dict, Any, Tuple, Optional, List
from datetime import datetime, timezone

from src.utils.path_utils import resolve_project_root
from src.utils.logger_utils import setup_logger

logger = setup_logger(__name__)

class SniperTrigger:
    """
    The Decision Node of the 'Sniper Mode' (v6.40).
    
    ZERO-ENTROPY: This class is now completely standalone. 
    It no longer loads its own config file. Instead, it extracts 
    all 100% of its thresholds and cooldowns from strategy_config.yaml.
    """
    
    def __init__(self):
        self.last_trigger_time: Optional[datetime] = None
        
        # v6.40: Absolute DNA Convergence
        # All monitoring sensitivity is physically identical to strategy parameters.
        from src.utils.pipeline_utils import load_combined_config, load_global_config
        self.strat_cfg = load_combined_config()
        self.global_cfg = load_global_config()
        self.regime_cfg = self.strat_cfg['regime_parameters']
        
        # v6.70: EXPLICIT CONFIG ENFORCEMENT
        # If sniper_configuration is missing from global_config.yaml, this will fail intentionally.
        self.sniper_cfg = self.global_cfg['sniper_configuration']
        
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
        checks = [
            (self._check_type_a, "TYPE_A (Breakout)"),
            (self._check_type_b, "TYPE_B (Asymmetry)"),
            (self._check_type_c, "TYPE_C (Structural)")
        ]

        for check_fn, type_tag in checks:
            is_hit, reason = check_fn(current_metrics, prev_metrics)
            if is_hit:
                return True, type_tag, reason

        return False, None, "SLEEPING"

    def _check_type_a(self, curr: Dict[str, Any], prev: Optional[Dict[str, Any]] = None) -> Tuple[bool, Optional[str]]:
        """势能破局: [波动率爆发] AND ([量能突增] OR [极致挤压])"""
        vol = curr['price_dynamics']['volatility_intensity_index']
        part = curr['market_regime']['volume_participation_ratio']
        squeeze = curr['market_regime'].get('squeeze_factor', 1.0)
        
        # 1. 势 (Volatility) - Required for Confluence
        vol_threshold = self.regime_cfg['volatility_baseline_ratio']
        is_vol_hit = vol > vol_threshold
        
        # 2. 能 & 局 (Volume & Squeeze) - One of these must accompany Volatility
        part_threshold = self.regime_cfg['volume_participation_threshold']
        is_volume_hit = part > part_threshold
        
        squeeze_threshold = self.regime_cfg['squeeze_threshold']
        is_squeeze_hit = squeeze < squeeze_threshold
        
        if is_vol_hit and (is_volume_hit or is_squeeze_hit):
            reason = f"势能共振 (Breakout): Vol={vol:.2f} (> {vol_threshold:.2f})"
            if is_volume_hit: reason += f" | Volume Ratio={part:.2f}"
            if is_squeeze_hit: reason += f" | Squeeze Factor={squeeze:.2f}"
            return True, reason
             
        return False, None

    def _check_type_b(self, curr: Dict[str, Any], prev: Optional[Dict[str, Any]] = None) -> Tuple[bool, Optional[str]]:
        """动能失衡: CVD 脉冲/背离、资金费极值或多空比极值"""
        sent = curr.get('sentiment_signals', {})
        
        # 1. 存量/极值检测 (CVD & LS Ratio)
        cvd = sent.get('cvd_intensity_ratio', 0.0)
        cvd_mult = self.sniper_cfg['cvd_threshold_multiplier']
        cvd_threshold = self.regime_cfg['cvd_intensity_threshold'] * cvd_mult
        
        cvd_net = sent.get('cvd_net_delta', 0.0)
        cvd_vol = sent.get('cvd_total_volume', 0.0)
        cvd_lookback = sent.get('cvd_lookback_candles', 0)
        micro_int = self.strat_cfg['analysis_window']['micro_context']['time_interval']
        
        if abs(cvd) > cvd_threshold:
            # Momentum Locking: If we have previous metrics, only re-trigger if intensity is INCREASING or FLIPPED
            should_trigger = True
            if prev:
                prev_sent = prev.get('sentiment_signals', {})
                prev_cvd = prev_sent.get('cvd_intensity_ratio', 0.0)
                
                # Condition: Current Intensity is stronger than previous (Simplified: ANY increase) OR direction flipped
                is_increasing = abs(cvd) > abs(prev_cvd)
                is_flipped = (cvd > 0 and prev_cvd < 0) or (cvd < 0 and prev_cvd > 0)
                
                if not (is_increasing or is_flipped):
                    return False, f"MOMENTUM_LOCK (Intensity stable: {cvd:.3f} vs {prev_cvd:.3f})"
                    
            if should_trigger:
                reason = (
                    f"Institutional CVD flow (Intensity: {cvd:.3f} | "
                    f"Delta: {cvd_net:.1f} | Vol: {cvd_vol:.1f} | "
                    f"Window: {cvd_lookback}k @ {micro_int} | Threshold: {cvd_threshold:.2f})"
                )
                return True, reason

        # DNA Mapping: ls_ratio_micro from sentiment_signals
        ls = sent.get('ls_ratio_micro', 1.0)
        if ls > self.regime_cfg['long_short_imbalance_ratio'] or \
           ls < self.regime_cfg['short_heavy_imbalance_ratio']:
            return True, f"Retail Sentiment Over-extension (L/S: {ls:.2f})"

        # 2. 资金费压力 (Funding Rate Pressure) - [NEW v2.0]
        funding = sent.get('funding_rate', 0.0)
        if abs(funding) > self.regime_cfg['funding_extreme_threshold']:
            return True, f"Funding Rate Extreme (Rate: {funding:.5f})"

        if prev:
            prev_sent = prev.get('sentiment_signals', {})
            prev_cvd = prev_sent.get('cvd_intensity_ratio', 0.0)
            
            # 3. CVD 脉冲 (CVD Dynamic Impulse) - [NEW v2.0]
            # Trigger on sudden taker surge even if absolute threshold isn't hit
            cvd_delta = abs(cvd - prev_cvd)
            pulse_ratio = self.sniper_cfg['cvd_impulse_intensity_ratio']
            pulse_threshold = (self.regime_cfg['cvd_intensity_threshold'] * pulse_ratio) * cvd_mult
            if cvd_delta > pulse_threshold:
                return True, f"CVD Impulse Detected (Delta: {cvd_delta:.3f} | Ratio: {pulse_ratio} | Threshold: {pulse_threshold:.3f})"

            # 4. 吸筹/派发背离 (CVD Divergence Detection) - [NEW v2.0]
            curr_price = curr['price_dynamics']['current_price']
            prev_price = prev['price_dynamics']['current_price']
            price_delta = curr_price - prev_price
            cvd_delta_raw = cvd - prev_cvd

            # Only trigger if CVD movement is non-trivial (ratio x of strategy threshold * mult)
            div_ratio = self.sniper_cfg['cvd_divergence_intensity_ratio']
            divergence_threshold = (self.regime_cfg['cvd_intensity_threshold'] * div_ratio) * cvd_mult
            if abs(cvd_delta_raw) > divergence_threshold:
                # Bullish Divergence: Price down, CVD up (Absorption)
                # Bearish Divergence: Price up, CVD down (Distribution)
                if (price_delta > 0 and cvd_delta_raw < 0) or \
                   (price_delta < 0 and cvd_delta_raw > 0):
                    return True, f"CVD/Price Divergence (Price:{price_delta:.1f}, CVD:{cvd_delta_raw:.3f} | Ratio: {div_ratio})"
        
        return False, None

    def _check_type_c(self, curr: Dict[str, Any], prev: Optional[Dict[str, Any]] = None) -> Tuple[bool, Optional[str]]:
        """关键拓扑碰撞: 边界极压 or 清算磁吸"""
        topo = curr['volume_profile']
        atr = curr['price_dynamics']['atr_macro']
        price = curr['price_dynamics']['current_price']
        part = curr['market_regime']['volume_participation_ratio']
        
        # DNA Mapping: boundary_dist -> structural_proximity_threshold
        dist_vh = abs(price - topo['vah']) / atr if atr > 0 else float('inf')
        dist_val = abs(price - topo['val']) / atr if atr > 0 else float('inf')
        
        # DNA Mapping: boundary_dist -> min_volume_participation_ratio (Relaxed for Sniper)
        if min(dist_vh, dist_val) < self.regime_cfg['structural_proximity_threshold'] and \
           part > self.regime_cfg['min_volume_participation_ratio']:
            side = "VAH" if dist_vh < dist_val else "VAL"
            return True, f"携量撞墙 (Heavy Boundary Test): Dist to {side}={min(dist_vh, dist_val):.2f} ATR"

        # DNA Mapping: liquidation_magnet -> structural_proximity_threshold
        liq_clusters = curr['sentiment_signals'].get('liquidation_clusters')
        if liq_clusters:
            for p_str, c_data in liq_clusters.items():
                p = float(p_str)
                dist_atr = abs(price - p) / atr if atr > 0 else float('inf')
                if dist_atr < self.regime_cfg['structural_proximity_threshold']:
                    return True, f"爆仓簇磁吸 (Liquidation Magnet): Price={p_str}, Dist={dist_atr:.2f} ATR"
                    
        return False, None

    def set_triggered(self, t_type: str):
        """Sets the last trigger time for physical cooldown."""
        self.last_trigger_time = datetime.now(timezone.utc)
