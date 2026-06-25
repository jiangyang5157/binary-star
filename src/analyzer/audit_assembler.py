from dataclasses import dataclass
from typing import Dict, Any, List, Optional
from src.infrastructure.exchange.models import KlineData
from src.utils.math_utils import MathTools

from src.utils.logger_utils import setup_logger
logger = setup_logger(__name__)

@dataclass(frozen=True)
class AuditReviewConfig:
    """Dataclass for type-safe Audit Review configuration."""
    macro_interval: str
    micro_interval: str
    strategy_intent: str
    catastrophic_miss_atr_threshold: float
    unfilled_proximity_atr_limit: float
    missed_opportunity_atr_threshold: float
    mae_threshold_pinpoint: float
    mae_threshold_standard: float
    mae_threshold_luck: float
    base_slippage_bps: float
    max_slippage_bps: float

    @classmethod
    def from_dict(cls, cfg: Dict[str, Any]) -> "AuditReviewConfig":
        """Factory method for strategic config."""
        sampling = cfg['analysis_window']
        audit_node = cfg['audit_review']
        
        return cls(
            macro_interval=str(sampling['macro_context']['time_interval']),
            micro_interval=str(sampling['micro_context']['time_interval']),
            strategy_intent=str(cfg.get('strategy_intent', "")),
            catastrophic_miss_atr_threshold=float(audit_node['catastrophic_miss_atr_threshold']),
            unfilled_proximity_atr_limit=float(audit_node['unfilled_proximity_atr_limit']),
            missed_opportunity_atr_threshold=float(audit_node['missed_opportunity_atr_threshold']),
            mae_threshold_pinpoint=float(audit_node['mae']['mae_threshold_pinpoint']),
            mae_threshold_standard=float(audit_node['mae']['mae_threshold_standard']),
            mae_threshold_luck=float(audit_node['mae']['mae_threshold_luck']),
            base_slippage_bps=float(audit_node['slippage']['base_slippage_bps']),
            max_slippage_bps=float(audit_node['slippage']['max_slippage_bps'])
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
        klines: List[KlineData], 
        entry_price: float, 
        strategy: Dict[str, Any],
        atr_macro_t0: float, 
        atr_macro_t1: float, 
        long_short_ratio_macro_t0: float,
        long_short_ratio_macro_t1: float,
        interval_hours: float,
        volume_profile: Optional[List[Dict[str, Any]]] = None
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
        
        highs = [k.high for k in klines]
        lows = [k.low for k in klines]
        closes = [k.close for k in klines]
        
        # Optimization: Core Physical Snapshots
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

        # Regime Drift Analysis
        regime_forensics = {
            "volatility_drift_pct": round(((atr_macro_t1 - atr_macro_t0) / atr_macro_t0 * 100), 2) if atr_macro_t0 > 0 else 0,
            "sentiment_drift": round(long_short_ratio_macro_t1 - long_short_ratio_macro_t0, 4)
        }

        # Decision context extraction
        final_decision = strategy.get('final_decision', {})
        opinion = final_decision.get('opinion', 'NEUTRAL').upper()
        # Default to NEITHER — actual result computed downstream
        default_result = "NEITHER"

        # 2. Result Payload Base
        result = {
            "tp_sl_result": default_result,
            "is_filled": False,
            "market_forensics": market_forensics,
            "regime_forensics": regime_forensics,
            "execution_forensics": {},
            "trade_execution_metrics": None # No entry, no execution.
        }
        
        if opinion in ('BULLISH', 'BEARISH'):
            tactical = final_decision.get('tactical_parameters', {})
            planned_entry = float(tactical.get('entry', entry_price))
            
            # --- Forensic Hardening: Apply Liquidity-Aware Slippage ---
            slippage_metrics = MathTools.calculate_liquidity_slippage(
                price=planned_entry,
                volume_profile=volume_profile or [],
                atr=max_atr,
                base_slippage_bps=self.config.base_slippage_bps,
                max_slippage_bps=self.config.max_slippage_bps,
                opinion=opinion
            )
            target_entry = slippage_metrics["price_adjusted"]
            
            tp = float(tactical.get('take_profit', 0))
            sl = float(tactical.get('stop_loss', 0))
            
            # Theoretical Drift Calculation (Physics vs Intent)
            entry_drift = (min_price - target_entry) if opinion == 'BULLISH' else (target_entry - max_price)
            entry_drift_atr = round(entry_drift / max_atr, 4) if max_atr > 0 else 0
            
            theoretical_mae = max(0, target_entry - min_price) if opinion == 'BULLISH' else max(0, max_price - target_entry)
            theoretical_mfe = max(0, max_price - target_entry) if opinion == 'BULLISH' else max(0, target_entry - min_price)
 
            unfilled_proximity_atr_limit = self.config.unfilled_proximity_atr_limit
            result["execution_forensics"] = {
                "planned_entry": planned_entry,
                "adjusted_entry": target_entry,
                "slippage_bps": slippage_metrics.get("slippage_bps", 0),
                "liquidity_quality": slippage_metrics.get("liquidity_quality", 0),
                "entry_drift_atr": entry_drift_atr,
                "theoretical_mae_atr": round(theoretical_mae / max_atr, 4) if max_atr > 0 else 0,
                "theoretical_mfe_atr": round(theoretical_mfe / max_atr, 4) if max_atr > 0 else 0,
                "is_near_miss": 0 < entry_drift_atr < unfilled_proximity_atr_limit
            }
 
            # Schema Relocation (Indicators now grouped in market_forensics)
            market_forensics["planned_entry_price"] = target_entry
            market_forensics["total_price_change_pct"] = market_forensics["price_move_pct"]
            market_forensics["max_favorable_runup_pct"] = round((theoretical_mfe / target_entry) * 100, 2) if target_entry > 0 else 0
            market_forensics["max_favorable_runup_atr"] = round(theoretical_mfe / max_atr, 4) if max_atr > 0 else 0
            market_forensics["max_adverse_drawdown_pct"] = round((theoretical_mae / target_entry) * 100, 2) if target_entry > 0 else 0
 
            if tp > 0 and sl > 0:
                entry_hit = False
                entry_index = None
                hit_result = "NEITHER"
                hit_index = len(klines)
                hit_time = None
                max_after, min_after = -float('inf'), float('inf')
                
                for i, k in enumerate(klines):
                    high = float(k.high)
                    low = float(k.low)
                    if not entry_hit:
                        if (opinion == 'BULLISH' and low <= target_entry) or \
                           (opinion == 'BEARISH' and high >= target_entry):
                            entry_hit = True
                            entry_index = i + 1
                            max_after, min_after = high, low
                    
                    if entry_hit:
                        max_after, min_after = max(max_after, high), min(min_after, low)
                        if hit_result == "NEITHER":
                            if opinion == 'BULLISH':
                                if low <= sl: 
                                    hit_result = "SL_HIT"
                                    hit_index = i + 1
                                    hit_time = k.open_time
                                elif high >= tp: 
                                    hit_result = "TP_HIT"
                                    hit_index = i + 1
                                    hit_time = k.open_time
                            else: # BEARISH
                                if high >= sl: 
                                    hit_result = "SL_HIT"
                                    hit_index = i + 1
                                    hit_time = k.open_time
                                elif low <= tp: 
                                    hit_result = "TP_HIT"
                                    hit_index = i + 1
                                    hit_time = k.open_time
                
                if entry_hit:
                    tp_dist = abs(tp - target_entry)
                    mae = max(0, target_entry - min_after) if opinion == 'BULLISH' else max(0, max_after - target_entry)
                    mfe = max(0, max_after - target_entry) if opinion == 'BULLISH' else max(0, target_entry - min_after)
                    
                    # --- Dynamic Temporal Forensic Logic ---
                    # 1. Access Math Fact Check for dilation ground-truth
                    last_round = strategy.get('debate_history', [{}])[-1]
                    math_check = last_round.get('math_fact_check', {}).get('holding_time_verification', {})
                    
                    # 2. Extract Dilation Parameters
                    dilation_factor = float(math_check.get('temporal_dilation_factor') or 1.0)
                    dilation_regime = math_check.get('temporal_dilation_regime', 'temporal_dilation_standard')
                    
                    # 3. Calculate Actual ISOLATED Holding Duration (Holding = Exit - Entry)
                    actual_holding_hours = round((hit_index - entry_index) * interval_hours, 2)
                    proj_holding_hours = float(tactical.get('projected_holding_hours', 0) or 0)
                    
                    # 4. Stress and Efficiency Analytics (Physics of Execution Quality)
                    mae_stress = MathTools.calculate_mae_stress(
                        mae_distance=mae, 
                        max_atr_used=max_atr,
                        pinpoint=self.config.mae_threshold_pinpoint,
                        standard=self.config.mae_threshold_standard,
                        luck=self.config.mae_threshold_luck
                    )
                    
                    result["is_filled"] = True
                    result["tp_sl_result"] = hit_result
                    
                    # 5. Final Meta-Metric Assembly (The "Evolver-Facing" Segment + Forensic Ground-Truth)
                    result["trade_execution_metrics"] = {
                        "actual_holding_hours": actual_holding_hours,
                        "projected_holding_hours": proj_holding_hours,
                        "temporal_dilation_factor": dilation_factor,
                        "temporal_dilation_regime": dilation_regime,
                        "mae_stress_level_pct": mae_stress.get("mae_stress_level_pct", 0),
                        "mae_stress_tier": mae_stress.get("stress_tier", "UNKNOWN"),
                        "mfe_efficiency_pct": round((mfe / tp_dist * 100) if tp_dist > 0 else 0, 1),
                        "highest_reached_price": max_after,
                        "lowest_reached_price": min_after,
                        "actual_hit_timestamp": hit_time
                    }
                    
                    # 6. Holistic Diagnostics (Moving drift data to forensics)
                    result["execution_forensics"]["actual_waiting_hours"] = round(entry_index * interval_hours, 2)
                    result["execution_forensics"]["actual_total_duration"] = round(hit_index * interval_hours, 2)
                    result["execution_forensics"]["mfe_efficiency_pct"] = round((mfe / tp_dist * 100) if tp_dist > 0 else 0, 1)
                    # result["execution_forensics"]["time_efficiency_multiplier"] = round(actual_holding_hours / proj_holding_hours, 2) if proj_holding_hours > 0 else 0
                    
                    # Sync: TP/SL Outcomes
                    market_forensics["max_favorable_runup_pct"] = round((mfe / target_entry) * 100, 2) if target_entry > 0 else 0
                    market_forensics["max_favorable_runup_atr"] = round(mfe / max_atr, 4) if max_atr > 0 else 0
                    market_forensics["max_adverse_drawdown_pct"] = round((mae / target_entry) * 100, 2) if target_entry > 0 else 0
        
        return result

    def review(self, historical_strategy: Dict[str, Any], actual_outcome: Dict[str, Any]) -> Dict[str, Any]:
        """Assembles a deterministic forensic audit of a trading session.

        Args:
            historical_strategy: The original session JSON.
            actual_outcome: The dictionary returned by calculate_outcome.

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
        
        # Forensic Verdict logic
        forensic_verdict = {}
        
        # 1. Justified Surrender Logic (Only for NEUTRAL)
        if opinion != "NEUTRAL":
            forensic_verdict["is_justified_surrender"] = "N/A: Only applicable when session opinion is NEUTRAL."
        else:
            # Neutral case
            forensics = actual_outcome.get("market_forensics", {})
            # Logic: If price move intensity (ATR) exceeds the threshold, the surrender was NOT justified
            move_intensity = forensics.get("window_volatility_intensity_atr", 0)
            missed_opportunity_atr_threshold = self.config.missed_opportunity_atr_threshold
            
            is_justified = True
            if not has_structural_data:
                is_justified = True
            elif move_intensity > missed_opportunity_atr_threshold:
                 is_justified = False
            
            forensic_verdict["is_justified_surrender"] = is_justified

        # 2. Catastrophic Miss Logic (For Neutral or Unfilled)
        if actual_outcome.get("is_filled"):
            forensic_verdict["is_catastrophic_miss"] = "N/A: Trade was filled; performance is evaluated via actual execution metrics."
        else:
            forensics = actual_outcome.get("market_forensics", {})
            mfe_atr = forensics.get("max_favorable_runup_atr", 0)
            # Threshold for catastrophe (ATR move instead of fixed %)
            threshold = self.config.catastrophic_miss_atr_threshold
            is_catastrophic = mfe_atr > threshold
            forensic_verdict["is_catastrophic_miss"] = is_catastrophic

        return {
            "forensic_verdict": forensic_verdict
        }
