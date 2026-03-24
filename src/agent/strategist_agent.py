import os
import re
import logging
import json
from typing import Dict, Any
from datetime import datetime, timezone
from google import genai
from google.genai import types
from src.utils.agent_utils import load_prompt, partition_prompt

logger = logging.getLogger(__name__)

class StrategistAgent:
    """
    Agent B: The Strategist.
    Consumes Observer JSON and produces a structured trading strategy.
    Implements Pass 1 (Drafting) and Pass 3 (Synthesis).
    """
    def __init__(self, config: Dict[str, Any], api_key: str):
        self.config = config
        self.strat_config = config.get('strategist', {})
        self.model_name = self.strat_config.get('model')
        self.prompt_path = self.strat_config.get('prompt_path')
        self.temp_draft = self.strat_config.get('temperature_draft')
        self.temp_synthesis = self.strat_config.get('temperature_synthesis')
        
        if not api_key:
            raise ValueError("Strategist: api_key is required for initialization")
        
        self.client = genai.Client(api_key=api_key)

    def draft(self, observation: Dict[str, Any]) -> Dict[str, Any]:
        """
        Pass 1: Generate initial strategic draft based on observations.
        """
        template = load_prompt(self.prompt_path)
        prompt_with_context = partition_prompt(template, ["DRAFTING"])
        
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
            logger.error(f"Failed to parse strategist draft: {e}")
            return {"error": "JSON parsing failed", "raw_response": response.text}

    def synthesize(self, observation: Dict[str, Any], draft_plan: Dict[str, Any], critique: Dict[str, Any]) -> Dict[str, Any]:
        """
        Pass 3: Synthesize draft and critique into final strategy JSON.
        """
        template = load_prompt(self.prompt_path)
        prompt_with_context = partition_prompt(template, ["SYNTHESIS"])
        
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
            logger.error(f"Failed to parse strategist synthesis: {e}")
            return {"error": "JSON parsing failed", "raw_response": response.text}
