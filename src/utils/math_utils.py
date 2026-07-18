import math
import logging
from dataclasses import dataclass
import numpy as np
from typing import Dict, Any, Optional, List

# Initialize standard hardened logger for math telemetry
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RegimePhysicsConfig:
    """Bundled config values for regime detection and temporal dilation.

    These values come from strategy_config.yaml (regime_parameters + temporal_parameters)
    and are passed as a group to get_regime_scalars() and project_holding_time().
    """
    # Velocity
    min_velocity_floor: float
    # Thresholds (from RegimeConfig)
    ti_thresh: float
    ti_strong: float
    vr_base: float
    vr_extreme: float
    # Dilation modifiers (from TemporalConfig)
    dilation_dead_water: float
    dilation_highway: float
    dilation_climax: float
    dilation_standard: float
    # Weight modifiers (from TemporalConfig)
    weight_dead_water: float
    weight_highway: float
    weight_climax: float
    weight_standard: float


def build_physics_config(session_config, critic_config) -> RegimePhysicsConfig:
    """Factory: build RegimePhysicsConfig from session and critic config sub-objects.

    Centralises the mapping so orchestrator and math checker stay in sync.
    """
    return RegimePhysicsConfig(
        min_velocity_floor=session_config.temporal.min_trade_velocity,
        ti_thresh=critic_config.regime.trend_intensity_threshold,
        ti_strong=critic_config.regime.trend_intensity_strong,
        vr_base=critic_config.regime.volatility_baseline_ratio,
        vr_extreme=critic_config.regime.volatility_extreme_ratio,
        dilation_dead_water=session_config.temporal.temporal_dilation_dead_water,
        dilation_highway=session_config.temporal.temporal_dilation_highway,
        dilation_climax=session_config.temporal.temporal_dilation_climax,
        dilation_standard=session_config.temporal.temporal_dilation_standard,
        weight_dead_water=session_config.temporal.temporal_weight_dead_water,
        weight_highway=session_config.temporal.temporal_weight_highway,
        weight_climax=session_config.temporal.temporal_weight_climax,
        weight_standard=session_config.temporal.temporal_weight_standard,
    )



def get_tool_declarations() -> list[dict]:
    """Return LLM function-calling schemas for the supported tools.

    Co-located with implementations so parameter changes stay in sync.
    """
    return [
        {
            "name": "calculate_trade_geometry",
            "description": "Validates a trade geometry: RR ratio, ATR-standardised distances, entry offset, and SL proximity to structural anchors. Returns errors for invalid inputs (zero/negative prices, NaN, zero ATR).",
            "parameters": {
                "type": "OBJECT",
                "properties": {
                    "current_price": {
                        "type": "NUMBER",
                        "minimum": 0,
                        "description": "Current market price. Must be positive."
                    },
                    "entry": {
                        "type": "NUMBER",
                        "minimum": 0,
                        "description": "Proposed entry price. Must be positive."
                    },
                    "take_profit": {
                        "type": "NUMBER",
                        "minimum": 0,
                        "description": "Take-profit target. Must be positive."
                    },
                    "stop_loss": {
                        "type": "NUMBER",
                        "minimum": 0,
                        "description": "Stop-loss price. Must be positive."
                    },
                    "atr": {
                        "type": "NUMBER",
                        "minimum": 0,
                        "description": "Average True Range — measures market volatility in price terms. Must be positive."
                    },
                    "poc": {
                        "type": "NUMBER",
                        "minimum": 0,
                        "description": "Point of Control — price level with highest traded volume. Must be positive. Optional."
                    },
                    "vah": {
                        "type": "NUMBER",
                        "minimum": 0,
                        "description": "Value Area High — upper boundary of the value zone. Must be positive.Optional."
                    },
                    "val": {
                        "type": "NUMBER",
                        "minimum": 0,
                        "description": "Value Area Low — lower boundary of the value zone. Must be positive. Optional."
                    },
                },
                "required": ["current_price", "entry", "take_profit", "stop_loss", "atr"],
            },
        },
    ]

