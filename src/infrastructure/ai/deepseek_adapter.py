"""DeepSeekAdapter — thin subclass of OpenAICompatibleAdapter."""
import logging
from typing import Any

from src.infrastructure.ai._openai_helpers import OpenAICompatibleAdapter, convert_tools, build_messages
from src.infrastructure.ai_client import AIResponse, VisualMode

logger = logging.getLogger(__name__)


class DeepSeekAdapter(OpenAICompatibleAdapter):
    """Talks to DeepSeek API via the shared OpenAI-compatible protocol.

    Enables thinking mode (reasoning_effort) which disables temperature.
    """

    def __init__(self, api_key: str, default_model: str = "deepseek-v4-flash",
                 base_url: str = "https://api.deepseek.com",
                 *, reasoning_effort: str = "high", http_timeout: int = 240):
        super().__init__(api_key=api_key, default_model=default_model,
                         base_url=base_url, provider_label="DeepSeekAdapter",
                         http_timeout=http_timeout)
        self._reasoning_effort = reasoning_effort

    @property
    def visual_mode(self) -> "VisualMode":
        return VisualMode.TEXT

    def generate_content(
        self, model: str, contents: list[Any], *,
        system_instruction: str | None = None,
        tools: list[Any] | None = None,
        temperature: float = 0.5,          # ignored — thinking mode hardcoded enabled
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
            "reasoning_effort": self._reasoning_effort,
            "extra_body": {"thinking": {"type": "enabled"}},
        }
        # thinking mode disables temperature — omit it
        if openai_tools:
            api_params["tools"] = openai_tools
            api_params["tool_choice"] = "auto"
        if response_json:
            api_params["response_format"] = {"type": "json_object"}
        if http_timeout:
            api_params["timeout"] = http_timeout

        if not self._model_logged:
            logger.info("AI call | provider=%s | model=%s | thinking=%s", self.provider_label, target_model, self._reasoning_effort)
            self._model_logged = True
        else:
            logger.debug("AI call | provider=%s | model=%s | thinking=%s", self.provider_label, target_model, self._reasoning_effort)
        response = self._get_client().chat.completions.create(**api_params)
        return self._parse(response, response_json)
