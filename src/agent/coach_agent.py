import os
import json
import logging
from typing import Dict, Any, List
from google import genai
from google.genai import types

logger = logging.getLogger(__name__)

class CoachAgent:
    """
    Agent C: The Coach / Strategist.
    Reviews batches of historical review reports to identify systemic patterns.
    Suggests high-level prompt patches and configuration adjustments.
    """
    def __init__(self, model_name: str, prompts_dir: str = "src/agent/prompts", 
                 prompt_filename: str = "prompt_coach.txt", temperature: float = 1.0):
        self.model_name = model_name
        self.prompts_dir = prompts_dir
        self.prompt_filename = prompt_filename
        self.temperature = temperature
        try:
            api_key = os.environ.get("GEMINI_API_KEY")
            self.client = genai.Client(api_key=api_key)
        except Exception as e:
            logger.error(f"Failed to initialize GenAI client: {e}")
            self.client = None

    def load_prompt_template(self) -> str:
        prompt_path = os.path.join(self.prompts_dir, self.prompt_filename)
        try:
            if not os.path.exists(prompt_path):
                logger.error(f"Coach prompt template missing at {prompt_path}")
                return ""
            with open(prompt_path, 'r', encoding='utf-8') as f:
                return f.read()
        except Exception as e:
            logger.error(f"Failed to load coach prompt template: {e}")
            return ""

    def coaching_session(self, review_reports: List[Dict[str, Any]], current_config: Dict[str, Any], base_prompt: str) -> str:
        """
        Executes a Gemini API call to perform a batch review (coaching session).
        """
        if not self.client:
            return '{"error": "GenAI API Client is not initialized."}'

        prompt_template = self.load_prompt_template()
        if not prompt_template:
            return '{"error": "Agent C (Coach) prompt template missing."}'

        # Format the batch data for the prompt
        batch_summary = []
        for i, report in enumerate(review_reports):
            summary = {
                "id": i + 1,
                "prediction": report.get('prediction', {}).get('content', {}),
                "actual_market_outcome": report.get('actual_market_outcome', {}),
                "analysis": report.get('analysis', {})
            }
            batch_summary.append(summary)

        try:
            formatted_prompt = prompt_template.format(
                batch_data=json.dumps(batch_summary, indent=2, ensure_ascii=False),
                current_config=json.dumps(current_config, indent=2, ensure_ascii=False),
                batch_count=len(batch_summary),
                base_prompt=base_prompt
            )
        except Exception as e:
            logger.error(f"Failed to format Coach prompt: {e}")
            return json.dumps({"error": f"Formatting error: {str(e)}"})

        try:
            logger.info(f"Invoking Coach Agent Model ({self.model_name}) for {len(batch_summary)} reviews...")
            
            response = self.client.models.generate_content(
                model=self.model_name,
                contents=formatted_prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    temperature=self.temperature
                )
            )
            
            return response.text
            
        except Exception as e:
            logger.error(f"Failed to get response from Coach GenAI API: {e}")
            return f'{{"error": "{str(e)}"}}'
