import os
import json
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from src.infrastructure.ai_client import AbstractAIClient
from src.agent.base_agent import BaseAgent, AgentConfig
from src.config.sub_configs import RegimeConfig, TemporalConfig, RiskConfig, AuditConfig, VisualConfig
from src.utils.path_utils import resolve_project_root
from src.utils.logger_utils import setup_logger
from src.utils.rate_limiter import CongestionController

# Initialize critic-specific logger
logger = setup_logger(__name__)

@dataclass(frozen=True)
class CriticConfig(AgentConfig):
    """Risk-centric configuration composed from logical sub-configs."""
    regime: RegimeConfig
    temporal: TemporalConfig
    risk: RiskConfig
    audit: AuditConfig
    visual: VisualConfig
    strategy_intent: str
    macro_interval: str
    micro_interval: str
    cvd_micro_lookback_candles: int
    instruction_literal: Optional[str] = None

    @classmethod
    def from_dict(cls, cfg: dict[str, Any], instruction_literal: Optional[str] = None) -> "CriticConfig":
        """Factory method to assemble a CriticConfig from the global YAML structure."""
        from src.config.loader import (
            load_regime_config, load_temporal_config, load_risk_config,
            load_audit_config, load_visual_config,
        )
        llm_cfg = cfg["llm"]
        provider = llm_cfg.get("active_provider", "gemini").lower()
        provider_cfg = llm_cfg.get(provider, {})
        sampling = cfg["analysis_window"]

        return cls(
            model=str(provider_cfg.get("model")),
            model_temperature=float(provider_cfg.get("critic_temperature", 0.1)),
            instruction_path=os.path.join(resolve_project_root(), cfg["binary_star"]["critic_role_prompt"]),
            max_tool_iterations=int(cfg["llm"]["max_tool_iterations"]),
            regime=load_regime_config(cfg),
            temporal=load_temporal_config(cfg),
            risk=load_risk_config(cfg),
            audit=load_audit_config(cfg),
            visual=load_visual_config(cfg),
            strategy_intent=str(cfg.get("strategy_intent", "")),
            macro_interval=str(sampling["macro_context"]["time_interval"]),
            micro_interval=str(sampling["micro_context"]["time_interval"]),
            cvd_micro_lookback_candles=int(sampling["tensors"]["cvd_micro_lookback_candles"]),
            instruction_literal=instruction_literal,
        )

class CriticAgent(BaseAgent):
    """Acts as the adversarial counterpart to the SessionAgent.

    Standardized to identify logical lapses, directional bias, and geometric
    violations in trade proposals by contrasting them against Math Truth.
    Its sole mission is finding flaws in proposals — a purely negating audit,
    not opportunity-seeking.
    """

    def __init__(
        self,
        config: CriticConfig,
        api_timeout: int,
        retry_count: int,
        retry_multiplier: float,
        retry_min: int,
        retry_max: int,
        ai_client: AbstractAIClient,
        congestion_controller: Optional[CongestionController] = None
    ):
        """Standard constructor with dependency injection."""
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

    def evaluate(
        self,
        observation: Optional[Dict[str, Any]],
        last_plan: Dict[str, Any],
        symbol: str,
        debate_history: Optional[List[Dict[str, Any]]] = None,
        math_fact_check: Optional[Dict[str, Any]] = None,
        tools: Optional[List[Any]] = None,
        visual_text: Optional[str] = None,
        system_instruction: Optional[str] = None
    ) -> Dict[str, Any]:
        """Evaluates the proposed plan against physical market topography
        and the mandatory CRITIC_CODES table. This is a cold,
        deterministic audit designed to identify structural traps.
        """
        logger.info(f"[{symbol}] auditing proposal")
        try:
            context = self._build_context(
                observation, last_plan,
                debate_history=debate_history,
                math_fact_check=math_fact_check,
            )
            prompt = self._prepare_prompt(self.config.instruction_path, **context)

            # Inject VISUAL_CONTEXT text block for non-vision models
            if visual_text:
                prompt = prompt + '\n\n' + visual_text
                logger.info(
                    "[%s] Critic_Evaluation visual_text injected | chars=%d",
                    symbol, len(visual_text),
                )

            return self._execute_ai_cycle(
                payload=[prompt],
                temperature=self.config.model_temperature,
                agent_name="Critic_Evaluation",
                tools=tools,
                system_instruction=system_instruction,
            )
        except Exception as e:
            logger.error(f"[{symbol}] evaluation failed | error={e}")
            raise

    def _build_context(
        self,
        observation: Optional[Dict[str, Any]],
        last_plan: Dict[str, Any],
        debate_history: Optional[List[Dict[str, Any]]] = None,
        math_fact_check: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Internal logic for constructing the adversarial audit context."""
        if observation:
            observation_json = json.dumps(observation, indent=2, ensure_ascii=False)
        else:
            raise ValueError("Critic: Audit attempted without baseline telemetry.")

        return {
            "observation_json": observation_json,
            "strategy_intent": self.config.strategy_intent,
            "last_plan": json.dumps(last_plan, indent=2, ensure_ascii=False),
            "debate_history_json": json.dumps(debate_history, indent=2, ensure_ascii=False) if debate_history else "null",
            "math_fact_check": json.dumps(math_fact_check, indent=2, ensure_ascii=False) if math_fact_check else "{}",
            "long_short_imbalance_ratio": self.config.regime.long_short_imbalance_ratio,
            "short_heavy_imbalance_ratio": self.config.regime.short_heavy_imbalance_ratio,
            "poc_gravity_atr_distance": self.config.risk.poc_gravity_atr_distance,
            "vacuum_risk_score": self.config.regime.vacuum_risk_score,
            "trend_intensity_strong": self.config.regime.trend_intensity_strong,
            "trend_intensity_min_expansion": self.config.regime.trend_intensity_min_expansion,
            "min_rr_ranging": self.config.risk.min_rr_ranging,
            "min_rr_trending": self.config.risk.min_rr_trending,
            "squeeze_audit_threshold": self.config.regime.squeeze_audit_threshold,
            "structural_buffer_atr": self.config.risk.structural_buffer_atr,
            "cvd_intensity_threshold": self.config.regime.cvd_intensity_threshold,
            "min_volume_participation_ratio": self.config.regime.min_volume_participation_ratio,
            "funding_extreme_threshold": self.config.regime.funding_extreme_threshold,
            "max_holding_hours": self.config.risk.max_holding_hours,
            "temporal_dilation_dead_water": self.config.temporal.temporal_dilation_dead_water,
            "temporal_dilation_highway": self.config.temporal.temporal_dilation_highway,
            "temporal_dilation_climax": self.config.temporal.temporal_dilation_climax,
            "temporal_dilation_standard": self.config.temporal.temporal_dilation_standard
        }
