"""DebateLoop — adversarial debate round management."""
import logging
from typing import Any

from src.analyzer.math_fact_checker import MathFactChecker
from src.utils.exceptions import MalformedJSONError

logger = logging.getLogger(__name__)


class DebateLoop:
    """Manages the round-by-round adversarial debate between Session and Critic."""

    def __init__(self, session_agent, critic_agent, math_checker: MathFactChecker,
                 max_rounds: int, cache_resource_name: str | None,
                 tools: list, visual_parts: list, shared_instruction: str,
                 session_config, critic_config):
        self.session_agent = session_agent
        self.critic_agent = critic_agent
        self.math_checker = math_checker
        self.max_rounds = max_rounds
        self.cache_resource_name = cache_resource_name
        self.tools = tools
        self.visual_parts = visual_parts
        self.shared_instruction = shared_instruction
        self.session_config = session_config
        self.critic_config = critic_config

    def run(self, observation: dict, symbol: str) -> dict[str, Any]:
        """Execute the full debate and return final results.

        Returns:
            {"final_decision": ..., "debate_history": ..., "early_exit": bool}
        """
        current_round = 1
        critic_results = None
        last_plan = None
        debate_history = []
        math_fact_check = None
        early_exit = False

        while current_round <= self.max_rounds:
            compressed_history = self._compress_debate_history(debate_history)

            # Planning / Refinement
            logger.info(f"BinaryStar: Round {current_round} - Generating Session Thesis (Planning State)...")
            last_plan = self.session_agent.execute_session_cycle(
                observation=observation,
                symbol=symbol,
                temperature=self.session_config.model_temperature,
                agent_name=f"Session_Planning_R{current_round}",
                cache_resource_name=self.cache_resource_name,
                tools=self.tools,
                debate_history=compressed_history,
                visual_parts=self.visual_parts,
                system_instruction=self.shared_instruction
            )

            # Validate response type before any expensive operations
            if not isinstance(last_plan, dict):
                logger.error(
                    "BinaryStar: Session agent returned %s instead of dict. Raw: %s",
                    type(last_plan).__name__, str(last_plan)[:300],
                )
                raise MalformedJSONError(
                    raw_text=str(last_plan)[:500],
                    agent_name="SessionAgent",
                )

            # Adversarial Audit (Math Fact Check Injection)
            logger.info(f"BinaryStar: Round {current_round} - Performing Adversarial Audit...")
            math_fact_check = self.math_checker.verify(last_plan, observation)

            # Critic Fast Pass Pre-check (Token Optimization)
            critic_results = None
            opinion = last_plan.get("opinion", "NEUTRAL")
            if opinion == "NEUTRAL" and math_fact_check.get("status") == "SKIPPED":
                fast_pass = self._evaluate_critic_fast_pass(debate_history, observation)
                if fast_pass:
                    critic_results = fast_pass
                    logger.info(f"BinaryStar: Critic Fast Pass successful! Pre-validated with {fast_pass['veto_level']}.")

            if not critic_results:
                critic_results = self.critic_agent.evaluate(
                    observation=observation,
                    last_plan=last_plan,
                    symbol=symbol,
                    debate_history=compressed_history,
                    cache_resource_name=self.cache_resource_name,
                    math_fact_check=math_fact_check,
                    tools=None,
                    visual_parts=self.visual_parts,
                    system_instruction=self.shared_instruction
                )

            # Score Telemetry
            veto_level = critic_results.get('veto_level', 'UNKNOWN').upper()
            logger.info(f"BinaryStar Audit [R{current_round}]: Veto={veto_level}")

            debate_history.append({
                "round": current_round,
                "plan": last_plan,
                "critic": critic_results,
                "math_fact_check": math_fact_check
            })

            # Smart Round Control (Early Exit on PASS or WEAK)
            # Amnesty Clause fast-pass preserves NEUTRAL justification but
            # should NOT block cold synthesis — it may find a creative repair.
            if veto_level in ["PASS", "WEAK"] and not critic_results.get("defer_to_synthesis"):
                logger.info(f"BinaryStar: {veto_level} plan detected in Round {current_round}. Triggering early exit.")
                early_exit = True
                break

            current_round += 1

        return {
            "final_decision": last_plan,
            "debate_history": debate_history,
            "early_exit": early_exit,
        }

    def _compress_debate_history(self, history: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Compresses historical debate rounds to save tokens.
        Keeps key names consistent with prompt expectations but strips heavy text fields.
        """
        if not history:
            return history

        compressed = []
        for i, entry in enumerate(history):
            is_latest = (i == len(history) - 1)

            # If it's the latest round, keep it 100% full for maximum context fidelity
            if is_latest:
                compressed.append(entry)
                continue

            # For older rounds, perform aggressive compression to save tokens
            c_entry = {"round": entry.get("round")}

            plan = entry.get("plan", {})
            c_entry["plan"] = {
                "opinion": plan.get("opinion"),
                "confidence_score": plan.get("confidence_score"),
                "tactical_parameters": plan.get("tactical_parameters", {})
            }
            # Prune Reasoning Chain for old rounds

            critic = entry.get("critic", {})
            c_entry["critic"] = {
                "veto_level": critic.get("veto_level"),
                "invalidations": critic.get("invalidations"),
                "critic_summary": critic.get("critic_summary")
            }
            # Prune Audit Evidence for old rounds

            math_fc = entry.get("math_fact_check", {})
            c_entry["math_fact_check"] = {
                "status": math_fc.get("status"),
                "compliance_verdict": math_fc.get("compliance_verdict")
            }
            compressed.append(c_entry)

        return compressed

    def _evaluate_critic_fast_pass(self, debate_history: list[dict[str, Any]], observation: dict[str, Any]) -> dict[str, Any] | None:
        """Python pre-flight check to bypass Critic API call in deterministic NEUTRAL scenarios."""
        # 1. Check Amnesty Clause
        has_terminal_in_history = any(
            r.get("critic", {}).get("veto_level") == "TERMINAL"
            for r in debate_history
        )
        if has_terminal_in_history:
            return {
                "veto_level": "PASS",
                "invalidations": ["[JUSTIFIED_INACTION]"],
                "audit_evidence": "Amnesty Clause verified: TERMINAL veto in prior round justifies current NEUTRAL stance.",
                "critic_summary": "Neutral stance justified by prior TERMINAL veto.",
                "critic_confidence": None,  # fast-pass bypass, no AI inference
                "defer_to_synthesis": True,  # amnesty justifies NEUTRAL but synthesis may find a creative repair
            }

        # 2. Check strict non-confluence for INACTION_BIAS, TREND_STARVATION, OPPORTUNITY_DENIAL
        metrics = observation.get('quantitative_metrics', {})
        dyn = metrics.get('price_dynamics', {})
        reg = metrics.get('market_regime', {})
        sent = metrics.get('sentiment_signals', {})
        topo = metrics.get('structural_anchors', {})

        sqz_audit_thresh = self.critic_config.regime.squeeze_audit_threshold
        min_vol_part = self.critic_config.regime.min_volume_participation_ratio
        poc_grav_dist = self.critic_config.risk.poc_gravity_atr_distance
        cvd_thresh = self.critic_config.regime.cvd_intensity_threshold
        cvd_extreme = self.critic_config.regime.cvd_intensity_extreme
        ti_strong = self.critic_config.regime.trend_intensity_strong
        vol_base = self.critic_config.regime.volatility_baseline_ratio
        vol_ext = self.critic_config.regime.volatility_extreme_ratio

        squeeze_factor = reg.get('squeeze_factor', 1.0)
        vol_part = reg.get('volume_participation_ratio', 1.0)
        poc_dist = topo.get('poc_dist_atr', 0)

        has_inaction_bias = (squeeze_factor < sqz_audit_thresh and vol_part > min_vol_part) or abs(poc_dist) > poc_grav_dist

        cvd_intens = sent.get('cvd_intensity_ratio', 0)
        has_flow_dom = abs(cvd_intens) > cvd_thresh
        oi_delta = sent.get('oi_delta_micro', 0)
        has_abs_risk = (oi_delta < 0) and (abs(cvd_intens) > cvd_extreme)
        has_opp_denial = has_flow_dom and not has_abs_risk

        vol_exp = dyn.get('volatility_expansion_index', 1.0)
        is_exp = vol_exp > vol_base
        is_chaos = vol_exp > vol_ext
        ti = reg.get('trend_intensity', 0)
        is_trend_strong = abs(ti) > ti_strong
        has_trend_starv = is_exp and not is_chaos and is_trend_strong

        if not has_inaction_bias and not has_opp_denial and not has_trend_starv:
            return {
                "veto_level": "PASS",
                "invalidations": ["[JUSTIFIED_INACTION]"],
                "audit_evidence": "Confluence Audit: No inaction bias, trend starvation, or opportunity denial conditions met.",
                "critic_summary": "Neutral stance justified by telemetry.",
                "critic_confidence": None,  # fast-pass bypass, no AI inference
            }

        return None
