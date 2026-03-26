from dataclasses import dataclass
import os
import logging
import json
from typing import Dict, Any, List, Optional
from google import genai
from google.genai import types
from src.utils.agent_utils import read_prompt_template, apply_prompt_logic_filters, safe_format
from src.utils.path_utils import resolve_project_root

logger = logging.getLogger(__name__)

@dataclass(frozen=True)
class StrategistConfig:
    """Encapsulates configuration for the StrategistAgent."""
    model: str
    role_prompt_path: str
    temperature_draft: float
    temperature_synthesis: float

    @classmethod
    def from_dict(cls, full_config: Dict[str, Any]) -> "StrategistConfig":
        """Factory method to extract strategist config from the global config dict."""
        strat = full_config['strategist']
        return cls(
            model=str(strat['model']),
            role_prompt_path=os.path.join(resolve_project_root(), strat['role_definition_prompt']),
            temperature_draft=float(strat['temperature_draft']),
            temperature_synthesis=float(strat['temperature_synthesis'])
        )

class StrategistAgent:
    """
    The Strategist & Orchestrator.
    Handles the drafting of initial plans and the final synthesis of 
    adversarial feedback into actionable trading strategies.
    """
    def __init__(self, config_dict: Dict[str, Any], api_key: str, ai_client: Optional[genai.Client] = None):
        """
        Initializes the Strategist with a configuration and optional AI client injection.
        
        Args:
            config_dict: The full application configuration dictionary.
            api_key: Gemini API key for fallback client initialization.
            ai_client: Optional pre-configured Gemini client for DI.
        """
        self.config = StrategistConfig.from_dict(config_dict)
        self.client = ai_client or genai.Client(api_key=api_key)

    def draft(self, observation: Dict[str, Any]) -> Dict[str, Any]:
        """
        Phase Draft: Generates an initial strategic draft based on market topography.
        """
        prompt = self._build_prompt(observation, filter_logic="DRAFTING")
        logger.info("Strategist: Drafting initial strategic plan...")
        return self._execute_ai_cycle(prompt, temperature=self.config.temperature_draft)

    def synthesize(self, observation: Dict[str, Any], draft_plan: Dict[str, Any], critique: Dict[str, Any]) -> Dict[str, Any]:
        """
        Phase Synthesize: Crystalizes the draft and adversarial critique into a final decision.
        """
        prompt = self._build_prompt(
            observation, 
            filter_logic="SYNTHESIS", 
            draft_plan=draft_plan, 
            critic_feedback=critique
        )
        logger.info("Strategist: Synthesizing final strategy...")
        return self._execute_ai_cycle(prompt, temperature=self.config.temperature_synthesis)

    def _build_prompt(self, observation: Dict[str, Any], filter_logic: str, **extra_context) -> str:
        """Helper to load and format the prompt template with logic filters."""
        template = read_prompt_template(self.config.role_prompt_path)
        prompt_with_logic = apply_prompt_logic_filters(template, [filter_logic])
        
        # Prepare context
        context = {
            "observation_json": json.dumps(observation, indent=2, ensure_ascii=False),
            "draft_plan": json.dumps(extra_context.get("draft_plan"), indent=2, ensure_ascii=False),
            "critic_feedback": json.dumps(extra_context.get("critic_feedback"), indent=2, ensure_ascii=False)
        }
        
        try:
            return safe_format(prompt_with_logic, **context)
        except KeyError as e:
            logger.warning(f"Strategist: Missing prompt placeholder during {filter_logic}: {e}")
            return prompt_with_logic # Fallback if formatting fails due to missing keys (e.g. in draft phase)

    def _execute_ai_cycle(self, prompt: str, temperature: float) -> Dict[str, Any]:
        """Core AI execution logic for both drafting and synthesis."""
        try:
            response = self.client.models.generate_content(
                model=self.config.model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=temperature,
                    response_mime_type="application/json"
                )
            )
            return json.loads(response.text)
        except Exception as e:
            logger.error(f"Strategist AI execution failed: {e}", exc_info=True)
            return {"error": "STRATEGIST_EXECUTION_FAILURE", "details": str(e)}
