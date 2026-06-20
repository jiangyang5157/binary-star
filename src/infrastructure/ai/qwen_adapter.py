"""QwenAdapter — Alibaba Qwen via OpenAI-compatible API."""
import json
import logging
from typing import Any

from src.infrastructure.ai_client import (
    AbstractAIClient, AIResponse, ToolCall, UsageMetadata,
)
from src.infrastructure.ai._openai_helpers import (
    build_messages, convert_tools, clean_json_text,
)

logger = logging.getLogger(__name__)


class QwenAdapter(AbstractAIClient):
    def __init__(self, api_key: str, default_model: str = "qwen-plus",
                 base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"):
        self.api_key = api_key
        self.default_model = default_model
        self.base_url = base_url
        self._client = None

    @property
    def supports_context_cache(self) -> bool:
        return False

    def _get_client(self):
        if self._client is None:
            from openai import OpenAI
            self._client = OpenAI(api_key=self.api_key, base_url=self.base_url)
        return self._client

    def generate_content(
        self, model: str, contents: list[Any], *,
        system_instruction: str | None = None,
        tools: list[Any] | None = None,
        temperature: float = 0.5,
        response_json: bool = False,
        http_timeout: int | None = None,
    ) -> AIResponse:
        target_model = self.default_model if "gemini" in model.lower() else model
        messages = build_messages(system_instruction, contents)
        openai_tools = convert_tools(tools) if tools else None

        api_params: dict[str, Any] = {
            "model": target_model, "messages": messages,
            "temperature": temperature,
        }
        if openai_tools:
            api_params["tools"] = openai_tools
            api_params["tool_choice"] = "auto"
        if response_json:
            api_params["response_format"] = {"type": "json_object"}

        logger.info("QwenAdapter: → %s", target_model)
        response = self._get_client().chat.completions.create(**api_params)
        return self._parse(response, response_json)

    def _parse(self, response, is_json: bool) -> AIResponse:
        msg = response.choices[0].message
        text = clean_json_text(msg.content or "") if is_json else (msg.content or "")
        tool_calls = None
        if msg.tool_calls:
            tool_calls = []
            for tc in msg.tool_calls:
                try:
                    args = json.loads(tc.function.arguments) if tc.function.arguments else {}
                except json.JSONDecodeError:
                    args = {}
                tool_calls.append(ToolCall(name=tc.function.name, args=args))
        usage = None
        if response.usage:
            usage = UsageMetadata(
                total_token_count=response.usage.total_tokens or 0,
                prompt_token_count=response.usage.prompt_tokens or 0,
                candidates_token_count=response.usage.completion_tokens or 0,
            )
        return AIResponse(text=text, tool_calls=tool_calls, usage=usage)
