from dataclasses import dataclass
import os
import logging
import json
from typing import Dict, Any, Optional
from google import genai
from google.genai import types
from src.utils.agent_utils import read_prompt_template, safe_format
from src.utils.path_utils import resolve_project_root

logger = logging.getLogger(__name__)

@dataclass(frozen=True)
class CriticConfig:
    """Encapsulates configuration for the CriticAgent."""
    model: str
    role_prompt_path: str
    temperature: float

    @classmethod
    def from_dict(cls, full_config: Dict[str, Any]) -> "CriticConfig":
        """Factory method to extract critic config from the global config dict."""
        critic = full_config['critic']
        return cls(
            model=str(critic['model']),
            role_prompt_path=os.path.join(resolve_project_root(), critic['role_definition_prompt']),
            temperature=float(critic['temperature'])
        )

class CriticAgent:
    """
    Agent C: The Critic (Adversarial Auditor).
    Responsible for performing adversarial audits on strategic drafts, identifying 
    psychological biases, logical gaps, and hidden structural risks.
    """
    def __init__(self, config_dict: Dict[str, Any], api_key: str, ai_client: Optional[genai.Client] = None):
        """
        Initializes the Critic with a configuration and optional AI client injection.
        
        Args:
            config_dict: The full application configuration dictionary.
            api_key: Gemini API key for fallback client initialization.
            ai_client: Optional pre-configured Gemini client for DI.
        """
        self.config = CriticConfig.from_dict(config_dict)
        self.client = ai_client or genai.Client(api_key=api_key)

    def audit(self, observation: Dict[str, Any], draft_plan: Dict[str, Any]) -> Dict[str, Any]:
        """
        Performs an adversarial audit on a draft trading plan.
        
        Args:
            observation: The market observation context (topography).
            draft_plan: The initial strategic draft from the Strategist.
            
        Returns:
            Dict: The audit findings (skepticism_score, veto_status, etc.).
        """
        template = read_prompt_template(self.config.role_prompt_path)
        
        prompt = safe_format(
            template,
            observation_json=json.dumps(observation, indent=2, ensure_ascii=False),
            draft_plan=json.dumps(draft_plan, indent=2, ensure_ascii=False)
        )
        
        logger.info("Critic: Performing adversarial audit...")
        return self._execute_ai_cycle(prompt)

    def _execute_ai_cycle(self, prompt: str) -> Dict[str, Any]:
        """Core AI execution logic for the audit phase."""
        try:
            response = self.client.models.generate_content(
                model=self.config.model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=self.config.temperature,
                    response_mime_type="application/json"
                )
            )
            return json.loads(response.text)
        except Exception as e:
            logger.error(f"Critic AI execution failed: {e}", exc_info=True)
            return {"error": "CRITIC_EXECUTION_FAILURE", "details": str(e)}
