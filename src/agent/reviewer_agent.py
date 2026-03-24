import os
import json
import logging
from typing import Dict, Any, List, Optional
from src.utils.agent_utils import load_prompt
from google import genai
from google.genai import types

logger = logging.getLogger(__name__)

class ReviewerAgent:
    """
    Agent B: The Reviewer / Optimizer.
    Evaluates past predictions made by Agent A against actual market outcomes.
    Specifically audits adherence to the Predictor's logic and rules.
    """
    def __init__(self, config: Dict[str, Any], api_key: str):
        self.config = config
        review_config = config.get('review', {})
        self.model_name = review_config.get('model')
        self.temperature = review_config.get('temperature', 1.0)
        self.prompt_path = review_config.get('prompt_path')
        self.strat_prompt_path = config.get('strategist', {}).get('prompt_path')
        self.critic_prompt_path = config.get('critic', {}).get('prompt_path')
        
        if not api_key:
            raise ValueError("Reviewer: api_key is required for initialization")
                    
        self.client = genai.Client(api_key=api_key)

    def review(self, historical_strategy: Dict[str, Any], 
               observation: Dict[str, Any], 
               current_observation: Optional[Dict[str, Any]]) -> str:
               chart_image_paths: List[str] = None) -> str:
        """
        Executes a multimodal post-mortem audit of Agent A's performance.
        Includes a self-audit against the Predictor's logic handbook.
        """
        try:
            prompt_with_context = load_prompt(self.prompt_path)
            strategist_prompt = load_prompt(self.strat_prompt_path)
            critic_prompt = load_prompt(self.critic_prompt_path)

            historical_observation = historical_strategy.get("observation")
            draft_plan = historical_strategy.get("draft")
            critique_against_draft_plan = historical_strategy.get("critique")
            final_decision = historical_strategy.get("final_decision")

            prompt = prompt_with_context.format(
                historical_observation=json.dumps(historical_observation, indent=2, ensure_ascii=False),
                current_observation=json.dumps(current_observation, indent=2, ensure_ascii=False),
                current_config=json.dumps(self.config, indent=2, ensure_ascii=False),
                draft_plan=draft_plan,
                critique_against_draft_plan=critique_against_draft_plan,
                final_decision=final_decision,
                strategist_prompt=strategist_prompt,
                critic_prompt=critic_prompt,
                macro_interval=self.config['observer']['macro_timeframe']['interval'],
                micro_interval=self.config['observer']['micro_timeframe']['interval'],
            )
        except Exception as e:
            logger.error(f"Reviewer formatting error: {e}")
            return json.dumps({"error": str(e)})

        contents = []
        contents.append(prompt)
        
        try:
            from google.genai import types
            logger.info(f"Invoking Reviewer Agent ({self.model_name})...")
            response = self.client.models.generate_content(
                model=self.model_name,
                contents=contents,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    temperature=self.temperature
                )
            )
            return response.text
        except Exception as e:
            logger.error(f"Reviewer API call failed: {e}")
            return json.dumps({"error": str(e)})
