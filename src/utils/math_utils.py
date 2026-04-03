import logging
from typing import Dict, Any, Optional, Union

# Initialize standard hardened logger for math telemetry
logger = logging.getLogger(__name__)

class MathTools:
    """The Electronic Physicist for the Singularity Reasoning Triad.
    
    Provides deterministic calculations for market topography and trade geometry
    to replace LLM heuristic math. All methods are static and idempotent.
    
    Key Responsibilities:
    1. Geometric Validation (RR, ATR Buffers, Structural Armor).
    2. Velocity Projection (Predicted holding times).
    3. Forensic Benchmarking (MAE Stress, Opportunity Cost).
    """

    @staticmethod
    def calculate_risk_reward(
        entry: float,
        take_profit: float,
        stop_loss: float
    ) -> Dict[str, Any]:
        """Calculates the Risk-Reward (RR) ratio for a limit order.
        
        Args:
            entry: Entry price of the trade.
            take_profit: Target exit price for profit.
            stop_loss: Exit price for risk management.
            
        Returns:
            A dictionary containing:
                rr_ratio: The calculated reward vs risk.
                profit_distance: Absolute difference between entry and TP.
                risk_distance: Absolute difference between entry and SL.
                error: (Optional) Error string if calculation fails.
        """
        try:
            sl_dist = abs(entry - stop_loss)
            tp_dist = abs(take_profit - entry)
            
            # Defense: Zero-division safety for logic gaps
            if sl_dist <= 0:
                return {
                    "rr_ratio": 0.0,
                    "profit_distance": round(tp_dist, 2),
                    "risk_distance": 0.0,
                    "warning": "Zero stop-loss distance detected."
                }
            
            rr = round(tp_dist / sl_dist, 2)
            return {
                "rr_ratio": rr,
                "profit_distance": round(tp_dist, 2),
                "risk_distance": round(sl_dist, 2)
            }
        except Exception as e:
            logger.error(f"MathTools: RR calculation failure: {e}")
            return {"error": str(e)}

    @staticmethod
    def calculate_atr_metrics(
        entry: float,
        stop_loss: float,
        take_profit: float,
        atr: float,
        current_price: Optional[float] = None
    ) -> Dict[str, Any]:
        """Standardizes entry/exit distances using ATR (Average True Range).
        
        Normalizing distances against ATR converts absolute price points into 
        'volatility units', enabling the agent to assess risk relative to 
        real-time market granularity.
        
        Args:
            entry: Entry price.
            stop_loss: Stop-loss price.
            take_profit: Take-profit price.
            atr: Current ATR value.
            current_price: Optional market price for real-time drift assessment.
            
        Returns:
            A dictionary of normalized ATR distances (e.g., SL is 1.5 ATR away).
        """
        try:
            if atr <= 0:
                return {"error": "ATR must be > 0 for topographical normalization."}
                
            metrics = {
                "entry_to_sl_atr": round(abs(entry - stop_loss) / atr, 2),
                "entry_to_tp_atr": round(abs(take_profit - entry) / atr, 2),
            }
            
            if current_price is not None:
                # Drift is signed: positive means market is above the entry.
                metrics["entry_to_current_atr"] = round((entry - current_price) / atr, 2)
                
            return metrics
        except Exception as e:
            logger.error(f"MathTools: ATR metrics failure: {e}")
            return {"error": str(e)}

    @staticmethod
    def calculate_structural_proximity(
        stop_loss: float,
        atr: float,
        poc: Optional[float] = None,
        vah: Optional[float] = None,
        val: Optional[float] = None
    ) -> Dict[str, Any]:
        """Calculates the distance from SL to structural 'armor' (POC/VAH/VAL).
        
        This metric is utilized by the Critic Agent to verify if the Stop Loss 
        is placed behind physical volume anchors.
        
        Args:
            stop_loss: Target SL price.
            atr: Market granularity unit.
            poc: Point of Control (Volume Anchor).
            vah: Value Area High.
            val: Value Area Low.
            
        Returns:
            A dictionary of relative distances in ATR units. 
            Positive = SL is ABOVE anchor; Negative = SL is BELOW anchor.
        """
        try:
            if atr <= 0:
                return {"error": "ATR must be > 0."}
                
            def dist_to_atr(anchor: Optional[float]) -> Optional[float]:
                if anchor is None: return None
                return round((stop_loss - anchor) / atr, 2)

            return {
                "sl_to_poc_atr": dist_to_atr(poc),
                "sl_to_vah_atr": dist_to_atr(vah),
                "sl_to_val_atr": dist_to_atr(val)
            }
        except Exception as e:
            logger.error(f"MathTools: Structural proximity failure: {e}")
            return {"error": str(e)}

    @staticmethod
    def project_holding_time(
        entry: float,
        take_profit: float,
        atr: float,
        trend_intensity: float,
        interval_minutes: int,
        min_velocity_floor: float,
        holding_time_modifier: float
    ) -> Dict[str, Any]:
        """Predicts the estimated holding time using a Synthetic Velocity Model.
        
        Logic:
        1. Base Engine = ATR (Natural market speed).
        2. Alignment = |Trend Intensity| (Momentum factor).
        3. Effective Speed = MAX(ATR * Intensity, ATR * Velocity Floor).
        4. Buffer = Apply holding_time_modifier to account for non-linear noise.
        
        The result converts price distance into time buckets (candles/hours).
        
        Args:
            entry: Proposed entry.
            take_profit: Proposed target.
            atr: Market ATR.
            trend_intensity: 0.0 to 1.0 (Regime momentum).
            interval_minutes: Chart time interval in minutes.
            min_velocity_floor: Safety floor (drift) when momentum is zero.
            holding_time_modifier: Multiplier for zig-zag noise (e.g., 1.5).
            
        Returns:
            A dictionary containing projected hours and candle counts.
        """
        try:
            if atr <= 0:
                return {"error": "ATR must be > 0."}
                
            # effective_velocity = max(ATR * |intensity|, safety_floor)
            effective_velocity = max(atr * abs(trend_intensity), atr * min_velocity_floor)
            dist = abs(take_profit - entry)
            
            if effective_velocity <= 0:
                return {"error": "Zero velocity detected. Check floor config."}

            projected_candles = dist / effective_velocity
            projected_hours = round((projected_candles * interval_minutes * holding_time_modifier) / 60, 1)
            
            return {
                "projected_holding_candles": round(projected_candles, 1),
                "projected_holding_hours": projected_hours,
                "effective_velocity_per_candle": round(effective_velocity, 2),
                "calculation_inputs": {
                    "velocity_floor": min_velocity_floor,
                    "target_dist": round(dist, 2)
                }
            }
        except Exception as e:
            logger.error(f"MathTools: Time projection failure: {e}")
            return {"error": str(e)}

    @staticmethod
    def calculate_opportunity_cost(
        missed_range: float,
        atr_macro: float
    ) -> Dict[str, Any]:
        """Quantifies the 'Cost of Cowardice' for Neutral decisions.
        
        Used by the Evolver to penalize indecision during major structural moves.
        
        Args:
            missed_range: Absolute price movement during the tracking window.
            atr_macro: Market volatility unit.
            
        Returns:
            A dictionary containing missed_relative_range (in ATRs).
        """
        try:
            if atr_macro <= 0:
                return {"error": "ATR must be > 0."}
            
            rel_range = round(missed_range / atr_macro, 2)
            return {
                "missed_relative_range": rel_range,
                "is_catastrophic_miss": rel_range > 2.0
            }
        except Exception as e:
            logger.error(f"MathTools: Opportunity cost failure: {e}")
            return {"error": str(e)}

    @staticmethod
    def calculate_mae_stress(
        mae_distance: float,
        max_atr_used: float
    ) -> Dict[str, Any]:
        """Evaluates the physical stress of a holding period relative to volatility.
        
        Args:
            mae_distance: Maximum adverse price distance recorded.
            max_atr_used: The peak ATR during the session (prevents lag).
            
        Returns:
            A dictionary containing mae_stress_level_pct and tier classification.
        """
        try:
            if max_atr_used <= 0:
                return {"error": "max_atr_used must be > 0."}
                
            stress_level = round((mae_distance / max_atr_used) * 100, 1)
            
            # Classification Tiers
            tier = "LOGIC_FAILURE"
            if stress_level <= 15: tier = "PINPOINT"
            elif stress_level <= 50: tier = "STANDARD"
            elif stress_level <= 80: tier = "LUCK"
            
            return {
                "mae_stress_level_pct": stress_level,
                "stress_tier": tier
            }
        except Exception as e:
            logger.error(f"MathTools: MAE stress failure: {e}")
            return {"error": str(e)}
