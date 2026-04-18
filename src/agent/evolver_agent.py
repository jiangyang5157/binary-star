import os
import json
import logging
from dataclasses import dataclass
from typing import Dict, Any, List, Optional
from google import genai
from src.agent.base_agent import BaseAgent, AgentConfig
from src.utils.path_utils import resolve_project_root
from src.utils.rate_limiter import CongestionController

logger = logging.getLogger("EvolverAgent")

@dataclass(frozen=True)
class EvolverConfig(AgentConfig):
    """Configuration for the Evolver meta-agent."""
    model: str
    model_temperature: float
    instruction_path: str
    max_tool_iterations: int

    @classmethod
    def from_dict(cls, cfg: Dict[str, Any]) -> "EvolverConfig":
        """Factory method to extract evolver config from the standalone evolver node."""
        evolver_cfg = cfg.get('evolver', {})
        # Note: role_definition_prompt is the legacy key in strategy_config.yaml
        return cls(
            model=str(evolver_cfg['model']),
            instruction_path=os.path.join(resolve_project_root(), cfg['evolution']['role_definition_prompt']),
            model_temperature=float(evolver_cfg['model_temperature']),
            max_tool_iterations=int(cfg['network']['gemini']['max_tool_iterations'])
        )

class EvolverAgent(BaseAgent):
    """The Meta-Optimizer for the Singularity Engine.

    Responsible for Darwinian evolution of the strategy and reasoning layers. 
    Transforms forensic audit failures into 'Physical Laws' (Configuration 
    Patches) and 'Semantic Refinements' (Prompt Distillation).
    """
    def __init__(
        self, 
        config: EvolverConfig, 
        ai_client: genai.Client,
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
        self.config = config

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
            # v7.8: Compress audit reports to remove redundant observation topography (Token Optimization)
            compressed_reports = self._compress_audit_reports(audit_reports)
            reports_json = json.dumps(compressed_reports, indent=2)
            config_json = json.dumps(active_config, indent=2)
            
            # v6.11: Partitioned Markdown aggregation for precise semantic targeting
            prompts_md = ""
            for module, content in current_instructions.items():
                prompts_md += f"# {module.lower()}_PROMPT\n{content}\n\n"

            logger.info(
                f"Evolver: Injected Context Size: "
                f"Reports={len(reports_json)} chars | "
                f"Config={len(config_json)} chars | "
                f"Prompts={len(prompts_md)} chars"
            )

            prompt = self._prepare_prompt(
                self.config.instruction_path,
                audit_reports_json=reports_json,
                active_config_yaml=config_json,
                current_prompt_md=prompts_md,
                strategy_intent=active_config['strategy_intent'],
                regime_parameters=active_config['regime_parameters'],
                trend_intensity_threshold=active_config['regime_parameters']['trend_intensity_threshold'],
                volatility_extreme_ratio=active_config['regime_parameters']['volatility_extreme_ratio'],
                structural_buffer_atr=active_config['regime_parameters']['structural_buffer_atr'],
                stop_loss_buffer_min=active_config['binary_star']['session']['stop_loss_buffer_min'],
                mae_threshold_pinpoint=active_config['audit_review']['mae_threshold_pinpoint'],
                mae_threshold_standard=active_config['audit_review']['mae_threshold_standard'],
                mae_threshold_luck=active_config['audit_review']['mae_threshold_luck'],
                max_rounds=active_config['binary_star']['max_rounds'],
            )

            logger.info("Evolver: Initiating distillation/patching cycle (Neural Meta-Analysis)...")
            
            evolution_result = self._execute_ai_cycle(
                payload=prompt,
                temperature=self.config.model_temperature,
                agent_name="Evolver_Meta",
                tools=None
            )
            
            # v6.11: Resilience - Handle cases where the model wraps the JSON in a list
            if isinstance(evolution_result, list) and len(evolution_result) > 0:
                logger.info("Evolver: AI returned a list. Extracting the first element.")
                evolution_result = evolution_result[0]
            
            if not isinstance(evolution_result, dict):
                logger.error(f"Evolver: AI returned non-dict result: {type(evolution_result)}")
                raise ValueError("AI_RESULT_FORMAT_ERROR: Expected dict, got " + str(type(evolution_result)))

            return evolution_result
            
        except Exception as e:
            logger.error(f"Evolver: Meta-optimization failed: {e}")
            raise
    def _compress_audit_reports(self, reports: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Summarizes forensic audit reports to remove massive topographical noise.
        We keep the decision, debate history, and performance metrics, but remove 
        the raw observation data which is often redundant for global strategy evolution.
        """
        compressed = []
        for report in reports:
            c_report = {
                "symbol": report.get("symbol"),
                "timestamp": report.get("observed_at"),
                "final_decision": report.get("final_decision", {}),
                "performance": report.get("performance", {}),
                "debate_summary": []
            }
            
            # Summarize debate history to keep logic drift visibility
            history = report.get("debate_history", [])
            for entry in history:
                c_report["debate_summary"].append({
                    "round": entry.get("round"),
                    "opinion": entry.get("plan", {}).get("opinion"),
                    "veto_level": entry.get("critic", {}).get("veto_level"),
                    "invalidations": entry.get("critic", {}).get("invalidations")
                })
            
            # Include a high-fidelity summary of quantitative metrics for structural contrast
            obs = report.get("observation", {})
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
