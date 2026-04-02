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
        atr_macro_t0: float = 0, 
        atr_macro_t1: float = 0, 
        interval_hours: float = 0
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
        
        max_price = max(highs)
        min_price = min(lows)
        final_close = closes[-1]
        
        # v6.0 Optimization: Use max ATR between T0 and T1 as the physical normalization baseline
        max_atr = max(atr_macro_t0, atr_macro_t1)
        
        # 1. Market Context / Forensic Opportunity Cost
        missed_range = max_price - min_price
        opportunity_cost_analysis = MathTools.calculate_opportunity_cost(missed_range, max_atr)
        
        market_context = {
            "highest_reached_at_t1": max_price,
            "lowest_reached_at_t1": min_price,
            "total_move_pct": round(((final_close - entry_price) / entry_price) * 100, 2),
            "missed_relative_range": opportunity_cost_analysis.get("missed_relative_range", 0),
            "audit_duration_candles": len(klines),
            "max_atr_used": round(max_atr, 2),
            "is_catastrophic_miss": opportunity_cost_analysis.get("is_catastrophic_miss", False)
        }

        # 2. Result Payload
        result = {
            "tp_sl_result": "NEITHER",
            "is_filled": False,
            "entry_price_requested": entry_price,
            "highest_reached_price": None,
            "lowest_reached_price": None,
            "exit_price_at_t1": final_close,
            "market_context": market_context,
            "trade_execution_metrics": {}
        }
        
        final_decision = strategy.get('final_decision', {})
        decision_opinion = (final_decision.get('opinion', '') or strategy.get('opinion', '')).upper()
        
        if decision_opinion in ('BULLISH', 'BEARISH'):
            tactical = final_decision.get('tactical_parameters') or strategy.get('limit_order') or {}
            target_entry = float(tactical.get('entry', entry_price) or entry_price)
            tp = float(tactical.get('take_profit', 0) or 0)
            sl = float(tactical.get('stop_loss', 0) or 0)
            
            if tp > 0 and sl > 0:
                entry_hit = False
                hit_result = "NEITHER"
                hit_index = len(klines)
                max_after, min_after = -float('inf'), float('inf')
                
                for i, k in enumerate(klines):
                    high, low = float(k[2]), float(k[3])
                    if not entry_hit:
                        if (decision_opinion == 'BULLISH' and low <= target_entry) or \
                           (decision_opinion == 'BEARISH' and high >= target_entry):
                            entry_hit = True
                            max_after, min_after = high, low
                    
                    if entry_hit:
                        max_after, min_after = max(max_after, high), min(min_after, low)
                        if hit_result == "NEITHER":
                            if decision_opinion == 'BULLISH':
                                if low <= sl: hit_result = "SL_HIT"; hit_index = i + 1
                                elif high >= tp: hit_result = "TP_HIT"; hit_index = i + 1
                            else: # BEARISH
                                if high >= sl: hit_result = "SL_HIT"; hit_index = i + 1
                                elif low <= tp: hit_result = "TP_HIT"; hit_index = i + 1
                
                if entry_hit:
                    tp_dist = abs(tp - target_entry)
                    mae = max(0, target_entry - min_after) if decision_opinion == 'BULLISH' else max(0, max_after - target_entry)
                    mfe = max(0, max_after - target_entry) if decision_opinion == 'BULLISH' else max(0, target_entry - min_after)
                    
                    mae_stress = MathTools.calculate_mae_stress(mae, max_atr)
                    mfe_eff = (mfe / tp_dist * 100) if tp_dist > 0 else 0
                    
                    est_hours = float(tactical.get('holding_time_hours', 1.0) or 1.0)
                    actual_hours = hit_index * interval_hours
                    time_mult = round(actual_hours / est_hours, 2) if est_hours > 0 else 0
                    
                    result["is_filled"] = True
                    result["tp_sl_result"] = hit_result
                    result["highest_reached_price"] = max_after
                    result["lowest_reached_price"] = min_after
                    result["trade_execution_metrics"] = {
                        "duration_candles": hit_index,
                        "actual_hours": round(actual_hours, 2),
                        "mae_stress_level_pct": mae_stress.get("mae_stress_level_pct", 0),
                        "mae_stress_tier": mae_stress.get("stress_tier", "UNKNOWN"),
                        "mfe_efficiency_pct": round(mfe_eff, 1),
                        "time_efficiency_multiplier": time_mult
                    }
                else:
                    result["tp_sl_result"] = "NEITHER"
                    result["trade_execution_metrics"] = {
                        "duration_candles": len(klines),
                        "actual_hours": round(len(klines) * interval_hours, 2)
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
        
        # v6.0 Forensic Logic: Neutrality is only a 'Justified Surrender' if 
        # the market didn't move past the Opportunity Cost limit defined in config.
        market_context = actual_outcome.get("market_context", {})
        missed_range = market_context.get("missed_relative_range", 0)
        opportunity_cost_forensic_threshold = float(self.config.audit_review.get('score_opportunity_cost_limit', 1.5))
        is_justified_surrender = True
        
        if opinion == "NEUTRAL":
            if missed_range > opportunity_cost_forensic_threshold:
                # Opportunity Loss: Market moved significantly despite structural data availability
                is_justified_surrender = False
            elif not has_structural_data:
                # Always justified if we lacked physical maps
                is_justified_surrender = True

        return {
            "evaluation_score": 0, # Placeholder for Evolver
            "audit_status": {
                "is_justified_surrender": is_justified_surrender,
                "data_availability_at_t0": "HIGH" if has_structural_data else "LOW",
                "mae_stress_tier": actual_outcome.get("trade_execution_metrics", {}).get("mae_stress_tier", "N/A"),
                "is_catastrophic_miss": market_context.get("is_catastrophic_miss", False)
            },
            "post_mortem": "Forensic data assembled.",
            "metrics_summary": actual_outcome.get("trade_execution_metrics", {})
        }
