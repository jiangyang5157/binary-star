"""DeepSeekAdapter — thin subclass of OpenAICompatibleAdapter."""
from src.infrastructure.ai._openai_helpers import OpenAICompatibleAdapter


class DeepSeekAdapter(OpenAICompatibleAdapter):
    """Talks to DeepSeek API via the shared OpenAI-compatible protocol."""

    def __init__(self, api_key: str, default_model: str = "deepseek-v4-flash",
                 base_url: str = "https://api.deepseek.com"):
        super().__init__(api_key=api_key, default_model=default_model,
                         base_url=base_url, provider_label="DeepSeekAdapter")
