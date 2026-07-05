"""Factory for AI clients — returns AbstractAIClient implementations."""
import logging
import os
from typing import Any

from src.infrastructure.ai_client import AbstractAIClient
from src.utils.pipeline_utils import load_config

logger = logging.getLogger(__name__)


class AIFactory:
    @staticmethod
    def create_client(
        api_key: str | None = None,
        config_dict: dict[str, Any] | None = None,
    ) -> AbstractAIClient:
        config = config_dict or load_config("config/global_config.yaml")
        llm_cfg = config.get("llm", {})
        provider = llm_cfg.get("active_provider", "gemini").lower()

        if provider == "deepseek":
            from src.infrastructure.ai.deepseek_adapter import DeepSeekAdapter
            cfg = llm_cfg.get("deepseek", {})
            key = api_key or os.getenv("DEEPSEEK_API_KEY")
            if not key:
                raise ValueError("DEEPSEEK_API_KEY not found")
            return DeepSeekAdapter(
                api_key=key,
                default_model=cfg.get("model", "deepseek-v4-flash"),
                base_url=cfg.get("base_url", "https://api.deepseek.com"),
                http_timeout=int(llm_cfg.get("api_timeout_seconds", 240)),
            )
        elif provider == "gemini":
            from src.infrastructure.ai.gemini_adapter import GeminiAdapter
            return GeminiAdapter(api_key=api_key)
        else:
            raise ValueError(f"Unknown LLM provider: {provider}")
