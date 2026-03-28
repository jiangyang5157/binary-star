import os
import json
from dataclasses import dataclass
from typing import Dict, Any, Optional, List
from google import genai
from google.genai import types

from src.agent.base_agent import BaseAgent
from src.utils.agent_utils import read_prompt_template, safe_format
from src.utils.path_utils import resolve_project_root
from src.utils.logger_utils import setup_logger
logger = setup_logger(__name__)

@dataclass(frozen=True)
class StrategistConfig:
    """Encapsulates configuration for the StrategistAgent."""
    model: str
    role_prompt_path: str
    temperature_draft: float
    temperature_synthesis: float
    min_temporal_efficiency: float
    sl_structural_buffer_floor: float
    sl_structural_buffer_ceiling: float
    strategy_intent: str
    macro_interval: str
    micro_interval: str

    @classmethod
    def from_dict(cls, full_config: Dict[str, Any]) -> "StrategistConfig":
        """Factory method to extract strategist config from the global config dict."""
        strat = full_config['strategist']
        return cls(
            model=str(strat['model']),
            role_prompt_path=os.path.join(resolve_project_root(), strat['role_definition_prompt']),
            temperature_draft=float(strat['temperature_draft']),
            temperature_synthesis=float(strat['temperature_synthesis']),
            min_temporal_efficiency=float(strat['min_temporal_efficiency']),
            sl_structural_buffer_floor=float(strat['sl_structural_buffer_floor']),
            sl_structural_buffer_ceiling=float(strat['sl_structural_buffer_ceiling']),
            strategy_intent=str(full_config.get('strategy_intent', 'Universal Crypto Logic')),
            macro_interval=str(full_config['observer']['macro_analysis_context']['time_interval']),
            micro_interval=str(full_config['observer']['micro_analysis_context']['time_interval'])
        )

class StrategistAgent(BaseAgent):
    """
    The Strategist & Decision Engine.
    
    This agent coordinates the reasoning triad:
    1. PHASE A (DRAFTING): Transforms raw terminal telemetry into an initial 
       strategic execution plan (Limit Entry, TP, SL).
    2. PHASE B (SYNTHESIS): Absorbs adversarial feedback from the Critic 
       to harden the plan, applying 'Deep Limit Entry' (DLE) mitigations 
       where structural risks are identified.
    """
    def __init__(self, config_dict: Dict[str, Any], api_key: str, ai_client: Optional[genai.Client] = None):
        """
        Initializes the Strategist with dual-temperature configuration.
        """
        self.config = StrategistConfig.from_dict(config_dict)
        super().__init__(
            model=self.config.model,
            temperature=self.config.temperature_draft, # Default behavior
            api_key=api_key,
            ai_client=ai_client
        )

    def draft(self, observation: Dict[str, Any]) -> Dict[str, Any]:
        """
        Phase A: DRAFTING - Generates an initial strategic draft.
        
        This phase focuses on structural mapping and execution engineering.
        The prompt is signaled to enter Phase A by passing 'null' for draft/critique.
        """
        prompt = self._build_prompt(observation)
        logger.info("Strategist: Executing PHASE A: DRAFTING (Initial strategic plan)...")
        return self._execute_ai_cycle(
            prompt, 
            temperature=self.config.temperature_draft, 
            agent_name="Strategist"
        )

    def synthesize(self, observation: Dict[str, Any], draft_plan: Dict[str, Any], critique: Dict[str, Any]) -> Dict[str, Any]:
        """
        Phase B: SYNTHESIS - Crystalizes the draft and audit into a final decision.
        
        This phase focuses on risk absorption and confidence calibration.
        The prompt is signaled to enter Phase B by passing populated draft/critique context.
        """
        prompt = self._build_prompt(
            observation, 
            draft_plan=draft_plan, 
            critic_feedback=critique
        )
        logger.info("Strategist: Executing PHASE B: SYNTHESIS (Final strategy)...")
        return self._execute_ai_cycle(
            prompt, 
            temperature=self.config.temperature_synthesis, 
            agent_name="Strategist"
        )

    def _build_prompt(self, observation: Dict[str, Any], **extra_context) -> str:
        """
        Standardizes the context injection for both Drafting and Synthesis phases.
        
        Uses explicit 'null' strings for Phase A signaling, ensuring the LLM 
        processes the correct operational protocols in the template.
        """
        # Load the velocity floor for temporal calculations
        velocity_floor = self.config.min_temporal_efficiency

        # Prepare context (json.dumps handles None as 'null' automatically)
        context = {
            "observation_json": json.dumps(observation, indent=2, ensure_ascii=False),
            "draft_plan": json.dumps(extra_context.get("draft_plan"), indent=2, ensure_ascii=False),
            "critic_feedback": json.dumps(extra_context.get("critic_feedback"), indent=2, ensure_ascii=False),
            "min_temporal_efficiency": velocity_floor,
            "sl_structural_buffer_floor": self.config.sl_structural_buffer_floor,
            "sl_structural_buffer_ceiling": self.config.sl_structural_buffer_ceiling,
            "strategy_intent": self.config.strategy_intent,
            "macro_interval": self.config.macro_interval,
            "micro_interval": self.config.micro_interval
        }
        
        return self._prepare_prompt(self.config.role_prompt_path, **context)
