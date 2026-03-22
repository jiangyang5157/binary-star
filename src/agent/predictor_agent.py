import os
import re
import copy
import logging
from typing import Dict, Any
from datetime import datetime, timezone
from google import genai
from google.genai import types

logger = logging.getLogger(__name__)

class PredictorAgent:
    """
    Agent A: The Predictor / Analyst.
    Uses the multimodal Gemini API to analyze market context and charts.
    """
    def __init__(self, model_name: str, prompts_dir: str, 
                 prompt_filename: str,
                 temp_initial: float, temp_critique: float, temp_final: float):
        self.model_name = model_name
        self.prompts_dir = prompts_dir
        self.prompt_filename = prompt_filename
        self.temp_initial = temp_initial
        self.temp_critique = temp_critique
        self.temp_final = temp_final
        
        # Initialize the GenAI client.
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

    def extract_section(self, template: str, section_name: str) -> str:
        """
        Extracts a specific section from the prompt template.
        Sections are defined by ### [SECTION_NAME] headers.
        """
        pattern = rf"\[\[\[{section_name}\]\]\](.*?)(?=\[\[\[/{section_name}\]\]\]|\Z)"
        match = re.search(pattern, template, re.DOTALL)
        if match:
            return match.group(1).strip()
        return ""

    def get_common_context(self, template: str) -> str:
        """Extracts the common principles and market context parts of the prompt."""
        if "[[[ROLE_SPECIFIC_INSTRUCTIONS]]]" in template:
            return template.split("[[[ROLE_SPECIFIC_INSTRUCTIONS]]]")[0].strip()
        return template

    def get_footer(self, template: str) -> str:
        """Extracts the final output protocol and format enforcement footer."""
        if "[[[FINAL_OUTPUT_PROTOCOL]]]" in template:
            return template.split("[[[FINAL_OUTPUT_PROTOCOL]]]")[-1].strip()
        return ""

    def analyze(self, symbol: str, chart_image_paths: list[str], context_data: Dict[str, Any], current_position: str = "None") -> str:
        """
        Executes the multimodal Gemini API call to determine the trading action.
        """
        if not self.client:
            return '{"error": "GenAI API Client is not initialized. Is GEMINI_API_KEY set?"}'

        # 1. Load Master Prompt Template
        master_template = self.load_prompt_template()
        if not master_template:
            return '{"error": "Agent prompt template missing."}'

        # 2. Extract Components
        common_context = self.get_common_context(master_template)
        footer = self.get_footer(master_template)
        
        # 3. Global Variables
        dt_now = datetime.now(timezone.utc)
        current_time = dt_now.isoformat().replace("+00:00", "Z")
        format_vars = copy.deepcopy(context_data)
        format_vars.update({
            "symbol": symbol,
            "current_time": current_time,
            "current_position": current_position,
            "prediction_horizon": context_data["prediction_horizon_days"]
        })

        # Multi-modal Input preparation (upload charts)
        contents_base = []
        for path in chart_image_paths:
            if os.path.exists(path):
                try:
                    uploaded_file = self.client.files.upload(file=path)
                    contents_base.append(uploaded_file)
                except Exception as e:
                    logger.warning(f"File upload failed for {path}: {e}")

        try:
            # --- PASS 1: Initial Prediction ---
            pass1_instr = self.extract_section(master_template, "PASS_1_INITIAL_ANALYSIS")
            pass1_prompt = f"{common_context}\n\n{pass1_instr}\n\n{footer}".format(**format_vars)
            
            pass1_contents = copy.deepcopy(contents_base)
            pass1_contents.append(pass1_prompt)
            
            logger.info("Pass 1 (Initial Prediction) starting...")
            initial_response = self.client.models.generate_content(
                model=self.model_name, contents=pass1_contents,
                config=types.GenerateContentConfig(response_mime_type="application/json", temperature=self.temp_initial)
            )
            initial_prediction = initial_response.text or "No initial prediction generated."
            logger.info("Pass 1 complete.")

            # --- PASS 2: Red Team Critique ---
            pass2_instr = self.extract_section(master_template, "PASS_2_RED_TEAM_CRITIQUE")
            format_vars["initial_prediction"] = initial_prediction
            pass2_prompt = f"{common_context}\n\n{pass2_instr}".format(**format_vars)
            
            pass2_contents = copy.deepcopy(contents_base)
            pass2_contents.append(pass2_prompt)
            
            logger.info("Pass 2 (Red Team Critique) starting...")
            critique_response = self.client.models.generate_content(
                model=self.model_name, contents=pass2_contents,
                config=types.GenerateContentConfig(temperature=self.temp_critique)
            )
            critique_text = critique_response.text or "No critique generated."
            logger.info("Pass 2 complete.")

            # --- PASS 3: Final Resolution ---
            pass3_instr = self.extract_section(master_template, "PASS_3_FINAL_RESOLUTION")
            format_vars["critique_text"] = critique_text
            pass3_prompt = f"{common_context}\n\n{pass3_instr}\n\n{footer}".format(**format_vars)
            
            pass3_contents = copy.deepcopy(contents_base)
            pass3_contents.append(pass3_prompt)
            
            logger.info("Pass 3 (Final Resolution) starting...")
            final_response = self.client.models.generate_content(
                model=self.model_name, contents=pass3_contents,
                config=types.GenerateContentConfig(response_mime_type="application/json", temperature=self.temp_final)
            )
            return final_response.text
            
        except Exception as e:
            logger.error(f"Multi-pass execution failed: {e}")
            return f'{{"error": "{str(e)}"}}'
