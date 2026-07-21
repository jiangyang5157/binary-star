import os
import json
import logging
from dataclasses import dataclass
from typing import Dict, Any, List, Optional
from src.infrastructure.ai_client import AbstractAIClient
from src.agent.base_agent import BaseAgent, AgentConfig
from src.utils.path_utils import resolve_project_root
from src.utils.rate_limiter import CongestionController
from src.utils.json_utils import compact_json
from src.analyzer.regime_states import compute_evolver_states, _format_states

logger = logging.getLogger("EvolverAgent")

@dataclass(frozen=True)
class EvolverConfig(AgentConfig):
    """Configuration for the Evolver meta-agent."""

    @classmethod
    def from_dict(cls, cfg: Dict[str, Any]) -> "EvolverConfig":
        """Factory method to extract evolver config from llm.agents.evolver."""
        llm_cfg = cfg['llm']
        active_provider = llm_cfg.get('active_provider')
        if not active_provider:
            raise ValueError("active_provider is not set in llm configuration.")
        active_provider = active_provider.lower()
        provider_cfg = llm_cfg.get(active_provider, {})
        model = provider_cfg.get('model')

        agent_cfg = cfg['llm']['agents']['evolver']

        return cls(
            model=str(model),
            instruction_path=os.path.join(resolve_project_root(), agent_cfg['role_prompt']),
            model_temperature=float(agent_cfg['temperature']),
            max_tool_iterations=int(cfg['llm']['max_tool_iterations']),
            reasoning_effort=agent_cfg.get('reasoning_effort'),
        )

