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
    audit_review_thresholds: Dict[str, Any]
    audit_review_parameters: Dict[str, Any]

    @classmethod
    def from_dict(cls, cfg: Dict[str, Any]) -> "AuditReviewConfig":
        """Factory method for strategic config."""
        sampling = cfg['sampling_parameters']
        topography = cfg['topography_parameters']
        regime = cfg['regime_parameters']
        audit_thresholds = cfg['audit_review_thresholds']
        audit_params = cfg['audit_review_parameters']
        
        return cls(
            macro_interval=str(sampling['macro_context']['time_interval']),
            micro_interval=str(sampling['micro_context']['time_interval']),
            strategy_intent=str(cfg.get('strategy_intent', "")),
            regime_anchor_drift_threshold=float(regime['anchor_drift_threshold']),
            audit_review_thresholds=audit_thresholds,
            audit_review_parameters=audit_params
        )

class AuditAssembler:
    """
    The Post-Execution Audit Data Reporter (The Audit Reviewer).
    
    Now a purely deterministic component that aggregates trade execution 
    metrics and market snapshots. AI-driven audit reasoning is deferred 
    to the Batch Coaching/Evolver phase.
    """
    def __init__(self, config: AuditReviewConfig):
        """
        Initializes the Assembler with historical and tactical configurations.
        """
        self.config = config

    def calculate_outcome(self, klines: List[List[Any]], entry_price: float, 
                          strategy: Dict[str, Any], atr_macro_t0: float = 0, 
                          atr_macro_t1: float = 0, interval_hours: float = 0) -> Dict[str, Any]:
        """Analyzes klines to determine the actual market outcome vs strategist hypothesis."""
        if not klines:
            return {}
        
        # Structure: [OpenTime, Open, High, Low, Close, Volume, CloseTime, ...]
        highs = [float(k[2]) for k in klines]
        lows = [float(k[3]) for k in klines]
        closes = [float(k[4]) for k in klines]
        
        max_price = max(highs)
        min_price = min(lows)
        final_close = closes[-1]
        
        # [Architect's Fix]: Decouple Time and Space.
        # Use max(T0, T1) for MAE stress evaluation to prevent "Lagging Indicator Paradox".
        max_atr = max(atr_macro_t0, atr_macro_t1)
        
        # 1. Market Context (T0 -> T1 Full Window Reference)
        missed_range = max_price - min_price
        opp_cost = MathTools.calculate_opportunity_cost(missed_range, max_atr)
        
        market_context = {
            "highest_reached_at_t1": max_price,
            "lowest_reached_at_t1": min_price,
            "total_move_pct": round(((final_close - entry_price) / entry_price) * 100, 2),
            "missed_relative_range": opp_cost.get("missed_relative_range", 0),
            "audit_duration_candles": len(klines),
            "max_atr_used": round(max_atr, 2),
            "is_catastrophic_miss": opp_cost.get("is_catastrophic_miss", False),
            "visual_evidence": {} # To be populated by Orchestrator
        }

        # 2. Results baseline (Initialized as null for non-filled trades)
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
        opinion = (final_decision.get('opinion', '') or strategy.get('opinion', '')).upper()
        
        # Only process execution metrics for Directional orders
        if opinion in ('BULLISH', 'BEARISH'):
            limit_order = final_decision.get('tactical_parameters') or strategy.get('limit_order') or {}
            target_entry = float(limit_order.get('entry') or entry_price)
            tp = float(limit_order.get('take_profit') or 0)
            sl = float(limit_order.get('stop_loss') or 0)
            
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
                    sl_dist = abs(target_entry - sl)
                    tp_dist = abs(tp - target_entry)
                    mae = max(0, target_entry - min_after) if opinion == 'BULLISH' else max(0, max_after - target_entry)
                    mfe = max(0, max_after - target_entry) if opinion == 'BULLISH' else max(0, target_entry - min_after)
                    
                    mae_stress = MathTools.calculate_mae_stress(mae, max_atr)
                    mfe_eff = (mfe / tp_dist * 100) if tp_dist > 0 else 0
                    
                    estimated_hours = float(limit_order.get('holding_time_hours', 1.0))
                    actual_hours = hit_index * interval_hours
                    time_multiplier = round(actual_hours / estimated_hours, 2) if estimated_hours > 0 else 0
                    
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
                        "time_efficiency_multiplier": time_multiplier
                    }
                else:
                    result["tp_sl_result"] = "NEITHER" # Order never filled
                    result["trade_execution_metrics"] = {
                        "duration_candles": len(klines),
                        "actual_hours": round(len(klines) * interval_hours, 2)
                    }
        
        return result

    def review(self, historical_strategy: Dict[str, Any], 
               actual_outcome: Dict[str, Any],
               current_observation: Optional[Dict[str, Any]] = None,
               visual_context: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
        """
        Assembles a deterministic audit of a trading session.
        """
        logger.info(f"AuditAssembler: Packaging report for Evolver...")
        
        # [The Neutrality Paradox Logic]
        # Check if core topographic data was available in the historical observation
        hist_obs = historical_strategy.get("observation", {})
        metrics = hist_obs.get("quantitative_metrics", {})
        topography = metrics.get("volume_topography", {})
        
        # If POC is present, it means core structural data was available
        has_structural_data = topography.get("poc") is not None
        final_decision = historical_strategy.get("final_decision", {})
        opinion = final_decision.get("opinion", "NEUTRAL")
        
        # Determine if Neutral choice was a 'Justified Surrender'
        is_justified_surrender = True
        if opinion == "NEUTRAL" and has_structural_data:
            # If structural data exists but agent stayed Neutral, mark as unjustified
            is_justified_surrender = False
            
        review_result = {
            "evaluation_score": 0, # To be assigned by Evolver
            "audit_status": {
                "is_justified_surrender": is_justified_surrender,
                "data_availability_at_t0": "HIGH" if has_structural_data else "LOW",
                "mae_stress_tier": actual_outcome.get("trade_execution_metrics", {}).get("mae_stress_tier", "N/A"),
                "is_catastrophic_miss": actual_outcome.get("market_context", {}).get("is_catastrophic_miss", False)
            },
            "post_mortem": "Data assembled. Awaiting Evolver Meta-Audit.",
            "metrics_summary": actual_outcome.get("trade_execution_metrics", {})
        }
        
        return review_result
        
        # Inject Audit Fingerprint for Chain of Custody
        project_root = resolve_project_root()
        config_path = os.path.join(project_root, 'config', 'strategy_config.yaml')
        
        review_result["audit_metadata"] = {
            "config_hash": get_file_hash(config_path),
            "audit_timestamp": datetime.datetime.utcnow().isoformat()
        }
        
        return review_result
