import logging
import os
from typing import Any, Dict
from google import genai
from src.utils.pipeline_utils import load_config

logger = logging.getLogger(__name__)

class AIFactory:
    """Factory for generating AI clients based on global infrastructure configuration."""
    
    @staticmethod
    def create_client(api_key: str = None, config_dict: Dict[str, Any] = None) -> Any:
        """Creates and returns the active LLM client (Gemini, Ollama, DeepSeek, or Qwen)."""
        try:
            config = config_dict or load_config('config/global_config.yaml')
            llm_cfg = config.get('llm', {})
            provider = llm_cfg.get('active_provider', 'gemini').lower()
            
            if provider == 'ollama':
                from src.infrastructure.ollama_adapter import OllamaAdapter
                ollama_cfg = llm_cfg.get('ollama', {})
                base_url = ollama_cfg.get('base_url')
                model = ollama_cfg.get('model')
                
                logger.info(f"AIFactory: Initializing OLLAMA provider (Model: {model}, URL: {base_url})")
                return OllamaAdapter(base_url=base_url, default_model=model)
            
            elif provider == 'deepseek':
                from src.infrastructure.deepseek_adapter import DeepSeekAdapter
                deepseek_cfg = llm_cfg.get('deepseek', {})
                api_key = api_key or os.getenv('DEEPSEEK_API_KEY')
                base_url = deepseek_cfg.get('base_url', 'https://api.deepseek.com')
                model = deepseek_cfg.get('model', 'deepseek-v4-flash')
                
                if not api_key:
                    raise ValueError("DEEPSEEK_API_KEY not found in environment variables or .env file")
                
                logger.info(f"AIFactory: Initializing DEEPSEEK provider (Model: {model}, URL: {base_url})")
                return DeepSeekAdapter(api_key=api_key, default_model=model, base_url=base_url)
            
            elif provider == 'qwen':
                from src.infrastructure.qwen_adapter import QwenAdapter
                qwen_cfg = llm_cfg.get('qwen', {})
                api_key = api_key or os.getenv('QWEN_API_KEY')
                base_url = qwen_cfg.get('base_url', 'https://dashscope.aliyuncs.com/compatible-mode/v1')
                model = qwen_cfg.get('model', 'qwen-plus')
                
                if not api_key:
                    raise ValueError("QWEN_API_KEY not found in environment variables or .env file")
                
                logger.info(f"AIFactory: Initializing QWEN provider (Model: {model}, URL: {base_url})")
                return QwenAdapter(api_key=api_key, default_model=model, base_url=base_url)
            
            else:
                logger.info("AIFactory: Initializing GEMINI provider (Cloud)")
                if not api_key:
                    logger.warning("AIFactory: Gemini selected but no API key provided.")
                return genai.Client(api_key=api_key)
                
        except Exception as e:
            logger.error(f"AIFactory: Failed to create client: {e}")
            # Fallback to Gemini if possible
            return genai.Client(api_key=api_key) if api_key else None
