import math
import os
import re
from typing import Any
from tenacity import Retrying, RetryError, stop_after_attempt, wait_exponential, retry_if_exception
from dataclasses import dataclass

from src.infrastructure.ai_client import AbstractAIClient, AIResponse, ToolCall, UsageMetadata
from src.utils.pipeline_utils import read_prompt_template, safe_format
from src.utils.json_utils import extract_json_from_text
from src.utils.logger_utils import setup_logger
from src.utils.rate_limiter import CongestionController
from src.utils.exceptions import (
    AgentInferenceError,
    EmptyModelResponseError,
    MalformedJSONError,
    MaxIterationsError,
    AIProviderError,
)

# Initialize standard hardened logger for base agent telemetry
logger = setup_logger(__name__)

@dataclass(frozen=True)
class AgentConfig:
    """Base configuration for neural agents.

    Attributes:
        model: The Gemini model identifier (e.g., 'gemini-2.0-flash').
        model_temperature: Model creativity override.
        instruction_path: Absolute path to the system instruction template.
        max_tool_iterations: Safety ceiling for autonomous tool-looping.
    """
    model: str
    model_temperature: float
    instruction_path: str
    max_tool_iterations: int

class BaseAgent:
    """Abstract Base Class for all AI-driven agents in the Singularity pipeline.

    Provides standardized orchestration for multimodal neural inference,
    autonomous tool-call handshaking, and robust error recovery patterns.

    Attributes:
        config: Standardized AgentConfig.
        client: The shared AbstractAIClient instance.
        api_timeout: HTTP timeout limit in seconds.
    """

    def __init__(
        self,
        config: AgentConfig,
        ai_client: AbstractAIClient,
        api_timeout: int,
        retry_count: int,
        retry_multiplier: float,
        retry_min: int,
        retry_max: int,
        congestion_controller: CongestionController | None = None
    ):
        """Initializes the agent with core AI configuration and dependencies.

        Args:
            config: Type-safe AgentConfig object.
            ai_client: The shared AbstractAIClient instance.
            api_timeout: Global timeout for neural inference.
            retry_count: Number of retry attempts on transient failure.
            retry_multiplier: Exponential backoff multiplier.
            retry_min: Minimum backoff time (seconds).
            retry_max: Maximum backoff time (seconds).
            congestion_controller: Pacing manager for RPM compliance.
        """
        self.config = config
        self.model = config.model
        self.temperature = config.model_temperature
        self.max_tool_iterations = config.max_tool_iterations
        self.client = ai_client
        self.api_timeout = api_timeout
        self.retry_count = retry_count
        self.retry_multiplier = retry_multiplier
        self.retry_min = retry_min
        self.retry_max = retry_max
        self.congestion_controller = congestion_controller

    def _prepare_prompt(self, template_path: str, **context: Any) -> str:
        """Reads a prompt template and injects semantic context variables.

        Prioritizes the in-memory instruction_literal if provided in the config,
        otherwise falls back to reading from the template_path on disk.
        """
        try:
            # Phase 1: Context Retrieval (Literal vs. Disk)
            # Prioritizing instruction_literal for sandbox/in-memory experiments
            instruction_literal = getattr(self.config, 'instruction_literal', None)

            if instruction_literal:
                template = instruction_literal
            else:
                template = read_prompt_template(template_path)
            rendered = safe_format(template, **context)

            # Detect missing template variables: compare what the template
            # declares against what the caller provided.  We intentionally
            # avoid regex-scanning the rendered output because substituted
            # values (e.g. embedded prompt files) may contain {placeholders}
            # of their own that are meant to be seen verbatim by the LLM.
            template_vars = set(re.findall(r'\{(\w+)\}', template))
            missing = template_vars - set(context.keys())
            if missing:
                raise ValueError(
                    f"BaseAgent: {len(missing)} unresolved template variable(s) "
                    f"in {os.path.basename(template_path)}: {', '.join(sorted(missing))}"
                )

            return rendered
        except Exception as e:
            logger.error(f"BaseAgent: Failed to prepare prompt from {template_path}: {e}")
            raise

    def _call_ai_provider(
        self,
        contents: list[Any],
        temperature: float,
        agent_name: str,
        cache_resource_name: str | None,
        tools: list[Any] | None,
        system_instruction: str | None,
    ) -> AIResponse:
        """Single AI inference call with retry and congestion pacing."""
        _NON_RETRYABLE = (ValueError, TypeError, KeyError, AttributeError,
                          AgentInferenceError)
        retryer = Retrying(
            stop=stop_after_attempt(self.retry_count),
            wait=wait_exponential(
                multiplier=self.retry_multiplier,
                min=self.retry_min, max=self.retry_max,
            ),
            retry=retry_if_exception(lambda e: not isinstance(e, _NON_RETRYABLE)),
        )
        use_json_mode = not tools and not cache_resource_name

        if self.congestion_controller:
            self.congestion_controller.pace(agent_name=agent_name)

        response: AIResponse = retryer(
            self.client.generate_content,
            model=self.model,
            contents=contents,
            system_instruction=system_instruction if not cache_resource_name else None,
            tools=tools if not cache_resource_name else None,
            temperature=temperature,
            response_json=use_json_mode,
            http_timeout=self.api_timeout,
        )

        if response.usage:
            u = response.usage
            logger.info(
                "[%s] Usage: T=%d | P=%d | C=%d | Cache=%d",
                agent_name, u.total_token_count, u.prompt_token_count,
                u.candidates_token_count, u.cached_content_token_count,
            )
        return response

    @staticmethod
    def _extract_simulated_tool_calls(parsed: dict) -> list[ToolCall]:
        """Detect models that describe function calls in text instead of native tool_calls.

        Two formats observed (e.g. DeepSeek v4 pro):
          A) {tool, parameters}              — single simulated call
          B) {tool_calls: [{name, arguments}]} — batch simulated calls
        """
        simulated: list[ToolCall] = []
        if "tool" in parsed and "parameters" in parsed:
            simulated.append(ToolCall(
                name=parsed["tool"],
                args=parsed.get("parameters", {}),
            ))
        elif isinstance(parsed.get("tool_calls"), list):
            for tc in parsed["tool_calls"]:
                if isinstance(tc, dict) and "name" in tc:
                    simulated.append(ToolCall(
                        name=tc["name"],
                        args=tc.get("arguments", tc.get("args", {})),
                    ))
        return simulated

    def _dispatch_tool_calls_to_contents(
        self,
        contents: list[Any],
        tool_calls: list[ToolCall],
        next_tc_id: int,
        reasoning_content: str | None = None,
    ) -> int:
        """Dispatch tool calls, append model+tool messages to contents. Returns new next_tc_id."""
        tc_entries = []
        for tc in tool_calls:
            tc_entries.append({
                "id": f"call_{next_tc_id}", "name": tc.name, "args": tc.args,
            })
            next_tc_id += 1
        model_msg: dict = {"role": "model", "tool_calls": tc_entries}
        if reasoning_content:
            model_msg["reasoning_content"] = reasoning_content
        contents.append(model_msg)

        tool_responses = []
        for entry, tc in zip(tc_entries, tool_calls):
            result = self._dispatch_tool_call(tc)
            tool_responses.append({
                "id": entry["id"], "name": tc.name, "result": result,
            })
        contents.append({"role": "user", "tool_responses": tool_responses})
        return next_tc_id

    def _execute_ai_cycle(
        self,
        payload: str | list[Any],
        temperature: float | None = None,
        agent_name: str = "Agent",
        cache_resource_name: str | None = None,
        tools: list[Any] | None = None,
        system_instruction: str | None = None,
    ) -> dict[str, Any]:
        """Autonomous iterative cycle: AI inference ↔ tool dispatch until convergence.

        Returns a parsed JSON dict.  See class docstring for raised exceptions.
        """
        try:
            temp = temperature if temperature is not None else self.temperature
            contents: list[Any] = payload if isinstance(payload, list) else [payload]
            iteration = 0
            next_tc_id = 0

            while iteration < self.max_tool_iterations:
                iteration += 1

                response = self._call_ai_provider(
                    contents, temp, agent_name,
                    cache_resource_name, tools, system_instruction,
                )

                if not response.text and not response.tool_calls:
                    logger.error("BaseAgent: %s returned empty response.", agent_name)
                    raise EmptyModelResponseError(agent_name=agent_name)

                # No tool calls → termination (check for simulated calls first)
                if not response.tool_calls:
                    if not response.text.strip():
                        logger.error("BaseAgent: %s returned empty text.", agent_name)
                        raise EmptyModelResponseError(agent_name=agent_name)

                    parsed = self._parse_and_validate_response(response.text, agent_name)
                    simulated = self._extract_simulated_tool_calls(parsed)

                    if simulated and "opinion" not in parsed:
                        logger.info(
                            "BaseAgent: %s simulated %d tool call(s) in text — dispatching.",
                            agent_name, len(simulated),
                        )
                        next_tc_id = self._dispatch_tool_calls_to_contents(
                            contents, simulated, next_tc_id, response.reasoning_content,
                        )
                        continue

                    return parsed

                # Real tool calls → dispatch, append results, loop
                next_tc_id = self._dispatch_tool_calls_to_contents(
                    contents, response.tool_calls, next_tc_id, response.reasoning_content,
                )

            logger.error("%s: max iterations (%d).", agent_name, self.max_tool_iterations)
            raise MaxIterationsError(agent_name=agent_name)

        except AgentInferenceError:
            raise
        except RetryError as e:
            actual_error = e.last_attempt.exception() if e.last_attempt and e.last_attempt.failed else e
            err_msg = str(actual_error)
            if hasattr(actual_error, "response") and hasattr(actual_error.response, "text"):
                err_msg = f"{err_msg} | Body: {actual_error.response.text}"
            logger.error("%s Inference Failure: %s", agent_name, err_msg)
            raise AIProviderError(details=err_msg, agent_name=agent_name) from actual_error
        except Exception as e:
            logger.error("%s Inference Failure: %s", agent_name, str(e))
            raise AIProviderError(details=str(e), agent_name=agent_name) from e

    def _parse_and_validate_response(self, text: str, agent_name: str) -> dict[str, Any]:
        """Extracts and validates structured JSON output from model candidates.

        Args:
            text: The raw text extracted from response parts.
            agent_name: Identity for error attribution.

        Returns:
            Extracted dictionary. Defaults to error object if malformed.
        """
        parsed = extract_json_from_text(text)
        if parsed is None:
            logger.error(f"BaseAgent: {agent_name} returned malformed JSON: {text[:200]}...")
            raise MalformedJSONError(raw_text=text, agent_name=agent_name)
        # Clamp confidence_score to valid range [0, 100] — guard against hallucinated values
        if "confidence_score" in parsed:
            try:
                cs = float(parsed["confidence_score"])
                if not math.isfinite(cs):
                    cs = 0.0
                parsed["confidence_score"] = max(0.0, min(100.0, cs))
            except (TypeError, ValueError):
                parsed["confidence_score"] = 0.0
        return parsed

    def _dispatch_tool_call(self, tc: ToolCall) -> Any:
        """Dynamically dispatches a tool-call to the local agent instance.

        Args:
            tc: ToolCall specification (name + args).

        Returns:
            The execution result or error string.
        """
        import inspect
        name = tc.name
        args = tc.args or {}
        try:
            if hasattr(self, name):
                method = getattr(self, name)
                # Filter args to only those the method actually accepts —
                # models sometimes pass extra context fields (opinion, atr_macro, etc.)
                sig = inspect.signature(method)
                valid_params = set(sig.parameters.keys())
                filtered = {k: v for k, v in args.items() if k in valid_params}
                dropped = set(args.keys()) - valid_params
                if dropped:
                    logger.debug(
                        "BaseAgent: Dropped extra tool args for '%s': %s",
                        name, sorted(dropped),
                    )
                logger.info("BaseAgent: Dispatching tool '%s'...", name)
                return method(**filtered)
            else:
                logger.error("BaseAgent: Tool '%s' not found.", name)
                return f"Error: Tool '{name}' missing."
        except Exception as e:
            logger.error("BaseAgent: Tool '%s' error: %s", name, e)
            return f"Tool Error: {str(e)}"

    # --- Tool Delegates (Function Calling Interfaces) ---

    def calculate_risk_reward(self, entry: float, take_profit: float, stop_loss: float) -> dict[str, Any]:
        """[TOOL] Calculates the Risk-Reward (RR) ratio for a trade geometry."""
        from src.utils.math_utils import MathTools
        return MathTools.calculate_risk_reward(entry, take_profit, stop_loss)

    def calculate_atr_metrics(self, entry: float, stop_loss: float, take_profit: float, atr: float, current_price: float | None = None) -> dict[str, Any]:
        """[TOOL] Standardizes trade distances using ATR (Average True Range)."""
        from src.utils.math_utils import MathTools
        return MathTools.calculate_atr_metrics(entry, stop_loss, take_profit, atr, current_price)

    def calculate_structural_proximity(self, stop_loss: float, atr: float, poc: float | None = None, vah: float | None = None, val: float | None = None) -> dict[str, Any]:
        """[TOOL] Calculates stop-loss distance to structural anchors (POC/VAH/VAL) in ATR units."""
        from src.utils.math_utils import MathTools
        return MathTools.calculate_structural_proximity(stop_loss, atr, poc, vah, val)
