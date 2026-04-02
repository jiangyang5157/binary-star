import logging
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

class MathTools:
    """
    Electronic Physicist for the Trading Triad.
    
    Provides deterministic calculations for market topography to replace 
    LLM heuristic math. All methods are static and idempotent.
    """

    @staticmethod
    def calculate_risk_reward(
        entry: float,
        take_profit: float,
        stop_loss: float
    ) -> Dict[str, Any]:
        """
        Calculates the Risk-Reward (RR) ratio for a limit order.
        
        Logic: 
        - Profit Potential = |TP - Entry|
        - Risk Capital = |Entry - SL|
        - RR Ratio = Profit / Risk
        
        The Break-even point is implicitly defined where Profit = Risk (RR=1.0).
        A ratio > 2.0 is generally considered 'High Conviction' in trending markets.
        """
        try:
            sl_dist = abs(entry - stop_loss)
            tp_dist = abs(take_profit - entry)
            
            rr = round(tp_dist / sl_dist, 2) if sl_dist > 0 else 0
            return {
                "rr_ratio": rr,
                "profit_distance": round(tp_dist, 2),
                "risk_distance": round(sl_dist, 2)
            }
        except Exception as e:
            logger.error(f"MathTools: RR calculation failed: {e}")
            return {"error": str(e)}

    @staticmethod
    def calculate_atr_metrics(
        entry: float,
        stop_loss: float,
        take_profit: float,
        atr: float,
        current_price: Optional[float] = None
    ) -> Dict[str, Any]:
        """
        Standardizes entry/exit distances using ATR (Average True Range).
        
        Philosophy:
        ATR represents the 'Market Noise' or 'Granularity'. By normalizing distances 
        against ATR, we convert absolute price points into 'volatility units', 
        allowing the agent to assess if a stop is placed within the noise floor 
        or behind structural support/resistance.
        """
        try:
            if atr <= 0:
                return {"error": "ATR must be greater than zero."}
                
            metrics = {
                "entry_to_sl_atr": round(abs(entry - stop_loss) / atr, 2),
                "entry_to_tp_atr": round(abs(take_profit - entry) / atr, 2),
            }
            
            if current_price is not None:
                metrics["entry_to_current_atr"] = round((entry - current_price) / atr, 2)
                
            return metrics
        except Exception as e:
            logger.error(f"MathTools: ATR metrics failed: {e}")
            return {"error": str(e)}

    @staticmethod
    def calculate_structural_proximity(
        stop_loss: float,
        atr: float,
        poc: Optional[float] = None,
        vah: Optional[float] = None,
        val: Optional[float] = None
    ) -> Dict[str, Any]:
        """
        Calculates the distance from the Stop Loss to key structural levels (POC, VAH, VAL) in ATR units.
        Used by the Critic to verify if the SL is placed behind physical 'armor'.
        """
        try:
            if atr <= 0:
                return {"error": "ATR must be greater than zero."}
                
            def dist_to_atr(anchor):
                if anchor is None: return None
                # (SL - Anchor) / ATR. 
                # Positive means SL is above anchor, Negative means SL is below.
                return round((stop_loss - anchor) / atr, 2)

            return {
                "sl_to_poc_atr": dist_to_atr(poc),
                "sl_to_vah_atr": dist_to_atr(vah),
                "sl_to_val_atr": dist_to_atr(val)
            }
        except Exception as e:
            logger.error(f"MathTools: Structural proximity failed: {e}")
            return {"error": str(e)}

    @staticmethod
    def project_holding_time(
        entry: float,
        take_profit: float,
        atr: float,
        trend_intensity: float,
        interval_minutes: int,
        min_velocity_floor: float
    ) -> Dict[str, Any]:
        """
        Predicts the time required to reach the Take Profit target using Volatility Dynamics.
        
        Algorithm (Synthetic Velocity Model):
        -------------------------------------
        1. Base Engine Power = ATR (Market granularity/speed).
        2. Efficiency Factor = |Trend_Intensity| (Directional momentum alignment).
        3. Raw Velocity = ATR * Efficiency.
        
        The result is a 'Volatility-Adjusted Velocity'. High ATR + High Intensity 
        projects rapid target hits; Low ATR or ranging markets project slow crawls.
        
        Safety Logic (The Floor):
        -------------------------
        min_velocity_floor: Prevents division by zero in zero-momentum regimes.
        Implies a minimum baseline 'drift' per candle (in ATR units), assumed 
        to exist due to stochastic market noise even when trend intensity is zero.
        This value is injected by the Strategist based on strategy specific tolerance.
        """
        try:
            if atr <= 0:
                return {"error": "ATR must be greater than zero."}
                
            # effective_velocity = max(ATR * |intensity|, safety_floor)
            effective_velocity = max(atr * abs(trend_intensity), atr * min_velocity_floor)
            dist = abs(take_profit - entry)
            
            # Prevent zero velocity if floor is somehow 0
            if effective_velocity <= 0:
                return {"error": "Effective velocity is zero. Check trend_intensity or velocity_floor."}

            projected_candles = dist / effective_velocity
            projected_hours = round((projected_candles * interval_minutes) / 60, 1)
            
            return {
                "projected_holding_candles": round(projected_candles, 1),
                "projected_holding_hours": projected_hours,
                "effective_velocity_per_candle": round(effective_velocity, 2),
                "model_parameters": {
                    "velocity_floor": min_velocity_floor,
                    "target_distance": round(dist, 2)
                }
            }
        except Exception as e:
            logger.error(f"MathTools: Holding time projection failed: {e}")
            return {"error": str(e)}
