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
    Performs adversarial audit of a strategic draft.
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
        Audit the draft plan against the observations.
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
        return json.loads(response.text)
