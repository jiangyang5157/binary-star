"""DeepSeekAdapter — thin subclass of OpenAICompatibleAdapter."""
from src.infrastructure.ai._openai_helpers import OpenAICompatibleAdapter
from src.infrastructure.ai_client import VisualMode


class DeepSeekAdapter(OpenAICompatibleAdapter):
    """Talks to DeepSeek API via the shared OpenAI-compatible protocol."""

    def __init__(self, api_key: str, default_model: str = "deepseek-v4-flash",
                 base_url: str = "https://api.deepseek.com",
                 *, http_timeout: int = 240):
        super().__init__(api_key=api_key, default_model=default_model,
                         base_url=base_url, provider_label="DeepSeekAdapter",
                         http_timeout=http_timeout)

    @property
    def visual_mode(self) -> "VisualMode":
        return VisualMode.TEXT
