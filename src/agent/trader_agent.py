import os
import copy
import logging
from typing import Dict, Any
from datetime import datetime
from google import genai
from google.genai import types

logger = logging.getLogger(__name__)

class TraderAgent:
    """
    Agent A: The Trader / Analyst.
    Uses the new google-genai SDK to analyze both text data (Market context) and image data (Volume Profile charts).
    """
    def __init__(self, model_name: str = "gemini-2.5-flash", prompts_dir: str = "src/agent/prompts"):
        self.model_name = model_name
        self.prompts_dir = prompts_dir
        
        # Initialize the GenAI client. It will automatically pick up GEMINI_API_KEY from the environment
        try:
            self.client = genai.Client()
        except Exception as e:
            logger.error(f"Failed to initialize GenAI client: {e}")
            self.client = None

    def load_prompt_template(self) -> str:
        prompt_path = os.path.join(self.prompts_dir, "prompt_trader.txt")
        try:
            with open(prompt_path, 'r', encoding='utf-8') as f:
                return f.read()
        except Exception as e:
            logger.error(f"Failed to load prompt template: {e}")
            return ""

    def analyze(self, symbol: str, chart_image_path: str, context_data: Dict[str, Any]) -> str:
        """
        Executes the multimodal Gemini API call to determine the trading action.
        """
        if not self.client:
            return '{"error": "GenAI API Client is not initialized. Is GEMINI_API_KEY set?"}'

        prompt_template = self.load_prompt_template()
        if not prompt_template:
            return '{"error": "Agent prompt template missing."}'

        # Prepare context data
        # We don't want to send the massive order book, just summaries
        context_summary = copy.deepcopy(context_data)
        
        # Format the specific text prompt with our dynamic data
        current_time = datetime.utcnow().isoformat() + "Z"
        formatted_prompt = prompt_template.format(
            symbol=symbol,
            current_time=current_time,
            context_data=context_summary
        )

        try:
            # We must use file API for GenAI since images can be large
            logger.info(f"Uploading chart image to Gemini API: {chart_image_path}")
            
            # Using the direct path approach or upload file
            # If upload fails, fallback to passing image directly if path is valid
            try:
                uploaded_file = self.client.files.upload(file=chart_image_path)
                contents = [uploaded_file, formatted_prompt]
            except Exception as e:
                logger.warning(f"File upload failed, attempting to pass raw path... {e}")
                # Sometimes local SDKs allow direct path if file API upload is blocked
                contents = [
                    {"mime_type": "image/png", "file_uri": chart_image_path}, # Placeholder if direct path fails
                    formatted_prompt
                ]
            
            logger.info(f"Invoking Gemini Model ({self.model_name})...")
            # We strictly request JSON format via response_mime_type
            response = self.client.models.generate_content(
                model=self.model_name,
                contents=contents,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    temperature=0.2 # low temperature for analytical reasoning
                )
            )
            
            return response.text
            
        except Exception as e:
            logger.error(f"Failed to get response from GenAI API: {e}")
            return f'{{"error": "{str(e)}"}}'