def calculate_risk_reward(
    entry: float,
    take_profit: float,
    stop_loss: float
) -> Dict[str, Any]:
    """Calculate the Risk-Reward (RR) ratio for a limit order.

    Args:
        entry: Entry price.
        take_profit: Take-profit price.
        stop_loss: Stop-loss price.

    Returns:
        Dict containing rr_ratio, profit_distance, and risk_distance.
    """
    try:
        # Basic validation: ensure inputs are positive and finite
        if entry <= 0 or take_profit <= 0 or stop_loss <= 0:
            return {"error": "All price inputs must be positive numbers."}
        if any(math.isnan(x) or math.isinf(x) for x in (entry, take_profit, stop_loss)):
            return {"error": "Invalid price input (NaN or Infinity)."}

        sl_dist = abs(entry - stop_loss)
        tp_dist = abs(take_profit - entry)
        
        # Zero-stop-loss guard: prevent division by zero
        if sl_dist < 1e-8:  # epsilon check instead of zero
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
        logger.error(f"RR calc failed | error={e}")
        return {"error": str(e)}


def effective_entry_delta(entry_price: float, sl_price: float, taker_fee_rate: float = 0.0) -> float:
    """Per-unit total cost: SL distance + round-trip trading fees.

    Returns the effective loss per unit if stop-loss is hit, accounting for
    both the adverse price move and the exchange taker fees on entry + exit.

    Args:
        entry_price: Order entry price.
        sl_price: Stop-loss price.
        taker_fee_rate: Exchange taker fee per side (e.g. 0.001 = 0.1%).
                        Set to 0 to disable fee adjustment (backward compatible).
    """
    delta = abs(entry_price - sl_price)
    if taker_fee_rate > 0:
        delta += taker_fee_rate * 2 * entry_price
    return delta


def calculate_atr_metrics(
    current_price: float | None,
    entry: float,
    stop_loss: float,
    take_profit: float,
    atr: float,
) -> Dict[str, Any]:
    """Standardize entry/SL/TP distances using ATR (Average True Range).

    Converts absolute price distances into volatility units so agents can
    evaluate risk relative to current market granularity.
    """
    try:
        if atr <= 0 or math.isnan(atr) or math.isinf(atr):
            return {"error": "ATR must be > 0 for topographical normalization."}
        if any(x is not None and (math.isnan(x) or math.isinf(x)) for x in (entry, stop_loss, take_profit)):
            return {"error": "Invalid numeric input (NaN or Infinity)."}
            
        metrics = {
            "entry_to_sl_atr": round(abs(entry - stop_loss) / atr, 3),
            "entry_to_tp_atr": round(abs(take_profit - entry) / atr, 3),
        }
        
        if current_price is not None and current_price > 0:
            # Drift: entry offset from current market price (sign-aligned with the legacy system)
            metrics["entry_to_current_atr"] = round((entry - current_price) / atr, 3)
            
        return metrics
    except Exception as e:
        logger.error(f"ATR calc failed | error={e}")
        return {"error": str(e)}

