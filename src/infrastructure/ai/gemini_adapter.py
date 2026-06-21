"""GeminiAdapter — wraps google-genai SDK behind AbstractAIClient."""
import logging
from typing import Any

from google import genai
from google.genai import types

from src.infrastructure.ai_client import (
    AbstractAIClient, AIResponse, ToolCall, UsageMetadata, VisualPart,
)

logger = logging.getLogger(__name__)


class GeminiAdapter(AbstractAIClient):
    """Wraps Google GenAI SDK to match AbstractAIClient."""

    def __init__(self, api_key: str, http_timeout: int = 240):
        self._client = genai.Client(api_key=api_key)

    @property
    def raw_client(self) -> genai.Client:
        """Expose underlying SDK client for cache operations."""
        return self._client

    @property
    def supports_context_cache(self) -> bool:
        return True

    def generate_content(
        self, model: str, contents: list[Any], *,
        system_instruction: str | None = None,
        tools: list[Any] | None = None,
        temperature: float = 0.5,
        response_json: bool = False,
        http_timeout: int | None = None,
    ) -> AIResponse:
        gen_config: dict[str, Any] = {
            "temperature": temperature,
        }
        if tools:
            gen_config["tools"] = tools
        elif response_json:
            gen_config["response_mime_type"] = "application/json"
        if system_instruction is not None:
            gen_config["system_instruction"] = system_instruction

        gemini_contents = self._to_gemini_contents(contents)
        response = self._client.models.generate_content(
            model=model, contents=gemini_contents, config=gen_config,
        )
        return self._to_ai_response(response)

    def _to_gemini_contents(self, contents: list[Any]) -> list[types.Content]:
        result = []
        for item in contents:
            if isinstance(item, types.Content):
                result.append(item)
            elif isinstance(item, types.Part):
                result.append(types.Content(parts=[item], role="user"))
            elif isinstance(item, VisualPart):
                parts: list[types.Part] = []
                if item.label:
                    parts.append(types.Part.from_text(text=item.label))
                parts.append(types.Part.from_bytes(data=item.data, mime_type=item.mime_type))
                result.append(types.Content(parts=parts, role="user"))
            elif isinstance(item, str):
                result.append(types.Content(
                    parts=[types.Part.from_text(text=item)], role="user"))
            elif isinstance(item, dict):
                role = "user" if item.get("role") != "model" else "model"
                if "text" in item:
                    result.append(types.Content(
                        parts=[types.Part.from_text(text=item["text"])], role=role))
                elif "tool_responses" in item:
                    parts = [
                        types.Part.from_function_response(
                            name=tr["name"], response={"result": tr["result"]})
                        for tr in item["tool_responses"]
                    ]
                    result.append(types.Content(parts=parts, role="user"))
                elif "tool_calls" in item:
                    parts = []
                    for tc in item["tool_calls"]:
                        parts.append(types.Part.from_function_call(
                            name=tc["name"], args=tc["args"]))
                    result.append(types.Content(parts=parts, role="model"))
        return result

    def _to_ai_response(self, response) -> AIResponse:
        if not response or not response.candidates:
            return AIResponse(text="")
        content = response.candidates[0].content
        parts = getattr(content, "parts", []) or []
        text = "".join(p.text for p in parts if hasattr(p, "text") and p.text)
        tool_calls = [
            ToolCall(name=fc.name, args=dict(fc.args or {}))
            for p in parts if (fc := getattr(p, "function_call", None))
        ] or None
        usage = None
        if response.usage_metadata:
            m = response.usage_metadata
            usage = UsageMetadata(
                total_token_count=m.total_token_count,
                prompt_token_count=m.prompt_token_count,
                candidates_token_count=m.candidates_token_count,
                cached_content_token_count=m.cached_content_token_count or 0,
            )
        return AIResponse(text=text, tool_calls=tool_calls, usage=usage)

    def create_cache(self, **kwargs) -> str | None:
        cache = self._client.caches.create(**kwargs)
        return cache.name

    def delete_cache(self, name: str) -> bool:
        try:
            self._client.caches.delete(name=name)
            return True
        except Exception:
            return False
