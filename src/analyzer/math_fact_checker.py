"""MathFactChecker — deterministic trade geometry verification."""
import logging
from typing import Any
from src.utils.math_utils import MathToolsNamespace
from src.utils.datetime_utils import get_interval_minutes

logger = logging.getLogger(__name__)


class MathFactChecker:
    """Deterministic math verification for AI trade proposals.

    This logic offloads complex trade geometry (RR, ATR, Isolation) to Python code,
    ensuring the audit loop is anchored by physical market reality.
    """

    def __init__(self, math_tools: MathToolsNamespace, session_config, critic_config,
                 macro_interval: str):
        self.math = math_tools
        self.session_config = session_config
        self.critic_config = critic_config
        self.macro_interval = macro_interval

    def verify(self, plan: dict[str, Any], observation: dict[str, Any]) -> dict[str, Any]:
        """Calculates deterministic mathematical truth for an AI proposal.

        Args:
            plan: The current tactical proposal from the Session Analyst.
            observation: Baseline topographical telemetry.

        Returns:
            A compliance dictionary containing verified metrics and a truth verdict.
        """
        try:
            # Handle plan error or neutral stance
            if plan.get("error"):
                return {"status": "ERROR", "reason": "Proposal execution failed."}

            opinion = plan.get("opinion", "NEUTRAL")
            if opinion == "NEUTRAL":
                return {"status": "SKIPPED", "reason": "Neutral proposal requires no math audit."}

            tactical = plan.get('tactical_parameters', {})
            entry = float(tactical.get('entry', 0) or 0)
            sl = float(tactical.get('stop_loss', 0) or 0)
            tp = float(tactical.get('take_profit', 0) or 0)

            # Topography Metrics
            metrics = observation.get('quantitative_metrics', {})
            dynamics = metrics.get('price_dynamics', {})
            topo = metrics.get('volume_profile', {})

            atr = float(dynamics['atr_macro'])
            poc = float(topo.get('poc', 0))
            vah = float(topo.get('vah', 0))
            val = float(topo.get('val', 0))

            regime = metrics.get('market_regime', {})
            trend_intensity = float(regime.get('trend_intensity', 0))

            # Verified Metrics Calculation
            rr_results = self.math.calculate_risk_reward(entry, tp, sl)
            atr_metrics = self.math.calculate_atr_metrics(entry, sl, tp, atr)
            proximity = self.math.calculate_structural_proximity(sl, atr, poc, vah, val)

            from src.utils.math_utils import RegimePhysicsConfig
            physics = RegimePhysicsConfig(
                min_velocity_floor=self.session_config.temporal.min_trade_velocity,
                ti_thresh=self.critic_config.regime.trend_intensity_threshold,
                ti_strong=self.critic_config.regime.trend_intensity_strong,
                vr_base=self.critic_config.regime.volatility_baseline_ratio,
                vr_extreme=self.critic_config.regime.volatility_extreme_ratio,
                dilation_dead_water=self.session_config.temporal.temporal_dilation_dead_water,
                dilation_highway=self.session_config.temporal.temporal_dilation_highway,
                dilation_climax=self.session_config.temporal.temporal_dilation_climax,
                dilation_standard=self.session_config.temporal.temporal_dilation_standard,
                weight_dead_water=self.session_config.temporal.temporal_weight_dead_water,
                weight_highway=self.session_config.temporal.temporal_weight_highway,
                weight_climax=self.session_config.temporal.temporal_weight_climax,
                weight_standard=self.session_config.temporal.temporal_weight_standard,
            )
            holding_time = self.math.project_holding_time(
                current_price=float(tactical.get('current_price', 0) or 0),
                entry=entry, take_profit=tp, atr=atr,
                trend_intensity=trend_intensity,
                volatility_intensity_index=float(dynamics['volatility_intensity_index']),
                normalized_velocity=float(dynamics.get('normalized_velocity', 0)),
                interval_minutes=get_interval_minutes(self.macro_interval),
                physics=physics,
            )

            # Compliance Verdict Synthesis (Aligned with Highway Threshold)
            is_trending = abs(trend_intensity) >= self.critic_config.regime.trend_intensity_threshold

            # Chaos-Aware Math Audit
            # In 'IS_CHAOS' regimes, survival (shielding) takes precedence over standard RR hulls.
            # We apply the chaos_rr_discount to the threshold to allow low-RR survival plans to pass.
            vol_expansion = dynamics.get('volatility_expansion_index', 1.0)
            is_chaos = vol_expansion > self.critic_config.regime.volatility_extreme_ratio

            min_rr = self.session_config.risk.min_rr_trending if is_trending else self.session_config.risk.min_rr_ranging

            if is_chaos:
                min_rr *= (1.0 - self.session_config.risk.chaos_rr_discount)
                logger.info(f"MathFactChecker: IS_CHAOS detected. Applying {self.session_config.risk.chaos_rr_discount*100}% RR discount. New min_rr={min_rr:.2f}")

            # Shielding check
            buffer = self.critic_config.risk.structural_buffer_atr
            prox_values = [v for v in proximity.values() if v is not None]
            is_shielded = (any(v < -buffer for v in prox_values) if opinion == "BULLISH"
                           else any(v > buffer for v in prox_values))

            compliance = {
                "rr_is_valid": rr_results.get("rr_ratio", 0) >= min_rr,
                "sl_is_shielded": is_shielded,
                "atr_volatility_is_logical": atr_metrics.get("entry_to_sl_atr", 0) < self.critic_config.risk.poc_gravity_atr_distance
            }

            return {
                "status": "VERIFIED",
                "rr_verification": rr_results,
                "atr_volatility_verification": atr_metrics,
                "structural_armor_verification": proximity,
                "holding_time_verification": holding_time,
                "compliance_verdict": compliance
            }
        except Exception as e:
            logger.error(f"MathFactChecker: Math fact check failed: {e}")
            return {"error": "VERIFICATION_FAILURE", "details": str(e)}
