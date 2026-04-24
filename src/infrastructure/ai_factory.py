import logging
from typing import Any, Optional, Dict
from google import genai
from src.infrastructure.ollama_adapter import OllamaAdapter
from src.utils.pipeline_utils import load_config

logger = logging.getLogger(__name__)

class AIFactory:
    """Factory for generating AI clients based on global infrastructure configuration."""
    
    @staticmethod
    def create_client(api_key: str = None, config_dict: Dict[str, Any] = None) -> Any:
        """Creates and returns the active LLM client (Gemini or Ollama)."""
        try:
            config = config_dict or load_config('config/global_config.yaml')
            llm_cfg = config.get('llm', {})
            provider = llm_cfg.get('active_provider', 'gemini').lower()
            
            if provider == 'ollama':
                ollama_cfg = llm_cfg.get('ollama', {})
                base_url = ollama_cfg.get('base_url')
                model = ollama_cfg.get('model')
                
                logger.info(f"AIFactory: Initializing OLLAMA provider (Model: {model}, URL: {base_url})")
                return OllamaAdapter(base_url=base_url, default_model=model)
            
            else:
                logger.info("AIFactory: Initializing GEMINI provider (Cloud)")
                if not api_key:
                    logger.warning("AIFactory: Gemini selected but no API key provided.")
                return genai.Client(api_key=api_key)
                
        except Exception as e:
            logger.error(f"AIFactory: Failed to create client: {e}")
            # Fallback to Gemini if possible
            return genai.Client(api_key=api_key) if api_key else None
