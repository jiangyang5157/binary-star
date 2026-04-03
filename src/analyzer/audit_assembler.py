import os
import json
from dataclasses import dataclass
from typing import Dict, Any, List, Optional
import datetime

from src.utils.pipeline_utils import safe_format
from src.utils.path_utils import resolve_project_root
from src.utils.math_utils import MathTools

from src.utils.logger_utils import setup_logger
logger = setup_logger(__name__)

@dataclass(frozen=True)
class AuditReviewConfig:
    """Dataclass for type-safe Audit Review configuration."""
    macro_interval: str
    micro_interval: str
    strategy_intent: str
    regime_anchor_drift_threshold: float
    audit_review: Dict[str, Any]

    @classmethod
    def from_dict(cls, cfg: Dict[str, Any]) -> "AuditReviewConfig":
        """Factory method for strategic config."""
        sampling = cfg['analysis_window']
        topography = cfg['topography_parameters']
        regime = cfg['regime_parameters']
        audit_node = cfg['audit_review']
        
        return cls(
            macro_interval=str(sampling['macro_context']['time_interval']),
            micro_interval=str(sampling['micro_context']['time_interval']),
            strategy_intent=str(cfg.get('strategy_intent', "")),
            regime_anchor_drift_threshold=float(regime['anchor_drift_threshold']),
            audit_review=audit_node
        )

