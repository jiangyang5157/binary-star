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
        from src.utils.pipeline_utils import load_combined_config
        self.strat_cfg = load_combined_config()
        self.regime_cfg = self.strat_cfg['regime_parameters']
        
        # Derive cooldown from micro-context (e.g., 15m)
        micro_interval = self.strat_cfg['analysis_window']['micro_context']['time_interval']
        self.cooldown_minutes = self._parse_interval_to_minutes(micro_interval)
        
        logger.info(f"SniperTrigger: Physically standalone. Cooldown={self.cooldown_minutes}m.")

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
            is_hit, reason = check_fn(current_metrics)
            if is_hit:
                return True, type_tag, reason

        return False, None, "SLEEPING"

    def _check_type_a(self, curr: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
        """势能破局: 波动率点火 or 极致挤压"""
        vol = curr['price_dynamics']['volatility_intensity_index']
        part = curr['market_regime']['volume_participation_ratio']
        
        # DNA Mapping: volatility_ignition -> volatility_baseline_ratio
        if vol > self.regime_cfg['volatility_baseline_ratio'] and \
           part > self.regime_cfg['volume_participation_threshold']:
            return True, f"Volatility Ignition (Ratio: {vol:.2f})"
        
        # DNA Mapping: squeeze_factor -> squeeze_threshold
        squeeze = curr['market_regime'].get('squeeze_factor', 1.0)
        if squeeze < self.regime_cfg['squeeze_threshold']:
             return True, f"极致挤压 (Squeeze): Factor={squeeze:.2f}"
             
        return False, None

    def _check_type_b(self, curr: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
        """动能失衡: CVD 机构流或多空比极值"""
        cvd = abs(curr['market_regime'].get('cvd_intensity', 0.0))
        
        # DNA Mapping: institutional_cvd -> cvd_intensity_threshold
        if cvd > self.regime_cfg['cvd_intensity_threshold']:
            return True, f"Institutional CVD flow (Intensity: {cvd:.3f})"
            
        # DNA Mapping: retail_ls -> long_short_imbalance_ratio
        ls = curr['market_regime'].get('long_short_ratio', 1.0)
        if ls > self.regime_cfg['long_short_imbalance_ratio'] or \
           ls < self.regime_cfg['short_heavy_imbalance_ratio']:
            return True, f"Retail Sentiment Over-extension (L/S: {ls:.2f})"
        
        return False, None

    def _check_type_c(self, curr: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
        """关键拓扑碰撞: 边界极压 or 清算磁吸"""
        topo = curr['volume_profile']
        atr = curr['price_dynamics']['atr_macro']
        price = curr['price_dynamics']['current_price']
        part = curr['market_regime']['volume_participation_ratio']
        
        # DNA Mapping: boundary_dist -> structural_proximity_threshold
        dist_vh = abs(price - topo['vah']) / atr if atr > 0 else float('inf')
        dist_val = abs(price - topo['val']) / atr if atr > 0 else float('inf')
        
        if min(dist_vh, dist_val) < self.regime_cfg['structural_proximity_threshold'] and \
           part > self.regime_cfg['volume_participation_threshold']:
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
