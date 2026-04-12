import logging
import numpy as np
from typing import Dict, Any, Optional, Union, List

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
    def get_regime_scalars(
        trend_intensity: float,
        volatility_intensity_index: float,
        normalized_velocity: float,
        ti_thresh: float,
        ti_strong: float,
        vr_base: float,
        vr_extreme: float,
        dilation_dead_water: float,
        dilation_highway: float,
        dilation_climax: float,
        dilation_standard: float,
        min_velocity_floor: float
    ) -> Dict[str, Any]:
        """Calculates primary physics scalars for a given market regime.
        
        Args:
            trend_intensity: Efficiency Ratio [-1, 1] for regime triggers.
            volatility_intensity_index: Current vs mean ATR ratio.
            normalized_velocity: Physical ATR/Bar speed for time projection.
        """
        ti_abs = abs(trend_intensity)
        
        # Final Velocity is the higher of observed speed or the protocol floor.
        # Added 1e-9 epsilon to prevent DivisionByZero in catastrophic config failure scenarios.
        effective_velocity_per_atr = max(normalized_velocity, min_velocity_floor, 1e-9)
        
        # Regime Detection (Logic gates remain on trend_intensity)
        if volatility_intensity_index >= vr_extreme:
            factor = dilation_climax
            regime = "temporal_dilation_climax"
        elif volatility_intensity_index < vr_base and ti_abs < ti_strong:
            factor = dilation_dead_water
            regime = "temporal_dilation_dead_water"
        elif ti_abs >= ti_thresh and vr_base <= volatility_intensity_index < vr_extreme:
            factor = dilation_highway
            regime = "temporal_dilation_highway"
        else:
            factor = dilation_standard
            regime = "temporal_dilation_standard"
            
        return {
            "effective_velocity_per_atr": effective_velocity_per_atr,
            "temporal_dilation_factor": factor,
            "temporal_dilation_regime": regime
        }

    @staticmethod
    def project_holding_time(
        current_price: float,
        entry: float,
        take_profit: float,
        atr: float,
        trend_intensity: float,
        volatility_intensity_index: float,
        normalized_velocity: float,
        interval_minutes: int,
        min_velocity_floor: float,
        # Thresholds
        vr_base: float,
        vr_extreme: float,
        ti_strong: float,
        ti_thresh: float,
        # Dilation Modifiers (Loaded from YAML temporal_dilation_*)
        dilation_dead_water: float,
        dilation_highway: float,
        dilation_climax: float,
        dilation_standard: float
    ) -> Dict[str, Any]:
        """使用静态标量引擎计算精确持仓与等待时间。"""
        try:
            if atr <= 0 or interval_minutes <= 0:
                return {"error": "ATR and interval_minutes must be > 0."}
            
            scalars = MathTools.get_regime_scalars(
                trend_intensity=trend_intensity,
                volatility_intensity_index=volatility_intensity_index,
                normalized_velocity=normalized_velocity,
                ti_thresh=ti_thresh, ti_strong=ti_strong,
                vr_base=vr_base, vr_extreme=vr_extreme,
                dilation_dead_water=dilation_dead_water,
                dilation_highway=dilation_highway,
                dilation_climax=dilation_climax,
                dilation_standard=dilation_standard,
                min_velocity_floor=min_velocity_floor
            )
            
            # 使用还原后的物理速度 (有效标量 * ATR)
            effective_velocity = scalars["effective_velocity_per_atr"] * atr
            
            # 1. 持仓时间 (受膨胀影响)
            dist = abs(take_profit - entry)
            projected_holding_hours = round((dist / effective_velocity * interval_minutes * scalars["temporal_dilation_factor"]) / 60, 1)

            
            # 2. 等待时间 (不受膨胀影响)
            projected_waiting_hours = 0.0
            if current_price is not None and current_price > 0:
                wait_dist = abs(entry - current_price)
                projected_waiting_hours = round((wait_dist / effective_velocity * interval_minutes) / 60, 1)

            return {
                "projected_holding_hours": projected_holding_hours,
                "projected_waiting_hours": projected_waiting_hours,
                "temporal_dilation_factor": scalars["temporal_dilation_factor"],
                "temporal_dilation_regime": scalars["temporal_dilation_regime"]
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
        pinpoint: float,
        standard: float,
        luck: float
    ) -> Dict[str, Any]:
        """评估持仓期间的最大浮亏 (MAE) 相对于波动的压力水平。
        """
        try:
            if max_atr_used <= 0:
                return {"error": "max_atr_used must be > 0."}
                
            stress_level = round((mae_distance / max_atr_used) * 100, 1)
            
            tier = "LOGIC_FAILURE"
            if stress_level <= pinpoint: tier = "PINPOINT"
            elif stress_level <= standard: tier = "STANDARD"
            elif stress_level <= luck: tier = "LUCK"
            
            return {
                "mae_stress_level_pct": stress_level,
                "stress_tier": tier
            }
        except Exception as e:
            logger.error(f"MathTools: MAE stress failure: {e}")
            return {"error": str(e)}
    @staticmethod
    def calculate_liquidity_slippage(
        price: float,
        volume_profile: List[Dict[str, Any]],
        atr: float,
        base_slippage_bps: float,
        max_slippage_bps: float
    ) -> Dict[str, Any]:
        """根据成交量分布（Volume Profile）计算流动性敏感型滑点。
        
        逻辑：
        - 寻找离价格最近的成交量桶（Bin）。
        - 归一化成交量：当前桶容量 / 最大桶容量。
        - 滑点惩罚：在基础滑点之上，根据成交量真空度增加惩罚项。
        """
        try:
            if not volume_profile or atr <= 0:
                return {"price_adjusted": price, "slippage_bps": base_slippage_bps, "warning": "Insufficient profile data."}

            # 1. 寻找最近的 Price Bin
            prices = np.array([float(d['price']) for d in volume_profile])
            vols = np.array([float(d['volume']) for d in volume_profile])
            
            idx = (np.abs(prices - price)).argmin()
            local_vol = vols[idx]
            max_vol = vols.max() if vols.size > 0 else 1.0
            
            # 2. 计算流动性质量 (0.0 to 1.0)
            liquidity_quality = local_vol / max_vol if max_vol > 0 else 0.0
            
            # 3. 动态滑点计算 (线性模型补偿真空区)
            # 基础滑点 + (1 - 质量) * (最大额外惩罚)
            extra_slippage = (1.0 - liquidity_quality) * (max_slippage_bps - base_slippage_bps)
            total_slippage_bps = base_slippage_bps + extra_slippage
            
            # 4. 价格调整 (假设是入场推迟)
            # 滑点 1 bps = 0.0001
            adjustment_factor = 1.0 + (total_slippage_bps / 10000.0)
            adjusted_price = round(price * adjustment_factor, 2)
            
            return {
                "original_price": price,
                "price_adjusted": adjusted_price,
                "slippage_bps": round(total_slippage_bps, 2),
                "liquidity_quality": round(liquidity_quality, 3),
                "is_vacuum_zone": bool(liquidity_quality < 0.1)
            }
        except Exception as e:
            logger.error(f"MathTools: Slippage calculation failure: {e}")
            return {"price_adjusted": price, "slippage_bps": base_slippage_bps, "error": str(e)}
