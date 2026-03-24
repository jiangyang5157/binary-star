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
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.model_name = config['agent'].get('reviewer_model', 'gemini-3.1-pro-preview')
        self.temperature = config['agent'].get('review_temperature', 1.0)
        self.prompts_dir = config['paths']['prompts_dir']
        self.prompt_filename = config['paths']['prompt_reviewer_filename']
        self.predictor_prompt_filename = config['paths']['prompt_predictor_filename']
        
        api_key = os.environ.get("GEMINI_API_KEY")
        self.mock_mode = (api_key == "MOCK")
        if not self.mock_mode and api_key:
            from google import genai
            self.client = genai.Client(api_key=api_key)
        else:
            self.client = None

    def review(self, historical_prediction: Dict[str, Any], 
               actual_outcome: Dict[str, Any], 
               chart_image_paths: Optional[List[str]] = None) -> str:
        """
        Executes a multimodal post-mortem audit of Agent A's performance.
        Includes a self-audit against the Predictor's logic handbook.
        """
        if self.mock_mode or not self.client:
            return json.dumps({
                "evaluation_score": 50,
                "tp_sl_result": "NEITHER",
                "prediction_post_mortem": "MOCKED: Market outcome calculated, but AI analysis is disabled."
            }, indent=2, ensure_ascii=False)

        prompt_path = os.path.join(self.prompts_dir, self.prompt_filename)
        predictor_prompt_path = os.path.join(self.prompts_dir, self.predictor_prompt_filename)
        
        try:
            with open(prompt_path, 'r', encoding='utf-8') as f:
                prompt_template = f.read()
            
            base_prompt = ""
            if os.path.exists(predictor_prompt_path):
                with open(predictor_prompt_path, 'r', encoding='utf-8') as f:
                    base_prompt = f.read()

            formatted_prompt = prompt_template.format(
                historical_prediction=json.dumps(historical_prediction, indent=2, ensure_ascii=False),
                actual_outcome=json.dumps(actual_outcome, indent=2, ensure_ascii=False),
                current_config=json.dumps(self.config, indent=2, ensure_ascii=False),
                prediction_horizon_days=self.config['prediction']['prediction_horizon_days'],
                macro_interval=self.config['prediction']['macro_timeframe']['interval'],
                micro_interval=self.config['prediction']['micro_timeframe']['interval'],
                base_prompt=base_prompt
            )
        except Exception as e:
            logger.error(f"Reviewer formatting error: {e}")
            return json.dumps({"error": str(e)})

        contents = []
        if chart_image_paths:
            for path in chart_image_paths:
                if os.path.exists(path):
                    try:
                        logger.info(f"Uploading historical chart {path}")
                        uploaded_file = self.client.files.upload(file=path)
                        contents.append(uploaded_file)
                    except Exception as e:
                        logger.warning(f"File upload failed: {e}")
        
        contents.append(formatted_prompt)
        
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
