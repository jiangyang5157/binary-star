"""Abstract AI client interface — decouples agents from LLM SDKs."""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


@dataclass
class VisualPart:
    """Provider-agnostic visual content (image, chart, etc.).

    Replaces direct `google.genai.types.Part` usage so the orchestrator
    and agents never import provider-specific types.
    """

    mime_type: str
    data: bytes
    label: str | None = None


class VisualMode(Enum):
    """How visual context is delivered to the model."""
    NONE = "none"    # skip entirely (save tokens)
    TEXT = "text"    # inject .md text summary into prompt
    IMAGE = "image"  # attach .png images as VisualPart


@dataclass
class ToolCall:
    """Provider-agnostic function call."""
    name: str
    args: dict


@dataclass
class UsageMetadata:
    """Token usage snapshot."""
    total_token_count: int = 0
    prompt_token_count: int = 0
    candidates_token_count: int = 0
    cached_content_token_count: int = 0


@dataclass
class AIResponse:
    """Provider-agnostic LLM response."""
    text: str
    tool_calls: list[ToolCall] | None = None
    usage: UsageMetadata | None = None
    reasoning_content: str | None = None  # DeepSeek thinking models


class AbstractAIClient(ABC):
    """Interface for LLM providers — mirrors AbstractExchangeClient pattern."""

    @abstractmethod
    def generate_content(
        self,
        model: str,
        contents: list[Any],
        *,
        system_instruction: str | None = None,
        tools: list[Any] | None = None,
        temperature: float = 0.5,
        response_json: bool = False,
        http_timeout: int | None = None,
    ) -> AIResponse:
        """Send contents and return provider-agnostic response.

        `contents` items are plain dicts:
          {"role": "user"|"model", "text": str}
          {"role": "model", "tool_calls": [{"id": str, "name": str, "args": dict}]}
          {"role": "user", "tool_responses": [{"id": str, "name": str, "result": any}]}
        """
        ...

    def close(self) -> None:
        """Release any held resources. Override in subclasses that hold connections (HTTP, WS)."""
        pass

    @property
    def visual_mode(self) -> VisualMode:
        """How this provider receives visual context."""
        return VisualMode.NONE

    @property
    def supports_context_cache(self) -> bool:
        return False

    # Cache hooks (Gemini only — no-op by default)
    def create_cache(self, **kwargs) -> str | None:
        return None

    def delete_cache(self, name: str) -> bool:
        return False
