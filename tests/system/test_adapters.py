"""Integration smoke tests for AI provider adapters.

These tests verify that adapter constructors and the AIFactory work correctly.
Live API tests are skipped unless real API keys are configured.
"""
import os
import pytest
from dotenv import load_dotenv

load_dotenv()


def test_deepseek_adapter_constructs():
    """DeepSeekAdapter can be constructed with an API key."""
    from src.infrastructure.ai.deepseek_adapter import DeepSeekAdapter
    adapter = DeepSeekAdapter(
        api_key="test-key",
        default_model="deepseek-v4-flash",
        base_url="https://api.deepseek.com",
    )
    assert adapter is not None


def test_gemini_adapter_constructs():
    """GeminiAdapter can be constructed with an API key."""
    from src.infrastructure.ai.gemini_adapter import GeminiAdapter
    adapter = GeminiAdapter(api_key="test-key")
    assert adapter is not None


def test_ai_factory_supports_providers():
    """AIFactory can be imported and lists supported providers."""
    from src.infrastructure.ai_factory import AIFactory
    assert hasattr(AIFactory, 'create_client') or hasattr(AIFactory, 'create')


@pytest.mark.skipif(
    not os.getenv("DEEPSEEK_API_KEY") or "your-deepseek-api-key" in os.getenv("DEEPSEEK_API_KEY", ""),
    reason="DEEPSEEK_API_KEY not configured in .env",
)
def test_deepseek_live_query():
    """DeepSeek adapter can send a live query and receive a response."""
    from src.infrastructure.ai.deepseek_adapter import DeepSeekAdapter
    api_key = os.getenv("DEEPSEEK_API_KEY")
    adapter = DeepSeekAdapter(
        api_key=api_key,
        default_model="deepseek-v4-flash",
        base_url="https://api.deepseek.com",
    )
    response = adapter.generate_content(
        model="deepseek-v4-flash",
        contents=['What is 2+2? Respond with JSON: {"answer": number}'],
        response_json=True,
        temperature=0.1,
    )
    assert response.text is not None
    assert '"answer"' in response.text

