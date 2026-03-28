import os
import json
from dataclasses import dataclass
from typing import Dict, Any, Optional
from google import genai
from google.genai import types

from src.agent.base_agent import BaseAgent
from src.utils.agent_utils import read_prompt_template, safe_format
from src.utils.path_utils import resolve_project_root
from src.utils.json_utils import extract_json_from_text

from src.utils.logger_utils import setup_logger
logger = setup_logger(__name__)

@dataclass(frozen=True)
class CriticConfig:
    """Encapsulates configuration for the CriticAgent."""
    model: str
    role_prompt_path: str
    temperature: float
    sl_structural_buffer_floor: float
    sl_structural_buffer_ceiling: float
    strategy_intent: str
    macro_interval: str
    micro_interval: str

    @classmethod
    def from_dict(cls, full_config: Dict[str, Any]) -> "CriticConfig":
        """Factory method to extract critic config from the global config dict."""
        critic = full_config['critic']
        strat = full_config['strategist']
        return cls(
            model=str(critic['model']),
            role_prompt_path=os.path.join(resolve_project_root(), critic['role_definition_prompt']),
            temperature=float(critic['temperature']),
            sl_structural_buffer_floor=float(strat['sl_structural_buffer_floor']),
            sl_structural_buffer_ceiling=float(strat['sl_structural_buffer_ceiling']),
            strategy_intent=str(full_config.get('strategy_intent', 'Universal Crypto Logic')),
            macro_interval=str(full_config['observer']['macro_analysis_context']['time_interval']),
            micro_interval=str(full_config['observer']['micro_analysis_context']['time_interval'])
        )

class CriticAgent(BaseAgent):
    """
    The Skeptical Risk Auditor (Adversarial Agent).
    
    This agent performs a high-fidelity stress test on the Strategist's draft.
    It identifies hidden flaws, structural traps, and math violations by 
    contrasting the draft against 'Math Fact Check' telemetry and volume topography.
    """
    def __init__(self, config_dict: Dict[str, Any], api_key: str, ai_client: Optional[genai.Client] = None):
        """
        Initializes the Critic with configuration.
        """
        self.config = CriticConfig.from_dict(config_dict)
        super().__init__(
            model=self.config.model,
            temperature=self.config.temperature,
            api_key=api_key,
            ai_client=ai_client
        )

    def audit(self, observation: Dict[str, Any], draft_plan: Dict[str, Any], math_fact_check: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Performs an adversarial audit of a proposed trading draft.
        
        Args:
            observation: The forensic market map (Observer output).
            draft_plan: The proposed strategy from Strategist (Phase A).
            math_fact_check: Deterministic math facts (RR, ATR distances) to prevent LLM hallucination.
            
        Returns:
            A critique dictionary containing 'is_veto' status and risk tags (e.g., [CLEAR], [LIQUIDITY_VOID]).
        """
        # Prepare semantic context for the audit session
        context = {
            "observation_json": json.dumps(observation, indent=2, ensure_ascii=False),
            "draft_plan": json.dumps(draft_plan, indent=2, ensure_ascii=False),
            "math_fact_check": json.dumps(math_fact_check, indent=2, ensure_ascii=False) if math_fact_check else "Not provided by system.",
            "sl_structural_buffer_floor": self.config.sl_structural_buffer_floor,
            "sl_structural_buffer_ceiling": self.config.sl_structural_buffer_ceiling,
            "strategy_intent": self.config.strategy_intent,
            "macro_interval": self.config.macro_interval,
            "micro_interval": self.config.micro_interval
        }
        
        prompt = self._prepare_prompt(self.config.role_prompt_path, **context)
        
        logger.info("Critic: Performing adversarial audit...")
        return self._execute_ai_cycle(prompt, agent_name="Critic")
