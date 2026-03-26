import os
import json
import logging
from dataclasses import dataclass
from typing import Dict, Any, List, Optional
from google import genai
from google.genai import types
from src.utils.agent_utils import read_prompt_template, safe_format
from src.utils.path_utils import resolve_project_root
from src.utils.json_utils import extract_json_from_text

logger = logging.getLogger(__name__)

@dataclass
class CoachConfig:
    """Dataclass for type-safe Coach configuration."""
    model: str
    temperature: float
    role_prompt_path: str
    strategist_prompt_path: str
    critic_prompt_path: str

    @classmethod
    def from_dict(cls, full_config: Dict[str, Any]) -> "CoachConfig":
        """Factory method to extract coach config from the global config dict."""
        coach_cfg = full_config['coach']
        strat_cfg = full_config['strategist']
        crit_cfg = full_config['critic']
        
        project_root = resolve_project_root()
        
        return cls(
            model=str(coach_cfg['model']),
            temperature=float(coach_cfg['temperature']),
            role_prompt_path=os.path.join(project_root, coach_cfg['role_definition_prompt']),
            strategist_prompt_path=os.path.join(project_root, strat_cfg['role_definition_prompt']),
            critic_prompt_path=os.path.join(project_root, crit_cfg['role_definition_prompt'])
        )

class CoachAgent:
    """
    Agent C: The Strategic Coach.
    Analyzes batches of historical forensic audits to identify systemic patterns.
    Suggests high-level architectural and logic refinements.
    """
    def __init__(self, config_dict: Dict[str, Any], api_key: str, ai_client: Optional[genai.Client] = None):
        """
        Initializes the Coach with configuration and injected dependencies.
        """
        self.config = CoachConfig.from_dict(config_dict)
        self.raw_config = config_dict
        self.client = ai_client or genai.Client(api_key=api_key)

    def analyze(self, review_history: List[Dict[str, Any]]) -> str:
        """
        Executes a coaching session by analyzing a batch of historical reviews.
        """
        logger.info(f"Coach: Starting systemic analysis of {len(review_history)} forensic reports...")
        prompt = self._build_prompt(review_history)
        return self._execute_ai_cycle(prompt)

    def _build_prompt(self, review_history: List[Dict[str, Any]]) -> str:
        """Constructs the analysis prompt by injecting context and history."""
        template = read_prompt_template(self.config.role_prompt_path)
        
        # Load linked agent prompts for context
        strategist_prompt = read_prompt_template(self.config.strategist_prompt_path)
        critic_prompt = read_prompt_template(self.config.critic_prompt_path)
        
        context = {
            "batch_data": json.dumps(review_history, indent=2, ensure_ascii=False),
            "current_config": json.dumps(self.raw_config, indent=2, ensure_ascii=False),
            "strategist_prompt": strategist_prompt,
            "critic_prompt": critic_prompt
        }
        
        return safe_format(template, **context)

    def _execute_ai_cycle(self, prompt: str) -> str:
        """Handles the low-level communication with the Gemini API."""
        try:
            logger.info(f"Invoking Coach Agent ({self.config.model})...")
            
            response = self.client.models.generate_content(
                model=self.config.model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    temperature=self.config.temperature
                )
            )
            parsed = extract_json_from_text(response.text)
            if parsed is None:
                logger.error(f"Coach: Failed to parse JSON from response: {response.text}")
                return json.dumps({"error": "JSON_PARSE_FAILURE", "raw_response": response.text})
            return response.text # Coach expects raw string for patch processing, but we validate it's JSON first
            
        except Exception as e:
            logger.error(f"Coach AI execution failed: {e}", exc_info=True)
            return json.dumps({"error": "COACH_EXECUTION_FAILURE", "details": str(e)})
