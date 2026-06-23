"""
Session Agent — the "Thesis" role in the Binary Star adversarial protocol.

Terminology note: "Session" in this module refers to the LLM agent role
(Session Analyst / Thesis proposer).  It is distinct from:
  - A trading session (a market position lifecycle)
  - A log file (session.log)
  - A single inference cycle (execute_session_cycle)

The Session Agent proposes trade blueprints; the Critic Agent audits them.
"""
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

# Initialize session-specific logger
logger = setup_logger(__name__, propagate=True)

@dataclass(frozen=True)
class SessionConfig(AgentConfig):
    """Strategic configuration for the Session Analyst (the Thesis agent in Binary Star).

    Composed from logical sub-configs.  Note: "Session" refers to the LLM agent
    role (not a trading session, log file, or inference cycle).
    """
    regime: RegimeConfig
    temporal: TemporalConfig
    risk: RiskConfig
    audit: AuditConfig
    visual: VisualConfig
    strategy_intent: str
    macro_interval: str
    micro_interval: str
    instruction_literal: Optional[str] = None

    @classmethod
    def from_dict(cls, cfg: dict[str, Any], instruction_literal: Optional[str] = None) -> "SessionConfig":
        """Factory method to assemble a SessionConfig from the global YAML structure."""
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
            model_temperature=float(provider_cfg.get("session_temperature", 0.5)),
            instruction_path=os.path.join(resolve_project_root(), llm_cfg["binary_star"]["session_role_prompt"]),
            max_tool_iterations=int(cfg["network"]["gemini"]["max_tool_iterations"]),
            regime=load_regime_config(cfg),
            temporal=load_temporal_config(cfg),
            risk=load_risk_config(cfg),
            audit=load_audit_config(cfg),
            visual=load_visual_config(cfg),
            strategy_intent=str(cfg.get("strategy_intent", "")),
            macro_interval=str(sampling["macro_context"]["time_interval"]),
            micro_interval=str(sampling["micro_context"]["time_interval"]),
            instruction_literal=instruction_literal,
        )

class SessionAgent(BaseAgent):
    """The Session Analyst & Decision Engine.

    Responsible for transforming topographical telemetry into tactical trade blueprints.
    Operates in an iterative cycle managed by the Orchestrator:
    1. Planning (Temp 0.7): Generates/Refines directional hypotheses and parameterization.
       Higher creativity for exploring potential alpha.
    2. Synthesis (Temp 0.3): Hardens the plan against Critic adversarial feedback in the final round.
       Cold-logic mode enforces alignment with all physical constraints for survivability.
    """
    
    def __init__(
        self, 
        config: SessionConfig, 
        ai_client: AbstractAIClient,
        api_timeout: int,
        retry_count: int,
        retry_multiplier: float,
        retry_min: int,
        retry_max: int,
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

    def execute_session_cycle(
        self,
        observation: Optional[Dict[str, Any]],
        symbol: str,
        temperature: float,
        agent_name: str,
        debate_history: Optional[List[Dict[str, Any]]] = None,
        cache_resource_name: Optional[str] = None,
        tools: Optional[List[Any]] = None,
        visual_parts: Optional[List[Any]] = None,
        system_instruction: Optional[str] = None
    ) -> Dict[str, Any]:
        """Core execution logic for a session reasoning step."""
        logger.info(f"SessionAgent: {agent_name} for {symbol}...")
        try:
            # Build multimodal prompt: integrate physical facts, debate history, and global parameters
            prompt = self._build_prompt(
                observation=observation,
                debate_history=debate_history,
                cache_resource_name=cache_resource_name
            )

            payload = [prompt]
            if not cache_resource_name and visual_parts:
                payload.extend(visual_parts)

            # Execute AI reasoning cycle with cache support and function calling (MathTools)
            return self._execute_ai_cycle(
                payload=payload,
                temperature=temperature,
                agent_name=agent_name,
                cache_resource_name=cache_resource_name,
                tools=tools,
                system_instruction=system_instruction
            )
        except Exception as e:
            logger.error(f"Session: failure during {agent_name} for {symbol}: {e}")
            raise

    def _build_prompt(
        self,
        observation: Optional[Dict[str, Any]],
        debate_history: Optional[List[Dict[str, Any]]] = None,
        cache_resource_name: Optional[str] = None,
    ) -> str:
        """Internal logic for constructing the multimodal reasoning context.

        Orchestrates variable injection for both zero-cache (direct)
        and high-context (cached) inference modes.
        """
        if cache_resource_name:
            observation_json = "[CONTEXT_PROVIDED_VIA_GEMINI_CACHE]"
        elif observation:
            observation_json = json.dumps(observation, indent=2, ensure_ascii=False)
        else:
            raise ValueError("Session: Reasoning attempted without market telemetry.")

        context = {
            "observation_json": observation_json,
            "debate_history_json": json.dumps(debate_history, indent=2, ensure_ascii=False) if debate_history else "null",
            "strategy_intent": self.config.strategy_intent,
            "min_rr_ranging": self.config.risk.min_rr_ranging,
            "min_rr_trending": self.config.risk.min_rr_trending,
            "structural_buffer_atr": self.config.risk.structural_buffer_atr,
            "poc_gravity_atr_distance": self.config.risk.poc_gravity_atr_distance,
            "breakout_frontrun_atr": self.config.regime.breakout_frontrun_atr,
            "max_entry_distance_atr": self.config.risk.max_entry_distance_atr,
            "chaos_rr_discount": self.config.risk.chaos_rr_discount
        }
        
        return self._prepare_prompt(self.config.instruction_path, **context)


