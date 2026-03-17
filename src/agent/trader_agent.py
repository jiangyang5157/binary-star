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
        
        # Initialize the GenAI client.
        try:
            api_key = os.environ.get("GEMINI_API_KEY")
            self.client = genai.Client(api_key=api_key)
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

    def analyze(self, symbol: str, chart_image_paths: list[str], context_data: Dict[str, Any]) -> str:
        """
        Executes the multimodal Gemini API call to determine the trading action.
        Supports multiple images (e.g., Macro + Micro charts).
        """
        if not self.client:
            return '{"error": "GenAI API Client is not initialized. Is GEMINI_API_KEY set?"}'

        prompt_template = self.load_prompt_template()
        if not prompt_template:
            return '{"error": "Agent prompt template missing."}'

        # Prepare context data
        context_summary = copy.deepcopy(context_data)
        
        # Format the specific text prompt with our dynamic data
        current_time = datetime.utcnow().isoformat() + "Z"
        
        # Prepare all variables for formatting, avoiding duplicate keywords
        format_vars = copy.deepcopy(context_summary)
        format_vars.update({
            "symbol": symbol,
            "current_time": current_time,
            "context_data": context_summary # For legacy support in prompt if used
        })
        
        try:
            formatted_prompt = prompt_template.format(**format_vars)
        except KeyError as e:
            logger.error(f"Missing key in prompt template: {e}")
            formatted_prompt = prompt_template
        except Exception as e:
            logger.error(f"Error formatting prompt: {e}")
            formatted_prompt = prompt_template

        try:
            # Multi-modal Input
            contents = []
            
            # Upload all charts
            for path in chart_image_paths:
                if not os.path.exists(path):
                    logger.warning(f"Chart image not found: {path}. Skipping.")
                    continue
                
                try:
                    logger.info(f"Uploading chart image to Gemini API: {path}")
                    uploaded_file = self.client.files.upload(file=path)
                    contents.append(uploaded_file)
                except Exception as e:
                    logger.warning(f"File upload failed for {path}: {e}")
                    # Minimal fallback
                    contents.append({"mime_type": "image/png", "file_uri": path})
            
            # Append text prompt at the end
            contents.append(formatted_prompt)
            
            logger.info(f"Invoking Gemini Model ({self.model_name})...")
            
            # response_mime_type="application/json" forces the model to return a valid JSON block,
            # which is much easier for our code to parse than free-form text.
            response = self.client.models.generate_content(
                model=self.model_name,
                contents=contents,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    temperature=0.2 # Lower temperature = more consistent, deterministic reasoning.
                )
            )
            
            return response.text
            
        except Exception as e:
            logger.error(f"Failed to get response from GenAI API: {e}")
            return f'{{"error": "{str(e)}"}}'
