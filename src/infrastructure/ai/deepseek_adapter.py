"""DeepSeekAdapter — thin subclass of OpenAICompatibleAdapter."""
import logging
from typing import Any

from src.infrastructure.ai._openai_helpers import OpenAICompatibleAdapter, convert_tools, build_messages
from src.infrastructure.ai_client import AIResponse, VisualMode

logger = logging.getLogger(__name__)


class DeepSeekAdapter(OpenAICompatibleAdapter):
    """Talks to DeepSeek API via the shared OpenAI-compatible protocol.

    Enables thinking mode when ``reasoning_effort`` is passed to
    ``generate_content()`` (disables temperature). Falls back to
    standard temperature-based generation when ``reasoning_effort`` is None.
    """

    def __init__(self, api_key: str, default_model: str = "deepseek-v4-flash",
                 base_url: str = "https://api.deepseek.com",
                 *, http_timeout: int = 240):
        super().__init__(api_key=api_key, default_model=default_model,
                         base_url=base_url, provider_label="DeepSeekAdapter",
                         http_timeout=http_timeout)

    @property
    def visual_mode(self) -> "VisualMode":
        return VisualMode.TEXT

    def generate_content(
        self, model: str, contents: list[Any], *,
        system_instruction: str | None = None,
        tools: list[Any] | None = None,
        temperature: float = 0.5,
        reasoning_effort: str | None = None,
        response_json: bool = False,
        http_timeout: int | None = None,
    ) -> AIResponse:
        # model param is always the orchestrator's shared_model — use as-is
        target_model = model or self.default_model
        messages = build_messages(system_instruction, contents,
                                  response_json=response_json,
                                  supports_vision=(self.visual_mode == VisualMode.IMAGE))
        openai_tools = convert_tools(tools) if tools else None

        api_params: dict[str, Any] = {
            "model": target_model,
            "messages": messages,
        }

        if reasoning_effort is not None:
            api_params["reasoning_effort"] = reasoning_effort
            api_params["extra_body"] = {"thinking": {"type": "enabled"}}
            # thinking mode disables temperature — omit it
        else:
            api_params["temperature"] = temperature

        if openai_tools:
            api_params["tools"] = openai_tools
            api_params["tool_choice"] = "auto"
        if response_json:
            api_params["response_format"] = {"type": "json_object"}
        if http_timeout:
            api_params["timeout"] = http_timeout

        think_label = reasoning_effort if reasoning_effort else "off"
        if not self._model_logged:
            logger.info("AI call | provider=%s | model=%s | thinking=%s", self.provider_label, target_model, think_label)
            self._model_logged = True
        else:
            logger.debug("AI call | provider=%s | model=%s | thinking=%s", self.provider_label, target_model, think_label)
        response = self._get_client().chat.completions.create(**api_params)
        return self._parse(response, response_json)