def calculate_structural_proximity(
    stop_loss: float,
    atr: float,
    poc: Optional[float] = None,
    vah: Optional[float] = None,
    val: Optional[float] = None
) -> Dict[str, Any]:
    """Calculate stop-loss distance to structural anchors (POC/VAH/VAL).

    Validates whether the stop is protected by physical armor.
    Positive values = SL above anchor; negative = SL below anchor.
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
        logger.error(f"structural proximity failed | error={e}")
        return {"error": str(e)}

def calculate_trade_geometry(
    current_price: float,
    entry: float,
    take_profit: float,
    stop_loss: float,
    atr: float,
    poc: float | None = None,
    vah: float | None = None,
    val: float | None = None,
) -> dict:
    """Combined trade geometry verification: RR + ATR metrics + structural proximity.

    Batch-verifies all three dimensions with a single call to reduce
    LLM tool-call round trips.
    """
    rr = calculate_risk_reward(entry, take_profit, stop_loss)
    atr_met = calculate_atr_metrics(current_price, entry, stop_loss, take_profit, atr)
    prox = calculate_structural_proximity(stop_loss, atr, poc, vah, val)

    # If any sub-function returned an error, propagate the first one found
    for sub_result in (rr, atr_met, prox):
        if "error" in sub_result:
            return {"error": sub_result["error"]}

    result = {
        "rr_ratio": rr.get("rr_ratio"),
        "profit_distance": rr.get("profit_distance"),
        "risk_distance": rr.get("risk_distance"),
        "entry_to_sl_atr": atr_met.get("entry_to_sl_atr"),
        "entry_to_tp_atr": atr_met.get("entry_to_tp_atr"),
        "sl_to_poc_atr": prox.get("sl_to_poc_atr"),
        "sl_to_vah_atr": prox.get("sl_to_vah_atr"),
        "sl_to_val_atr": prox.get("sl_to_val_atr"),
    }
    eca = atr_met.get("entry_to_current_atr")
    if eca is not None:
        result["entry_to_current_atr"] = eca
    return result


def get_regime_scalars(
    trend_intensity: float,
    volatility_intensity_index: float,
    normalized_velocity: float,
    physics: RegimePhysicsConfig,
) -> Dict[str, Any]:
    """Calculates primary physics scalars for a given market regime.

    Args:
        trend_intensity: Efficiency Ratio [-1, 1] for regime triggers.
        volatility_intensity_index: Current vs mean ATR ratio.
        normalized_velocity: Physical ATR/Bar speed for time projection.
        physics: Bundled config values (thresholds, dilation/weight modifiers).
    """
    ti_abs = abs(trend_intensity)

    # Final Velocity is the higher of observed speed or the protocol floor.
    effective_velocity_per_atr = max(normalized_velocity, physics.min_velocity_floor, 1e-9)

    # Regime Detection (Logic gates remain on trend_intensity)
    if volatility_intensity_index >= physics.vr_extreme:
        factor = physics.dilation_climax
        weight = physics.weight_climax
        dilation_variable = "temporal_dilation_climax"
        weight_variable = "temporal_weight_climax"
    elif ti_abs >= physics.ti_thresh:
        factor = physics.dilation_highway
        weight = physics.weight_highway
        dilation_variable = "temporal_dilation_highway"
        weight_variable = "temporal_weight_highway"
    elif volatility_intensity_index < physics.vr_base and ti_abs < physics.ti_strong:
        factor = physics.dilation_dead_water
        weight = physics.weight_dead_water
        dilation_variable = "temporal_dilation_dead_water"
        weight_variable = "temporal_weight_dead_water"
    else:
        factor = physics.dilation_standard
        weight = physics.weight_standard
        dilation_variable = "temporal_dilation_standard"
        weight_variable = "temporal_weight_standard"

    return {
        "effective_velocity_per_atr": effective_velocity_per_atr,
        "temporal_dilation_factor": factor,
        "temporal_dilation_variable": dilation_variable,
        "temporal_weight_factor": weight,
        "temporal_weight_variable": weight_variable
    }

def project_holding_time(
    current_price: float,
    entry: float,
    take_profit: float,
    atr: float,
    trend_intensity: float,
    volatility_intensity_index: float,
    normalized_velocity: float,
    interval_minutes: int,
    physics: RegimePhysicsConfig,
) -> Dict[str, Any]:
    """Calculate precise holding and waiting times using the static scalar engine."""
    try:
        if atr <= 0 or interval_minutes <= 0:
            return {"error": "ATR and interval_minutes must be > 0."}
        if any(math.isnan(x) or math.isinf(x) for x in (trend_intensity, volatility_intensity_index, normalized_velocity)):
            return {"error": "Invalid numeric input (NaN or Infinity)."}

        scalars = get_regime_scalars(
            trend_intensity=trend_intensity,
            volatility_intensity_index=volatility_intensity_index,
            normalized_velocity=normalized_velocity,
            physics=physics,
        )
        
        # Reconstructed physical velocity (effective scalar * ATR)
        effective_velocity = scalars["effective_velocity_per_atr"] * atr
        # Guard: prevent division-by-zero when ATR is microscopic (e.g., stablecoins)
        if effective_velocity <= 1e-12:
            effective_velocity = 1e-12

        # 1. Physical holding time (with execution buffer)
        # Formula = (pure physical flight time) * temporal dilation factor
        # projected_holding_hours serves as the hard tracking deadline for audit scripts.
        dist = abs(take_profit - entry)
        projected_holding_hours = round((dist / effective_velocity * interval_minutes * scalars["temporal_dilation_factor"]) / 60, 1)

        # 2. Waiting time (no buffer, pure physical velocity)
        projected_waiting_hours = 0.0
        if current_price is not None and current_price > 0:
            wait_dist = abs(entry - current_price)
            projected_waiting_hours = round((wait_dist / effective_velocity * interval_minutes) / 60, 1)

        return {
            "projected_holding_hours": projected_holding_hours,
            "projected_waiting_hours": projected_waiting_hours,
            "temporal_weight_factor": scalars["temporal_weight_factor"],
            "temporal_weight_variable": scalars["temporal_weight_variable"]
        }

    except Exception as e:
        logger.error(f"time projection failed | error={e}")
        return {"error": str(e)}


def calculate_opportunity_cost(
    missed_range: float,
    atr_macro: float,
    threshold: float
) -> Dict[str, Any]:
    """Quantify the Cost of Cowardice — missed volatility during neutral decisions.
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
        logger.error(f"opportunity cost failed | error={e}")
        return {"error": str(e)}

