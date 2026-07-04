"""QwenAdapter — thin subclass of OpenAICompatibleAdapter."""
from src.infrastructure.ai._openai_helpers import OpenAICompatibleAdapter


class QwenAdapter(OpenAICompatibleAdapter):
    """Talks to Alibaba Qwen (DashScope) via the shared OpenAI-compatible protocol."""

    def __init__(self, api_key: str, default_model: str = "qwen-plus",
                 base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1",
                 *, http_timeout: int = 240):
        super().__init__(api_key=api_key, default_model=default_model,
                         base_url=base_url, provider_label="QwenAdapter",
                         http_timeout=http_timeout)
