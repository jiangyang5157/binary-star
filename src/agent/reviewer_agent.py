import os
import json
import logging
from typing import Dict, Any, List, Optional
from google import genai
from google.genai import types

logger = logging.getLogger(__name__)

class ReviewerAgent:
    """
    Agent B: The Reviewer / Optimizer.
    Evaluates past predictions made by Agent A against actual market outcomes.
    Specifically audits adherence to the Predictor's logic and rules.
    """
    def __init__(self, model_name: str, prompts_dir: str, 
                 prompt_filename: str, temperature: float):
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
            with open(prompt_path, 'r', encoding='utf-8') as f:
                return f.read()
        except Exception as e:
            logger.error(f"Failed to load prompt template: {e}")
            return ""

    def review(self, historical_prediction: Dict[str, Any], actual_outcome: Dict[str, Any], config: Dict[str, Any], 
               chart_image_paths: Optional[List[str]] = None, base_prompt: str = "") -> str:
        """
        Executes a multimodal Gemini API call to review Agent A's performance.
        Includes base_prompt to allow auditing of rule adherence.
        """
        if not self.client:
            return json.dumps({"error": "GenAI API Client is not initialized."})

        prompt_template = self.load_prompt_template()
        if not prompt_template:
            return json.dumps({"error": "Agent B prompt template missing."})

        try:
            formatted_prompt = prompt_template.format(
                historical_prediction=json.dumps(historical_prediction, indent=2, ensure_ascii=False),
                actual_outcome=json.dumps(actual_outcome, indent=2, ensure_ascii=False),
                current_config=json.dumps(config, indent=2, ensure_ascii=False),
                prediction_horizon_days=config['prediction']['prediction_horizon_days'],
                macro_interval=config['prediction']['macro_timeframe']['interval'],
                micro_interval=config['prediction']['micro_timeframe']['interval'],
                base_prompt=base_prompt
            )
        except Exception as e:
            logger.error(f"Failed to format Reviewer prompt: {e}")
            return json.dumps({"error": f"Formatting error: {str(e)}"})

        contents = []
        
        # Upload all provided charts
        if chart_image_paths:
            for path in chart_image_paths:
                if os.path.exists(path):
                    try:
                        logger.info(f"Uploading historical chart image to Gemini API: {path}")
                        uploaded_file = self.client.files.upload(file=path)
                        contents.append(uploaded_file)
                    except Exception as e:
                        logger.warning(f"File upload failed for Reviewer at {path}: {e}")
        
        # Append text prompt
        contents.append(formatted_prompt)
        
        try:
            logger.info(f"Invoking Reviewer Agent Model ({self.model_name})...")
            
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
            logger.error(f"Failed to get response from GenAI API: {e}")
            return json.dumps({"error": str(e)})