def calculate_mae_stress(
    mae_distance: float,
    max_atr_used: float,
    pinpoint: float,
    standard: float,
    luck: float
) -> Dict[str, Any]:
    """Evaluate Maximum Adverse Excursion (MAE) stress level relative to volatility.
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
        logger.error(f"MAE stress failed | error={e}")
        return {"error": str(e)}

def calculate_liquidity_slippage(
    price: float,
    volume_profile: List[Dict[str, Any]],
    atr: float,
    base_slippage_bps: float,
    max_slippage_bps: float,
    opinion: str = "BULLISH"
) -> Dict[str, Any]:
    """Calculate liquidity-sensitive slippage from volume profile.

    Logic:
    - Find the nearest volume bin to the given price.
    - Normalize volume: current bin / max bin volume.
    - Slippage penalty: add to base slippage based on volume vacuum.
    - Entry delay: BULLISH→adjust up (price rises during delay), BEARISH→adjust down.
    """
    try:
        if not volume_profile or atr <= 0:
            return {"price_adjusted": price, "slippage_bps": base_slippage_bps, "warning": "Insufficient profile data."}

        # 1. Find nearest price bin
        prices = np.array([float(d['price']) for d in volume_profile])
        vols = np.array([float(d['volume']) for d in volume_profile])

        idx = (np.abs(prices - price)).argmin()
        local_vol = vols[idx]
        max_vol = vols.max() if vols.size > 0 else 1.0

        # 2. Calculate liquidity quality (0.0 to 1.0)
        liquidity_quality = local_vol / max_vol if max_vol > 0 else 0.0

        # 3. Dynamic slippage (linear model compensating vacuum zones)
        # base slippage + (1 - quality) * (max extra penalty)
        extra_slippage = (1.0 - liquidity_quality) * (max_slippage_bps - base_slippage_bps)
        total_slippage_bps = base_slippage_bps + extra_slippage

        # 4. Price adjustment (entry delay simulation)
        # Slippage: 1 bps = 0.0001
        # BULLISH (buy limit): price rises during delay → adjust upward
        # BEARISH (sell limit): price falls during delay → adjust downward
        slippage_ratio = total_slippage_bps / 10000.0
        if opinion.upper() == "BEARISH":
            adjustment_factor = 1.0 - slippage_ratio
        else:
            adjustment_factor = 1.0 + slippage_ratio
        adjusted_price = round(price * adjustment_factor, 2)
        
        return {
            "original_price": price,
            "price_adjusted": adjusted_price,
            "slippage_bps": round(total_slippage_bps, 2),
            "liquidity_quality": round(liquidity_quality, 3),
            "is_vacuum_zone": bool(liquidity_quality < 0.1)
        }
    except Exception as e:
        logger.error(f"slippage calc failed | error={e}")
        return {"price_adjusted": price, "slippage_bps": base_slippage_bps, "error": str(e)}

# ── Backward-compatible namespace for MathTools.xxx() callers ──────────────
# Prefer importing functions directly, e.g. from src.utils.math_utils import calculate_risk_reward

# Functions that were methods on the old MathTools class
_MATH_TOOLS_FUNCTIONS = [
    get_tool_declarations,
    calculate_risk_reward,
    calculate_atr_metrics,
    calculate_structural_proximity,
    calculate_trade_geometry,
    get_regime_scalars,
    project_holding_time,
    calculate_opportunity_cost,
    calculate_mae_stress,
    calculate_liquidity_slippage,
]


class _MathToolsNamespace:
    """Delegates attribute access to module-level functions.

    ``MathTools()`` returns a **fresh** namespace instance so that callers
    that instantiated the old class (e.g. ``self.math_tools = MathTools()``)
    are not accidentally sharing mutable state.
    """

    def __call__(self):
        new_instance = _MathToolsNamespace()
        for _fn in _MATH_TOOLS_FUNCTIONS:
            setattr(new_instance, _fn.__name__, staticmethod(_fn))
        return new_instance


MathToolsNamespace = _MathToolsNamespace  # public type alias for annotations
MathTools = _MathToolsNamespace()          # singleton for MathTools.xxx() access
for _fn in _MATH_TOOLS_FUNCTIONS:
    setattr(MathTools, _fn.__name__, staticmethod(_fn))
