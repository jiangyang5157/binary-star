import os
import copy
import logging
from typing import Dict, Any
from datetime import datetime, timezone
from google import genai
from google.genai import types

logger = logging.getLogger(__name__)

class TraderAgent:
    """
    Agent A: The Trader / Analyst.
    Uses the new google-genai SDK to analyze both text data (Market context) and image data (Volume Profile charts).
    """
    def __init__(self, model_name: str, prompts_dir: str = "src/agent/prompts", 
                 temp_pass1: float = 1.0, temp_pass2: float = 1.0, temp_pass3: float = 0.7):
        self.model_name = model_name
        self.prompts_dir = prompts_dir
        self.temp_pass1 = temp_pass1
        self.temp_pass2 = temp_pass2
        self.temp_pass3 = temp_pass3
        
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
        current_time = datetime.now(timezone.utc).isoformat() + "Z"
        
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
            
            logger.info(f"Invoking Gemini Model ({self.model_name}) with Multi-Pass Reasoning...")
            
            # --- PASS 1: Initial Prediction ---
            initial_response = self.client.models.generate_content(
                model=self.model_name,
                contents=contents,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    temperature=self.temp_pass1
                )
            )
            initial_prediction = initial_response.text or "No initial prediction generated."
            logger.info("Pass 1 (Initial Prediction) complete.")

            # --- PASS 2: Red Team Critique (The 'Premortem') ---
            # We ask the model to assume the trade failed and find out why.
            review_window = context_data.get("review_window_days", 7)
            critique_prompt = f"""
            CRITICAL EVALUATION (RED TEAM):
            Assume you just executed the following prediction:
            {initial_prediction}

            Now, imagine that {review_window} DAYS have passed and this trade resulted in a MASSIVE LOSS / STOP-OUT.
            Look at the Macro and Micro charts again. What did you MISS? 
            Specifically search for:
            1. **Liquidity Traps**: Did you ignore clear exhaustion wicks or high-volume rejections at POC/VAH/VAL? 
            2. **Visual AR Cues**: Are there heavy **Liquidation Zones** (translucent bands) directly against your trade direction?
            3. **Breakout Failure**: Was the 'breakout' you entered actually a low-volume 'fakeout' with declining Open Interest (OI)?
            4. **Sentiment Divergence**: Is the Global L/S Ratio extremely high (>2.0) while price is grinding up (suggesting retail is long and being trapped)?

            Provide a HARSH technical critique. Do NOT be defensive.
            """
            
            # We reuse the same images (contents[:-1]) but add the new critique prompt
            critique_contents = copy.deepcopy(contents[:-1])
            critique_contents.append(critique_prompt)
            
            critique_response = self.client.models.generate_content(
                model=self.model_name,
                contents=critique_contents,
                config=types.GenerateContentConfig(
                    temperature=self.temp_pass2
                )
            )
            critique_text = critique_response.text or "No critique generated."
            logger.info("Pass 2 (Red Team Critique) complete.")

            # --- PASS 3: Final Refined Decision ---
            final_prompt = f"""
            FINAL RESOLUTION:
            You have your Initial Plan and a harsh Red Team Critique.
            Initial Plan: {initial_prediction}
            Critique: {critique_text}

            Re-evaluate the data. If the critique revealed a fatal flaw or high risk of a trap, switch to HOLD or reverse bias. 
            If the initial plan is still robust, refine the entry/exit points for better R:R.

            IMPORTANT: You MUST output the final result in the EXACT JSON format below, including the Mandarin translation field:
            {{
              "timestamp": "{current_time}",
              "action": "BUY/SELL/HOLD",
              "confidence": 0-100,
              "reasoning": "...",
              "reasoning_zh": "中文解析内容..."
            }}
            """
            final_contents = copy.deepcopy(contents[:-1])
            final_contents.append(final_prompt)
            
            final_response = self.client.models.generate_content(
                model=self.model_name,
                contents=final_contents,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    temperature=self.temp_pass3
                )
            )
            
            # We return the final JSON
            return final_response.text
            
        except Exception as e:
            logger.error(f"Failed to get response from GenAI API: {e}")
            return f'{{"error": "{str(e)}"}}'
