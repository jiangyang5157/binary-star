"""DebateLoop — adversarial debate round management."""
import logging
from typing import Any

from src.analyzer.math_fact_checker import MathFactChecker
from src.utils.exceptions import MalformedJSONError

logger = logging.getLogger(__name__)


class DebateLoop:
    """Manages the round-by-round adversarial debate between Session and Critic."""

    def __init__(self, session_agent, critic_agent, math_checker: MathFactChecker,
                 max_rounds: int,
                 tools: list, shared_instruction: str,
                 session_config, critic_config,
                 visual_text: str | None = None):
        self.session_agent = session_agent
        self.critic_agent = critic_agent
        self.math_checker = math_checker
        self.max_rounds = max_rounds
        self.tools = tools
        self.shared_instruction = shared_instruction
        self.session_config = session_config
        self.critic_config = critic_config
        self.visual_text = visual_text

    def run(self, observation: dict, symbol: str,
            progress_callback=None) -> dict[str, Any]:
        """Execute the full debate and return final results.

        Args:
            progress_callback: Optional fn(stage, activity, stage_label=...)
                for progress reporting.

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

            # Progress: debate round starting — Session Agent
            if progress_callback:
                progress_callback(
                    stage=3,
                    activity=f"Debate R{current_round} · Session LLM planning…",
                    stage_label=f"Debate · Round {current_round}/{self.max_rounds}",
                )

            # Planning / Refinement
            logger.info(f"[{symbol}] debate R{current_round} planning | agent=Session_Planning")
            last_plan = self.session_agent.execute_session_cycle(
                observation=observation,
                symbol=symbol,
                temperature=self.session_config.model_temperature,
                agent_name=f"Session_Planning_R{current_round}",
                tools=self.tools,
                debate_history=compressed_history,
                visual_text=self.visual_text,
                system_instruction=self.shared_instruction
            )

            # Validate response type before any expensive operations
            if not isinstance(last_plan, dict):
                logger.error(
                    "[%s] session agent returned %s instead of dict | raw=%s",
                    symbol, type(last_plan).__name__, str(last_plan)[:300],
                )
                raise MalformedJSONError(
                    raw_text=str(last_plan)[:500],
                    agent_name="SessionAgent",
                )

            # Adversarial Audit (Math Fact Check Injection)
            if progress_callback:
                progress_callback(
                    stage=3,
                    activity=f"Debate R{current_round} · Math verification…",
                )
            logger.info(f"[{symbol}] debate R{current_round} running critic audit")
            math_fact_check = self.math_checker.verify(last_plan, observation)

            if progress_callback:
                math_status = math_fact_check.get("status", "UNKNOWN")
                progress_callback(
                    stage=3,
                    activity=f"Debate R{current_round} · Math: {math_status}",
                )

            # Full adversarial review — critic always runs (handles NEUTRAL via
            # its own NEUTRALITY PARADOX protocol, no Python-level bypass needed).
            if progress_callback:
                progress_callback(
                    stage=3,
                    activity=f"Debate R{current_round} · Critic LLM reviewing…",
                )
            critic_results = self.critic_agent.evaluate(
                observation=observation,
                last_plan=last_plan,
                symbol=symbol,
                debate_history=compressed_history,
                math_fact_check=math_fact_check,
                tools=None,
                visual_text=self.visual_text,
                system_instruction=self.shared_instruction
            )

            # Score Telemetry
            veto_level = critic_results.get('veto_level', 'UNKNOWN').upper()
            logger.info(f"[{symbol}] debate R{current_round} audit | veto={veto_level}")

            if progress_callback:
                progress_callback(
                    stage=3,
                    activity=f"Debate R{current_round} · Critic: {veto_level}",
                )

            debate_history.append({
                "round": current_round,
                "plan": last_plan,
                "critic": critic_results,
                "math_fact_check": math_fact_check
            })

            # Smart Round Control (Early Exit on PASS or WEAK)
            if veto_level in ["PASS", "WEAK"]:
                logger.info(f"[{symbol}] debate R{current_round} {veto_level} → early exit")
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