class EvolverAgent(BaseAgent):
    """The Meta-Optimizer for the BinaryStar Engine.

    Responsible for Darwinian evolution of the strategy and reasoning layers.
    Transforms forensic audit failures into 'Physical Laws' (Configuration
    Patches) and 'Semantic Refinements' (Prompt Distillation).
    """
    def __init__(
        self,
        config: EvolverConfig,
        ai_client: AbstractAIClient,
        api_timeout: int,
        retry_count: int,
        retry_multiplier: float,
        retry_min: int,
        retry_max: int,
        congestion_controller: Optional[CongestionController] = None
    ):
        """Initializes the EvolverAgent with a type-safe configuration.

        Args:
            config: Encapsulated evolver parameters.
            ai_client: Authenticated Gemini client.
            api_timeout: Request timeout in seconds.
            retry_count: Maximum retry attempts.
            retry_multiplier: Retrying backoff multiplier.
            retry_min: Minimum retry delay.
            retry_max: Maximum retry delay.
            congestion_controller: Pacing manager for RPM compliance.
        """
        super().__init__(
            config=config,
            ai_client=ai_client,
            api_timeout=api_timeout,
            retry_count=retry_count,
            retry_multiplier=retry_multiplier,
            retry_min=retry_min,
            retry_max=retry_max,
            congestion_controller=congestion_controller
        )

    def evolve(
        self,
        audit_reports: List[Dict[str, Any]],
        active_config: Dict[str, Any],
        current_instructions: Dict[str, str]
    ) -> Dict[str, Any]:
        """Executes the neural meta-optimization cycle.

        Analyzes recent forensic audit reports to identify systematic
        logic failures or edge cases, then generates a corrective mutation.

        Args:
            audit_reports: List of analyzed session results with outcomes.
            active_config: Current active strategy_config.yaml state.
            current_instructions: Mapping of agent names to their instruction source code.

        Returns:
            A dictionary containing the mutation proposal and rationale.
        """
        try:
            # Compress audit reports to remove redundant observation topography (Token Optimization)
            compressed_reports = self._compress_audit_reports(audit_reports)
            reports_json = json.dumps(compressed_reports, indent=2)
            config_json = json.dumps(active_config, indent=2)

            # Pre-computed evolver states
            from src.config.sub_configs import AuditConfig
            audit_cfg = AuditConfig(
                mae_threshold_pinpoint=float(active_config.get('audit_review', {}).get('mae', {}).get('mae_threshold_pinpoint', 0.1)),
                mae_threshold_standard=float(active_config.get('audit_review', {}).get('mae', {}).get('mae_threshold_standard', 0.3)),
                mae_threshold_luck=float(active_config.get('audit_review', {}).get('mae', {}).get('mae_threshold_luck', 0.5)),
                missed_opportunity_atr_threshold=float(active_config.get('audit_review', {}).get('mae', {}).get('missed_opportunity_atr_threshold', 1.0)),
            )
            evolver_states = compute_evolver_states(audit_reports, audit_cfg)
            time_cal = evolver_states.pop("time_calibration_report", {})
            time_cal_json = compact_json(time_cal)

            # Extract batch forensic stats before formatting evolver_states for injection
            fill_rate_pct = evolver_states.pop("fill_rate_pct", 0)
            near_miss_rate = evolver_states.pop("near_miss_rate", 0)
            mae_stress_distribution = evolver_states.pop("mae_stress_distribution", {})
            cowardice_tag_rate = evolver_states.pop("cowardice_tag_rate", 0)

            # Partitioned Markdown aggregation for precise semantic targeting
            prompts_md = ""
            for module, content in current_instructions.items():
                prompts_md += f"# {module.lower()}_PROMPT\n{content}\n\n"

            logger.info(
                f"context injected | reports={len(reports_json)} chars | config={len(config_json)} chars | prompts={len(prompts_md)} chars"
            )

            prompt = self._prepare_prompt(
                self.config.instruction_path,
                audit_reports_json=reports_json,
                active_config_yaml=config_json,
                current_prompt_md=prompts_md,
                strategy_intent=active_config.get('strategy_intent', "N/A"),
                precomputed_evolver_states=_format_states(evolver_states),
                time_calibration_report=time_cal_json,
                fill_rate_pct=fill_rate_pct,
                near_miss_rate=near_miss_rate,
                mae_stress_distribution=mae_stress_distribution,
                cowardice_tag_rate=cowardice_tag_rate,
                regime_parameters=active_config.get('regime_parameters', {}),
                trend_intensity_threshold=active_config.get('regime_parameters', {}).get('trend', {}).get('trend_intensity_threshold'),
                volatility_extreme_ratio=active_config.get('regime_parameters', {}).get('volatility', {}).get('volatility_extreme_ratio'),
                structural_buffer_atr=active_config.get('risk_management', {}).get('structural_buffer_atr'),
                stop_loss_buffer_min=active_config.get('risk_management', {}).get('stop_loss_buffer_min'),
                max_holding_hours=active_config.get('risk_management', {}).get('max_holding_hours'),
                mae_threshold_pinpoint=active_config.get('audit_review', {}).get('mae', {}).get('mae_threshold_pinpoint'),
                mae_threshold_standard=active_config.get('audit_review', {}).get('mae', {}).get('mae_threshold_standard'),
                mae_threshold_luck=active_config.get('audit_review', {}).get('mae', {}).get('mae_threshold_luck'),
                max_rounds=active_config.get('binary_star', {}).get('max_rounds'),
            )

            logger.info("initiating distillation/patching cycle")

            evolution_result = self._execute_ai_cycle(
                payload=prompt,
                temperature=self.config.model_temperature,
                agent_name="Evolver_Meta",
                tools=None
            )

            # Resilience - Handle cases where the model wraps the JSON in a list
            if isinstance(evolution_result, list) and len(evolution_result) > 0:
                logger.info("AI returned list, extracting first element")
                evolution_result = evolution_result[0]

            if not isinstance(evolution_result, dict):
                logger.error(f"non-dict result from AI | type={type(evolution_result)}")
                raise ValueError("AI_RESULT_FORMAT_ERROR: Expected dict, got " + str(type(evolution_result)))

            return evolution_result

        except Exception as e:
            logger.error(f"meta-optimization failed | error={e}")
            raise
    def _compress_audit_reports(self, reports: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Summarizes forensic audit reports to remove massive topographical noise.

        Keeps the decision, FULL debate history, and performance metrics, but removes
        the raw observation data which is often redundant for global strategy evolution.

        Debate detail PRESERVED — Evolver needs to understand WHY a plan was
        rejected/approved to identify logical evolution patterns. Only the heavy
        observation topography is pruned.
        """
        compressed = []
        for report in reports:
            # Field Mapping Correction - Align with actual audit JSON schema
            obs = report.get("observation", {})
            session = report.get("session", {})
            outcome = report.get("market_outcome", {})

            c_report = {
                "symbol": obs.get("symbol"),
                "timestamp": obs.get("observed_at"),
                "final_decision": session.get("final_decision", {}),
                "performance": outcome,
                "debate_summary": []
            }

            # Preserve FULL debate detail for Evolver analysis
            # (reasoning_chain, audit_evidence, math_fact_check are essential
            # for identifying systematic logic failures and evolution patterns)
            history = session.get("debate_history", [])
            for entry in history:
                plan = entry.get("plan", {})
                critic = entry.get("critic", {})
                math_fc = entry.get("math_fact_check", {})

                c_report["debate_summary"].append({
                    "round": entry.get("round"),
                    "plan": plan,
                    "critic": critic,
                    "math_fact_check": math_fc
                })

            # Include a high-fidelity summary of quantitative metrics for structural contrast
            metrics = obs.get("quantitative_metrics", {})
            if metrics:
                c_report["market_context_summary"] = {
                    "market_regime": metrics.get("market_regime", {}),
                    "price_dynamics": metrics.get("price_dynamics", {}),
                    "volume_profile": metrics.get("volume_profile", {}),
                    "structural_anchors": metrics.get("structural_anchors", {}),
                    "sentiment_signals": metrics.get("sentiment_signals", {})
                }

            compressed.append(c_report)
        return compressed
