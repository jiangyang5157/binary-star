import os
import logging
import json
from typing import Dict, Any
from google import genai
from google.genai import types
from src.utils.agent_utils import load_prompt

logger = logging.getLogger(__name__)

class CriticAgent:
    """
    Agent C: The Critic.
    Responsible for performing adversarial audits on strategic drafts, identifying 
    psychological biases, logical gaps, and hidden structural risks.
    """
    def __init__(self, config: Dict[str, Any], api_key: str):
        self.config = config
        self.critic_config = config.get('critic', {})
        self.model_name = self.critic_config['model']
        self.prompt_path = self.critic_config['prompt_path']
        self.temperature = self.critic_config['temperature']
        
        if not api_key:
            raise ValueError("Critic: api_key is required for initialization")
        
        self.client = genai.Client(api_key=api_key)

    def audit(self, observation: Dict[str, Any], draft_plan: Dict[str, Any]) -> Dict[str, Any]:
        """
        Performs an adversarial audit on a draft trading plan.
        
        Args:
            observation (Dict): The market observation context.
            draft_plan (Dict): The initial strategic draft from the Strategist.
            
        Returns:
            Dict: The audit findings including skepticism score and veto status.
        """
        prompt_with_context = load_prompt(self.prompt_path)
        
        prompt = prompt_with_context.format(
            observation_json=json.dumps(observation, indent=2),
            draft_plan=json.dumps(draft_plan, indent=2)
        )
        
        logger.info(f"Critic: Auditing strategist draft...")
        response = self.client.models.generate_content(
            model=self.model_name,
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=self.temperature,
                response_mime_type="application/json"
            )
        )
        try:
            return json.loads(response.text)
        except Exception as e:
            logger.error(f"Critic: Failed to parse audit JSON: {e}")
            return {"error": "JSON_PARSE_FAILURE", "raw_response": response.text}
