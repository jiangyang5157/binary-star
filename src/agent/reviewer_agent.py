import os
import json
import logging
from typing import Dict, Any
from google import genai
from google.genai import types

logger = logging.getLogger(__name__)

class ReviewerAgent:
    """
    Agent B: The Reviewer / Optimizer.
    Evaluates past predictions made by Agent A against actual market outcomes.
    Suggests config parameter tweaks and prompt updates.
    """
    def __init__(self, model_name: str = "gemini-2.5-flash", prompts_dir: str = "src/agent/prompts"):
        self.model_name = model_name
        self.prompts_dir = prompts_dir
        try:
            api_key = os.environ.get("GEMINI_API_KEY")
            self.client = genai.Client(api_key=api_key)
        except Exception as e:
            logger.error(f"Failed to initialize GenAI client: {e}")
            self.client = None

    def load_prompt_template(self) -> str:
        prompt_path = os.path.join(self.prompts_dir, "prompt_reviewer.txt")
        try:
            with open(prompt_path, 'r', encoding='utf-8') as f:
                return f.read()
        except Exception as e:
            logger.error(f"Failed to load prompt template: {e}")
            return ""

    def review(self, historical_prediction: Dict[str, Any], actual_outcome: Dict[str, Any], current_config: Dict[str, Any]) -> str:
        """
        Executes a text-only Gemini API call to review Agent A's performance.
        """
        if not self.client:
            return '{"error": "GenAI API Client is not initialized."}'

        prompt_template = self.load_prompt_template()
        if not prompt_template:
            return '{"error": "Agent B prompt template missing."}'

        formatted_prompt = prompt_template.format(
            historical_prediction=json.dumps(historical_prediction, indent=2),
            actual_outcome=json.dumps(actual_outcome, indent=2),
            current_config=json.dumps(current_config, indent=2),
            target_duration=14  # Can be parameterized based on user preference
        )

        try:
            logger.info(f"Invoking Reviewer Agent Model ({self.model_name})...")
            
            # Agent B evaluates Agent A's past prediction vs Actual market outcome.
            # Its goal is to find 'Logical Flaws' and generate 'Config Patches' or Prompt updates.
            response = self.client.models.generate_content(
                model=self.model_name,
                contents=formatted_prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    temperature=0.3 # Slightly higher temperature to allow for more 'insightful' improvement tips.
                )
            )
            
            return response.text
            
        except Exception as e:
            logger.error(f"Failed to get response from GenAI API: {e}")
            return f'{{"error": "{str(e)}"}}'
