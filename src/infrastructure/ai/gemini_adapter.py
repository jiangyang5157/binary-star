"""GeminiAdapter — wraps google-genai SDK behind AbstractAIClient."""
import logging
from typing import Any

from google import genai
from google.genai import types

from src.infrastructure.ai_client import (
    AbstractAIClient, AIResponse, ToolCall, UsageMetadata, VisualPart, VisualMode,
)

logger = logging.getLogger(__name__)


class GeminiAdapter(AbstractAIClient):
    """Wraps Google GenAI SDK to match AbstractAIClient."""

    CACHE_TTL_MINUTES = 10

    def __init__(self, api_key: str, http_timeout: int = 240):
        # Per Python 3.14 + google-genai 2.9.0 compatibility: http_options
        # must live on the Client (not per-request config dict) to avoid
        # a ``copy.deepcopy`` failure on ``_thread.lock`` objects.
        self._client = genai.Client(
            api_key=api_key,
            http_options={'timeout': http_timeout * 1000},
        )
        self._active_cache_name: str | None = None

    @property
    def raw_client(self) -> genai.Client:
        """Expose underlying SDK client for cache operations."""
        return self._client

    @property
    def visual_mode(self) -> VisualMode:
        return VisualMode.IMAGE

    def generate_content(
        self, model: str, contents: list[Any], *,
        system_instruction: str | None = None,
        tools: list[Any] | None = None,
        temperature: float = 0.5,
        reasoning_effort: str | None = None,
        response_json: bool = False,
        http_timeout: int | None = None,
    ) -> AIResponse:
        # Timeout is set once on the Client (see __init__), not per-request,
        # to avoid a Python 3.14 deepcopy issue with the google-genai SDK.
        gen_config: dict[str, Any] = {
            "temperature": temperature,
        }
        if self._active_cache_name:
            gen_config["cached_content"] = self._active_cache_name
        else:
            if tools:
                gen_config["tools"] = self._normalize_tools(tools)
            if system_instruction is not None:
                gen_config["system_instruction"] = system_instruction
        if response_json:
            gen_config["response_mime_type"] = "application/json"

        gemini_contents = self._to_gemini_contents(contents)
        response = self._client.models.generate_content(
            model=model, contents=gemini_contents, config=gen_config,
        )
        return self._to_ai_response(response)

    @staticmethod
    def _normalize_tools(tools: list[Any]) -> list[Any]:
        """Convert any dict-format tool declarations to Gemini Tool objects.

        Dict format comes from ``MathTools.get_tool_declarations()``.
        Gemini ``types.Tool`` objects pass through unchanged.
        """
        normalized: list[Any] = []
        dict_fds: list[types.FunctionDeclaration] = []
        for tool in tools:
            if isinstance(tool, dict):
                props = {}
                required: list[str] = []
                raw_params = tool.get("parameters", {})
                for pn, ps in raw_params.get("properties", {}).items():
                    props[pn] = types.Schema(
                        type=ps.get("type", "STRING").upper(),
                        description=ps.get("description", ""),
                    )
                required = list(raw_params.get("required", []) or [])
                dict_fds.append(types.FunctionDeclaration(
                    name=tool.get("name", ""),
                    description=tool.get("description", ""),
                    parameters=types.Schema(
                        type="OBJECT", properties=props, required=required,
                    ),
                ))
            else:
                normalized.append(tool)
        if dict_fds:
            normalized.append(types.Tool(function_declarations=dict_fds))
        return normalized

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

    def begin_session(self, system_instruction, tools, visual_parts, model):
        """Create context cache: images + system_instruction + tools only.

        Observation JSON intentionally excluded — all models send it in prompt text.
        """
        cache_contents: list = []
        for vp in (visual_parts or []):
            cache_contents.append(
                types.Part.from_bytes(data=vp.data, mime_type=vp.mime_type)
            )
        if not cache_contents:
            return  # nothing to cache

        cache = self._client.caches.create(
            model=model,
            config=types.CreateCachedContentConfig(
                contents=cache_contents,
                system_instruction=system_instruction,
                tools=self._normalize_tools(tools) if tools else None,
            ),
            ttl=f'{self.CACHE_TTL_MINUTES}m',
        )
        self._active_cache_name = cache.name
        logger.info("cache created | name=%s | ttl=%sm", cache.name, self.CACHE_TTL_MINUTES)

    def end_session(self):
        if self._active_cache_name:
            try:
                self._client.caches.delete(name=self._active_cache_name)
            except Exception as e:
                logger.warning(f"cache delete failed: {e}")
            self._active_cache_name = None
