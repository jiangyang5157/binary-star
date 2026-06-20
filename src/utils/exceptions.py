"""Domain exception types for the Singularity pipeline.

Replaces dict-based error returns in agent inference with typed exceptions
so callers can handle specific failure modes without inspecting dict keys.
"""


class SingularityError(Exception):
    """Base exception for all Singularity pipeline errors."""


# ── Agent inference errors ────────────────────────────────────────────────────

class AgentInferenceError(SingularityError):
    """Raised when an AI agent's inference cycle fails."""

    def __init__(self, message: str, agent_name: str = "Unknown"):
        self.agent_name = agent_name
        super().__init__(f"[{agent_name}] {message}")


class EmptyModelResponseError(AgentInferenceError):
    """The LLM returned an empty response (no text, no tool calls)."""


class MalformedJSONError(AgentInferenceError):
    """The LLM response could not be parsed as valid JSON."""

    def __init__(self, raw_text: str, agent_name: str = "Unknown"):
        self.raw_text = raw_text
        super().__init__(
            f"Malformed JSON: {raw_text[:200]}...", agent_name=agent_name,
        )


class MaxIterationsError(AgentInferenceError):
    """The agent reached the maximum tool-call iteration limit."""


class AIProviderError(AgentInferenceError):
    """The AI provider returned an error (HTTP error, timeout, etc.)."""

    def __init__(self, details: str, agent_name: str = "Unknown"):
        self.details = details
        super().__init__(details, agent_name=agent_name)


# ── Data / configuration errors ───────────────────────────────────────────────

class DataIntegrityError(SingularityError):
    """Market data is insufficient or corrupt for analysis."""


class ConfigurationError(SingularityError):
    """Required configuration keys are missing or invalid."""
