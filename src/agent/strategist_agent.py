import os
import re
import logging
import json
from typing import Dict, Any
from datetime import datetime, timezone
from google import genai
from google.genai import types
from src.utils.agent_utils import read_prompt_template, apply_prompt_logic_filters

logger = logging.getLogger(__name__)

class StrategistAgent:
    """
    Agent B: The Strategist.
    Responsible for drafting initial strategic plans based on market observations 
    and synthesizing those drafts with adversarial critiques into a final, 
    actionable trading decision.
    """
    def __init__(self, config: Dict[str, Any], api_key: str):
        self.config = config
        self. strat_config = config.get('strategist', {})
        self.model_name = self.strat_config.get('model')
        self.prompt_path = self.strat_config.get('role_definition_prompt')
        self.temp_draft = self.strat_config.get('temperature_draft')
        self.temp_synthesis = self.strat_config.get('temperature_synthesis')
        
        if not api_key:
            raise ValueError("Strategist: api_key is required for initialization")
        
        self.client = genai.Client(api_key=api_key)

    def draft(self, observation: Dict[str, Any]) -> Dict[str, Any]:
        """
        Generates an initial strategic draft (Pass 1).
        
        Args:
            observation (Dict): The market observation context.
            
        Returns:
            Dict: The initial trading plan draft.
        """
        template = read_prompt_template(self.prompt_path)
        prompt_with_context = apply_prompt_logic_filters(template, ["DRAFTING"])
        
        prompt = prompt_with_context.format(
            observation_json=json.dumps(observation, indent=2)
        )
        
        logger.info(f"Strategist: Generating initial draft...")
        response = self.client.models.generate_content(
            model=self.model_name,
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=self.temp_draft,
                response_mime_type="application/json"
            )
        )
        
        try:
            return json.loads(response.text)
        except Exception as e:
            logger.error(f"Strategist: Failed to parse draft JSON: {e}")
            return {"error": "JSON_PARSE_FAILURE", "raw_response": response.text}

    def synthesize(self, observation: Dict[str, Any], draft_plan: Dict[str, Any], critique: Dict[str, Any]) -> Dict[str, Any]:
        """
        Synthesizes the draft and critique into a final decision (Pass 3).
        
        Args:
            observation (Dict): The market observation context.
            draft_plan (Dict): The initial strategic draft.
            critique (Dict): The adversarial audit results.
            
        Returns:
            Dict: The final crystallized trading strategy.
        """
        template = read_prompt_template(self.prompt_path)
        prompt_with_context = apply_prompt_logic_filters(template, ["SYNTHESIS"])
        
        prompt = prompt_with_context.format(
            observation_json=json.dumps(observation, indent=2),
            draft_plan=json.dumps(draft_plan, indent=2),
            critic_feedback=json.dumps(critique, indent=2)
        )
        
        logger.info(f"Strategist: Synthesizing final decision...")
        response = self.client.models.generate_content(
            model=self.model_name,
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=self.temp_synthesis,
                response_mime_type="application/json"
            )
        )

        try:
            return json.loads(response.text)
        except Exception as e:
            logger.error(f"Strategist: Failed to parse synthesis JSON: {e}")
            return {"error": "JSON_PARSE_FAILURE", "raw_response": response.text}
