"""OllamaAdapter — local Ollama implementing AbstractAIClient."""
import json as _json
import logging
from typing import Any

import ollama

from src.infrastructure.ai_client import (
    AbstractAIClient, AIResponse, UsageMetadata, ToolCall,
)
from src.infrastructure.ai._openai_helpers import JSON_HINT, clean_json_text, build_messages, convert_tools

logger = logging.getLogger(__name__)


class OllamaAdapter(AbstractAIClient):
    def __init__(self, base_url: str, default_model: str, num_ctx: int = 8192):
        self.base_url = base_url
        self.default_model = default_model
        self.num_ctx = num_ctx

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

        # Build messages using shared OpenAI-format helper
        messages = build_messages(system_instruction, contents, response_json=response_json)

        # Convert tools to Ollama/OpenAI format
        ollama_tools = convert_tools(tools) if tools else None

        logger.info("OllamaAdapter: → %s", target_model)
        response = ollama.chat(
            model=target_model, messages=messages,
            tools=ollama_tools,
            format="json" if response_json else None,
            options={"temperature": temperature, "num_ctx": self.num_ctx},
        )
        msg = response.get("message", {})
        text = msg.get("content", "")
        if response_json and text:
            text = clean_json_text(text)

        # Extract tool calls from response
        tool_calls = None
        raw_tcs = msg.get("tool_calls", [])
        if raw_tcs:
            tool_calls = []
            for tc in raw_tcs:
                func = tc.get("function", {})
                args = func.get("arguments", {})
                if isinstance(args, str):
                    try:
                        args = _json.loads(args)
                    except _json.JSONDecodeError:
                        args = {}
                tool_calls.append(ToolCall(name=func.get("name", ""), args=args))

        return AIResponse(
            text=text,
            tool_calls=tool_calls,
            usage=UsageMetadata(
                total_token_count=response.get("total_duration", 0) // 1_000_000,
            ),
        )
