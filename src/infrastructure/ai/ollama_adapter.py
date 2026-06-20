"""OllamaAdapter — local Ollama implementing AbstractAIClient."""
import logging
from typing import Any

from src.infrastructure.ai_client import (
    AbstractAIClient, AIResponse, UsageMetadata,
)
from src.infrastructure.ai._openai_helpers import JSON_HINT, clean_json_text

logger = logging.getLogger(__name__)


class OllamaAdapter(AbstractAIClient):
    def __init__(self, base_url: str, default_model: str):
        self.base_url = base_url
        self.default_model = default_model

    @property
    def supports_context_cache(self) -> bool:
        return False

    def generate_content(
        self, model: str, contents: list[Any], *,
        system_instruction: str | None = None,
        tools: list[Any] | None = None,
        temperature: float = 0.5,
        response_json: bool = False,
        http_timeout: int | None = None,
    ) -> AIResponse:
        target_model = self.default_model if "gemini" in model.lower() else model
        system_content = (
            f"{system_instruction}\n\n{JSON_HINT}"
            if system_instruction else JSON_HINT
        )
        messages: list[dict] = [{"role": "system", "content": system_content}]
        for item in contents:
            if isinstance(item, str):
                messages.append({"role": "user", "content": item})
            elif isinstance(item, dict) and "text" in item:
                messages.append({"role": item.get("role", "user"), "content": item["text"]})

        import ollama
        logger.info("OllamaAdapter: → %s", target_model)
        response = ollama.chat(
            model=target_model, messages=messages,
            format="json" if response_json else None,
            options={"temperature": temperature, "num_ctx": 8192},
        )
        msg = response.get("message", {})
        text = clean_json_text(msg.get("content", "")) if response_json else msg.get("content", "")
        return AIResponse(
            text=text,
            usage=UsageMetadata(
                total_token_count=response.get("total_duration", 0) // 1_000_000,
            ),
        )
