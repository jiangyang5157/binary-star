import os
import json
import logging
from typing import Dict, Any, List, Optional, Union
from google import genai
from google.genai import types
import tenacity
import time

from src.utils.agent_utils import read_prompt_template, safe_format
from src.utils.json_utils import extract_json_from_text
from src.utils.logger_utils import setup_logger
from src.utils.path_utils import resolve_project_root
import yaml

logger = setup_logger(__name__)

class BaseAgent:
    """
    Abstract Base Class for all AI-driven agents in the forensic trading pipeline.
    
    This class centralizes common AI interaction patterns, including:
    - Gemini client management and file API access.
    - Standardized prompt template loading and context injection.
    - Robust JSON extraction with 'Strict JSON' enforcement.
    - Unified error handling and logging across the agent triad.
    """
    
    def __init__(self, model: str, temperature: float, api_key: str, ai_client: Optional[genai.Client] = None):
        """
        Initializes the agent with core AI configuration and dependencies.
        
        Args:
            model: The Gemini model identifier (e.g., 'gemini-2.0-flash').
            temperature: Creativity control (higher = more variance).
            api_key: Gemini API key for standalone initialization.
            ai_client: Optional pre-configured client for Dependency Injection.
        """
        self.model = model
        self.temperature = temperature
        self.client = ai_client or genai.Client(api_key=api_key)
        
        # Load Global Network Configuration
        self.network_cfg = self._load_network_config()
        gemini_cfg = self.network_cfg.get('network', {}).get('gemini', {})
        self.retry_count = int(gemini_cfg.get('retry_count', 2))
        self.api_timeout = int(gemini_cfg.get('api_timeout_seconds', 30))

    def _load_network_config(self) -> Dict[str, Any]:
        """Loads the global configuration from YAML (for network settings)."""
        try:
            cfg_path = os.path.join(resolve_project_root(), "config", "global_config.yaml")
            if os.path.exists(cfg_path):
                with open(cfg_path, 'r') as f:
                    return yaml.safe_load(f)
        except Exception as e:
            logger.error(f"BaseAgent: Failed to load global_config.yaml: {e}")
        return {}

    def _prepare_prompt(self, template_path: str, **context) -> str:
        """
        Reads a requirement template and injects semantic context variables.
        
        Uses 'safe_format' to ensure missing placeholders don't crash the pipeline,
        preserving the raw template tags for debugging.
        """
        try:
            template = read_prompt_template(template_path)
            return safe_format(template, **context)
        except Exception as e:
            logger.error(f"BaseAgent: Failed to prepare prompt from {template_path}: {e}")
            raise

    def _execute_ai_cycle(
        self, 
        payload: Union[str, List[Any]], 
        temperature: Optional[float] = None,
        agent_name: str = "Agent"
    ) -> Dict[str, Any]:
        """
        Orchestrates a single high-fidelity interaction with the AI model.
        
        Args:
            payload: The input content (Markdown string or a list of multi-modal Parts).
            temperature: Optional override for the model's creativity setting.
            agent_name: Descriptive name for logging context.
            
        Returns:
            A structured dictionary extracted from the AI's 'Strict JSON' response.
            Returns an error dictionary if parsing or execution fails.
        """
        try:
            temp = temperature if temperature is not None else self.temperature
            
            # Use dynamic retry strategy based on global_config.yaml
            from tenacity import Retrying, stop_after_attempt, wait_exponential, retry_if_exception_type

            retryer = Retrying(
                stop=stop_after_attempt(self.retry_count),
                wait=wait_exponential(multiplier=1, min=2, max=10),
                retry=retry_if_exception_type(Exception),
                before_sleep=lambda retry_state: logger.warning(
                    f"{agent_name}: Network issues detected. Retrying ({retry_state.attempt_number}/{self.retry_count})..."
                )
            )

            def _call_genai():
                # Note: GenAI SDK timeout is usually handled in the client config or http_options
                # We apply it via http_options if supported, otherwise we rely on the SDK's internal timeouts.
                return self.client.models.generate_content(
                    model=self.model,
                    contents=payload,
                    config=types.GenerateContentConfig(
                        temperature=temp,
                        response_mime_type="application/json",
                        http_options={'timeout': self.api_timeout * 1000} # ms
                    )
                )

            for attempt in retryer:
                with attempt:
                    response = _call_genai()
            
            # Extract and validate structured output
            parsed = extract_json_from_text(response.text)
            if parsed is None:
                logger.error(f"{agent_name}: Failed to parse JSON from response: {response.text}")
                return {
                    "error": "JSON_PARSE_FAILURE", 
                    "raw_response": response.text,
                    "agent": agent_name
                }
            
            return parsed
        except Exception as e:
            logger.error(f"{agent_name} AI execution failed: {e}", exc_info=True)
            return {
                "error": f"{agent_name.upper()}_EXECUTION_FAILURE", 
                "details": str(e),
                "agent": agent_name
            }
