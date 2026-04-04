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
        """计算限价单的风险回报比 (RR)。
        
        Args:
            entry: 入场价格。
            take_profit: 止盈价格。
            stop_loss: 止损价格。
            
        Returns:
            包含 rr_ratio, profit_distance, risk_distance 的字典。
        """
        try:
            # 基础验证：确保输入为正数
            if entry <= 0 or take_profit <= 0 or stop_loss <= 0:
                return {"error": "All price inputs must be positive numbers."}

            sl_dist = abs(entry - stop_loss)
            tp_dist = abs(take_profit - entry)
            
            # 零止损距离防御：防止除零错误
            if sl_dist < 1e-8: # 使用极小值代替 0
                return {
                    "rr_ratio": 0.0,
                    "profit_distance": round(tp_dist, 4),
                    "risk_distance": 0.0,
                    "warning": "Zero stop-loss distance detected. Logical trap."
                }
            
            rr = round(tp_dist / sl_dist, 2)
            return {
                "rr_ratio": rr,
                "profit_distance": round(tp_dist, 4),
                "risk_distance": round(sl_dist, 4)
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
        """使用 ATR (平均真实波幅) 对入场/止损/止盈距离进行标准化。
        
        将绝对价格距离转换为“波动单位”，使智能体能评估相对于市场当前粒度的风险。
        """
        try:
            if atr <= 0:
                return {"error": "ATR must be > 0 for topographical normalization."}
                
            metrics = {
                "entry_to_sl_atr": round(abs(entry - stop_loss) / atr, 3),
                "entry_to_tp_atr": round(abs(take_profit - entry) / atr, 3),
            }
            
            if current_price is not None and current_price > 0:
                # Drift: 入场位相对于市场当前价格的偏移值 (符号位逻辑对齐原有系统)
                metrics["entry_to_current_atr"] = round((entry - current_price) / atr, 3)
                
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
        """计算止损位到结构（POC/VAH/VAL）的距离，用于验证止损是否被“物理装甲”保护。
        
        正值表示止损在锚点上方，负值表示在下方。
        """
        try:
            if atr <= 0:
                return {"error": "ATR must be > 0."}
                
            def dist_to_atr(anchor: Optional[float]) -> Optional[float]:
                if anchor is None or anchor <= 0: return None
                return round((stop_loss - anchor) / atr, 3)

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
        """使用合成速度模型预测预计持仓时间。
        
        公式：Effective Speed = MAX(ATR * |Intensity|, ATR * Velocity Floor)。
        """
        try:
            if atr <= 0 or interval_minutes <= 0:
                return {"error": "ATR and interval_minutes must be > 0."}
                
            # 有效速度 = max(波动率驱动速度, 最小漂移地板)
            # 还原逻辑：移除 abs()，确保与原系统 floor 定义一致
            effective_velocity = max(atr * abs(trend_intensity), atr * min_velocity_floor)
            dist = abs(take_profit - entry)
            
            if effective_velocity < 1e-8:
                return {"error": "Zero effective velocity. Check drift configuration."}

            projected_candles = dist / effective_velocity
            # 应用持仓时间调整系数（用于抵消非线性噪音）
            projected_hours = round((projected_candles * interval_minutes * holding_time_modifier) / 60, 1)
            
            return {
                "projected_holding_candles": round(projected_candles, 2),
                "projected_holding_hours": projected_hours,
                "effective_velocity_per_candle": round(effective_velocity, 4),
                "calculation_inputs": {
                    "velocity_floor_used": min_velocity_floor,
                    "price_distance": round(dist, 4)
                }
            }
        except Exception as e:
            logger.error(f"MathTools: Time projection failure: {e}")
            return {"error": str(e)}

    @staticmethod
    def calculate_opportunity_cost(
        missed_range: float,
        atr_macro: float,
        threshold: float
    ) -> Dict[str, Any]:
        """量化“懦弱成本”(Cost of Cowardice)，即在中性决策期间错过的波动。
        """
        try:
            if atr_macro <= 0:
                return {"error": "ATR must be > 0."}
            
            rel_range = round(missed_range / atr_macro, 2)
            return {
                "missed_relative_range": rel_range,
                "is_catastrophic_miss": rel_range > threshold
            }
        except Exception as e:
            logger.error(f"MathTools: Opportunity cost failure: {e}")
            return {"error": str(e)}

    @staticmethod
    def calculate_mae_stress(
        mae_distance: float,
        max_atr_used: float,
        thresholds: Dict[str, float]
    ) -> Dict[str, Any]:
        """评估持仓期间的最大浮亏 (MAE) 相对于波动的压力水平。
        """
        try:
            if max_atr_used <= 0:
                return {"error": "max_atr_used must be > 0."}
                
            stress_level = round((mae_distance / max_atr_used) * 100, 1)
            
            tier = "LOGIC_FAILURE"
            if stress_level <= thresholds["pinpoint"]: tier = "PINPOINT"
            elif stress_level <= thresholds["standard"]: tier = "STANDARD"
            elif stress_level <= thresholds["luck"]: tier = "LUCK"
            
            return {
                "mae_stress_level_pct": stress_level,
                "stress_tier": tier
            }
        except Exception as e:
            logger.error(f"MathTools: MAE stress failure: {e}")
            return {"error": str(e)}
