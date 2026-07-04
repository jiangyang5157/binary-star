"""Verify all adapters satisfy AbstractAIClient contract."""
import pytest
from src.infrastructure.ai_client import AbstractAIClient, AIResponse, ToolCall, UsageMetadata
from src.infrastructure.ai.gemini_adapter import GeminiAdapter
from src.infrastructure.ai.deepseek_adapter import DeepSeekAdapter
from src.infrastructure.ai.qwen_adapter import QwenAdapter


def test_all_adapters_implement_interface():
    adapters = [
        GeminiAdapter("test-key"),
        DeepSeekAdapter("test-key", default_model="test-model"),
        QwenAdapter("test-key", default_model="test-model"),
    ]
    for adapter in adapters:
        assert isinstance(adapter, AbstractAIClient), \
            f"{type(adapter).__name__} does not implement AbstractAIClient"


def test_ai_response_dataclass():
    r = AIResponse(text="{}", usage=UsageMetadata(total_token_count=100))
    assert r.text == "{}"
    assert r.usage.total_token_count == 100
    assert r.tool_calls is None


def test_ai_response_with_tool_calls():
    tc = ToolCall(name="place_order", args={"side": "BUY", "price": 100.0})
    r = AIResponse(text="ok", tool_calls=[tc])
    assert r.tool_calls[0].name == "place_order"
    assert r.tool_calls[0].args["side"] == "BUY"


def test_usage_metadata_defaults():
    u = UsageMetadata()
    assert u.total_token_count == 0
    assert u.prompt_token_count == 0
    assert u.candidates_token_count == 0
    assert u.cached_content_token_count == 0


def test_abstract_client_cannot_instantiate():
    """AbstractAIClient cannot be instantiated directly."""
    with pytest.raises(TypeError):
        AbstractAIClient()  # type: ignore[abstract]