class AuditAssembler:
    """The Post-Execution Forensic Data Reporter.

    Aggregates trade execution metrics, price-action outcomes, and 
    structural alignments to provide a deterministic baseline for the Evolver.
    """
    def __init__(self, config: AuditReviewConfig):
        """Initializes the Assembler with forensic configurations.

        Args:
            config: The type-safe AuditReviewConfig object.
        """
        self.config = config

    def calculate_outcome(
        self, 
        klines: List[List[Any]], 
        entry_price: float, 
        strategy: Dict[str, Any],
        atr_macro_t0: float, 
        atr_macro_t1: float, 
        long_short_ratio_macro_t0: float,
        long_short_ratio_macro_t1: float,
        interval_hours: float
    ) -> Dict[str, Any]:
        """Analyzes klines to determine the actual market outcome vs strategy hypothesis.

        Args:
            klines: Raw OHLCV data for the audit window.
            entry_price: Price at the time of the session (T0).
            strategy: The original strategy/session JSON.
            atr_macro_t0: ATR at session start.
            atr_macro_t1: ATR at audit end.
            interval_hours: Duration of a single kline in hours.

        Returns:
            A dictionary containing the parsed forensic outcome.
        """
        if not klines:
            return {"error": "EMPTY_KLINES", "tp_sl_result": "N/A"}
        
        # Structure: [OpenTime, Open, High, Low, Close, Volume, CloseTime, ...]
        highs = [float(k[2]) for k in klines]
        lows = [float(k[3]) for k in klines]
        closes = [float(k[4]) for k in klines]
        
        # v6.5 Optimization: Core Physical Snapshots
        max_price = max(highs)
        min_price = min(lows)
        final_close = closes[-1]
        max_atr = max(atr_macro_t0, atr_macro_t1)
        
        market_forensics = {
            "planned_entry_price": entry_price,
            "price_at_t0": entry_price,
            "price_at_t1": final_close,
            "window_high_price": max_price,
            "window_low_price": min_price,
            "window_volatility_intensity_atr": round((max_price - min_price) / max_atr, 4) if max_atr > 0 else 0,
            "price_move_pct": round(((final_close - entry_price) / entry_price) * 100, 2)
        }

        # v6.5: Regime Drift Analysis
        regime_forensics = {
            "volatility_drift_pct": round(((atr_macro_t1 - atr_macro_t0) / atr_macro_t0 * 100), 2) if atr_macro_t0 > 0 else 0,
            "sentiment_drift": round(long_short_ratio_macro_t1 - long_short_ratio_macro_t0, 4)
        }

        # 2. Result Payload Base
        result = {
            "tp_sl_result": "NEITHER",
            "is_filled": False,
            "market_forensics": market_forensics,
            "regime_forensics": regime_forensics,
            "execution_forensics": {},
            "trade_execution_metrics": {
                "duration_candles": len(klines),
                "actual_hours": round(len(klines) * interval_hours, 2),
                "mae_stress_tier": "N/A"
            }
        }
        
        final_decision = strategy.get('final_decision', {})
        opinion = final_decision.get('opinion', 'NEUTRAL').upper()
        
        if opinion in ('BULLISH', 'BEARISH'):
            tactical = final_decision.get('tactical_parameters', {})
            target_entry = float(tactical.get('entry', entry_price))
            tp = float(tactical.get('take_profit', 0))
            sl = float(tactical.get('stop_loss', 0))
            
            # Theoretical Drift Calculation (Physics vs Intent)
            entry_drift = (min_price - target_entry) if opinion == 'BULLISH' else (target_entry - max_price)
            entry_drift_atr = round(entry_drift / max_atr, 4) if max_atr > 0 else 0
            
            theoretical_mae = max(0, target_entry - min_price) if opinion == 'BULLISH' else max(0, max_price - target_entry)
            theoretical_mfe = max(0, max_price - target_entry) if opinion == 'BULLISH' else max(0, target_entry - min_price)

            unfilled_proximity_atr_limit = float(self.config.audit_review['unfilled_proximity_atr_limit'])
            result["execution_forensics"] = {
                "entry_drift_atr": entry_drift_atr,
                "theoretical_mae_atr": round(theoretical_mae / max_atr, 4) if max_atr > 0 else 0,
                "theoretical_mfe_atr": round(theoretical_mfe / max_atr, 4) if max_atr > 0 else 0,
                "is_near_miss": 0 < entry_drift_atr < unfilled_proximity_atr_limit
            }

            # v6.13 Schema Relocation (Indicators now grouped in market_forensics)
            market_forensics["planned_entry_price"] = target_entry
            market_forensics["total_price_change_pct"] = market_forensics["price_move_pct"]
            market_forensics["max_favorable_runup_pct"] = round((theoretical_mfe / entry_price) * 100, 2) if entry_price > 0 else 0
            market_forensics["max_adverse_drawdown_pct"] = round((theoretical_mae / entry_price) * 100, 2) if entry_price > 0 else 0

            if tp > 0 and sl > 0:
                entry_hit = False
                hit_result = "NEITHER"
                hit_index = len(klines)
                max_after, min_after = -float('inf'), float('inf')
                
                for i, k in enumerate(klines):
                    high, low = float(k[2]), float(k[3])
                    if not entry_hit:
                        if (opinion == 'BULLISH' and low <= target_entry) or \
                           (opinion == 'BEARISH' and high >= target_entry):
                            entry_hit = True
                            max_after, min_after = high, low
                    
                    if entry_hit:
                        max_after, min_after = max(max_after, high), min(min_after, low)
                        if hit_result == "NEITHER":
                            if opinion == 'BULLISH':
                                if low <= sl: hit_result = "SL_HIT"; hit_index = i + 1
                                elif high >= tp: hit_result = "TP_HIT"; hit_index = i + 1
                            else: # BEARISH
                                if high >= sl: hit_result = "SL_HIT"; hit_index = i + 1
                                elif low <= tp: hit_result = "TP_HIT"; hit_index = i + 1
                
                if entry_hit:
                    tp_dist = abs(tp - target_entry)
                    mae = max(0, target_entry - min_after) if opinion == 'BULLISH' else max(0, max_after - target_entry)
                    mfe = max(0, max_after - target_entry) if opinion == 'BULLISH' else max(0, target_entry - min_after)
                    
                    mae_stress = MathTools.calculate_mae_stress(mae, max_atr)
                    mfe_eff = (mfe / tp_dist * 100) if tp_dist > 0 else 0
                    
                    # Explicitly extract estimated hours without fallback to avoid logic pollution
                    est_hours = float(tactical.get('holding_time_hours', 0) or 0)
                    if est_hours == 0:
                        self.logger.warning("Forensics: 'holding_time_hours' missing in tactical parameters. Efficiency multiplier will be 0.")
                    
                    actual_hours = hit_index * interval_hours
                    
                    result["is_filled"] = True
                    result["tp_sl_result"] = hit_result
                    
                    # v6.13 Sync: Indicators still grouped in market_forensics for filled orders
                    market_forensics["max_favorable_runup_pct"] = round((mfe / entry_price) * 100, 2) if entry_price > 0 else 0
                    market_forensics["max_adverse_drawdown_pct"] = round((mae / entry_price) * 100, 2) if entry_price > 0 else 0
                    result["trade_execution_metrics"] = {
                        "duration_candles": hit_index,
                        "actual_hours": round(actual_hours, 2),
                        "mae_stress_level_pct": mae_stress.get("mae_stress_level_pct", 0),
                        "mae_stress_tier": mae_stress.get("stress_tier", "UNKNOWN"),
                        "mfe_efficiency_pct": round(mfe_eff, 1),
                        "time_efficiency_multiplier": round(actual_hours / est_hours, 2) if est_hours > 0 else 0,
                        "highest_reached_price": max_after,
                        "lowest_reached_price": min_after,
                        "mfe_efficiency": round(mfe_eff, 1), # Notification compatibility
                        "mae_stress_level": mae_stress.get("mae_stress_level_pct", 0) # Notification compatibility
                    }
        
        return result

    def review(self, historical_strategy: Dict[str, Any], 
               actual_outcome: Dict[str, Any],
               current_observation: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Assembles a deterministic forensic audit of a trading session.

        Args:
            historical_strategy: The original session JSON.
            actual_outcome: The dictionary returned by calculate_outcome.
            current_observation: Optional current market topography for reference.

        Returns:
            A summary dictionary containing audit status and metrics.
        """
        logger.info(f"AuditAssembler: Finalizing forensic report...")
        
        hist_obs = historical_strategy.get("observation", {})
        metrics = hist_obs.get("quantitative_metrics", {})
        topography = metrics.get("volume_profile", {})
        
        has_structural_data = topography.get("poc") is not None
        final_decision = historical_strategy.get("final_decision", {})
        opinion = final_decision.get("opinion", "NEUTRAL")
        
        # v6.13 Forensic Verdict logic
        forensic_verdict = {}
        
        # 1. Justified Surrender Logic (Only for NEUTRAL)
        if opinion != "NEUTRAL":
            forensic_verdict["is_justified_surrender"] = "N/A: Only applicable when session opinion is NEUTRAL."
        else:
            # Neutral case
            forensics = actual_outcome.get("market_forensics", {})
            vol_abs = abs(forensics.get("price_move_pct", 0))
            # missed_opportunity_atr_threshold used as proxy for volatility baseline
            missed_opportunity_atr_threshold = float(self.config.audit_review['missed_opportunity_atr_threshold'])
            
            is_justified = True
            # Simple heuristic: if price move was small and no structural data, it's justified surrender.
            # (Note: In a full implementation, we'd use ATR relative distance).
            if not has_structural_data:
                is_justified = True
            elif vol_abs > 1.0: # Simplification for now: >1% move vs neutral
                 is_justified = False
            
            forensic_verdict["is_justified_surrender"] = is_justified

        # 2. Catastrophic Miss Logic (For Neutral or Unfilled)
        if actual_outcome.get("is_filled"):
            forensic_verdict["is_catastrophic_miss"] = "N/A: Trade was filled; performance is evaluated via actual execution metrics."
        else:
            forensics = actual_outcome.get("market_forensics", {})
            mfe_pct = forensics.get("max_favorable_runup_pct", 0)
            # Threshold for catastrophe (e.g. 5% or large ATR move)
            threshold = 3.0 # % threshold for catastrophic miss
            is_catastrophic = mfe_pct > threshold
            forensic_verdict["is_catastrophic_miss"] = is_catastrophic

        return {
            "forensic_verdict": forensic_verdict
        }
