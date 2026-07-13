"""Domain exception types for the BinaryStar pipeline.

Replaces dict-based error returns in agent inference with typed exceptions
so callers can handle specific failure modes without inspecting dict keys.
"""


class BinaryStarError(Exception):
    """Base exception for all BinaryStar pipeline errors."""


# ── Agent inference errors ────────────────────────────────────────────────────

class AgentInferenceError(BinaryStarError):
    """Raised when an AI agent's inference cycle fails."""

    def __init__(self, message: str, agent_name: str = "Unknown"):
        self.agent_name = agent_name
        super().__init__(f"[{agent_name}] {message}")


class EmptyModelResponseError(AgentInferenceError):
    """The LLM returned an empty response (no text, no tool calls)."""

    def __init__(self, message: str = "Model returned empty response", agent_name: str = "Unknown"):
        super().__init__(message, agent_name=agent_name)


class MalformedJSONError(AgentInferenceError):
    """The LLM response could not be parsed as valid JSON."""

    def __init__(self, raw_text: str, agent_name: str = "Unknown"):
        self.raw_text = raw_text
        super().__init__(
            f"Malformed JSON: {raw_text[:200]}...", agent_name=agent_name,
        )


class MaxIterationsError(AgentInferenceError):
    """The agent reached the maximum tool-call iteration limit."""

    def __init__(self, message: str = "Max tool-call iterations reached", agent_name: str = "Unknown"):
        super().__init__(message, agent_name=agent_name)


class AIProviderError(AgentInferenceError):
    """The AI provider returned an error (HTTP error, timeout, etc.)."""

    def __init__(self, details: str, agent_name: str = "Unknown"):
        self.details = details
        super().__init__(details, agent_name=agent_name)


# ── Data / configuration errors ───────────────────────────────────────────────

class DataIntegrityError(BinaryStarError):
    """Market data is insufficient or corrupt for analysis."""


class ConfigurationError(BinaryStarError):
    """Required configuration keys are missing or invalid."""
