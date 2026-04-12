from typing import Dict, Any, List, Optional, Union
from google import genai
from google.genai import types
from tenacity import Retrying, stop_after_attempt, wait_exponential, retry_if_exception_type
from dataclasses import dataclass

from src.utils.pipeline_utils import read_prompt_template, safe_format
from src.utils.json_utils import extract_json_from_text
from src.utils.logger_utils import setup_logger

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
        client: The high-level Gemini GenAI client.
        api_timeout: HTTP timeout limit in seconds.
    """
    
    def __init__(
        self, 
        config: AgentConfig,
        ai_client: genai.Client, 
        api_timeout: int,
        retry_count: int,
        retry_multiplier: float,
        retry_min: int,
        retry_max: int
    ):
        """Initializes the agent with core AI configuration and dependencies.
        
        Args:
            config: Type-safe AgentConfig object.
            ai_client: The shared genai.Client instance.
            api_timeout: Global timeout for neural inference.
            retry_count: Number of retry attempts on transient failure.
            retry_multiplier: Exponential backoff multiplier.
            retry_min: Minimum backoff time (seconds).
            retry_max: Maximum backoff time (seconds).
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
            return safe_format(template, **context)
        except Exception as e:
            logger.error(f"BaseAgent: Failed to prepare prompt from {template_path}: {e}")
            raise

    def _execute_ai_cycle(
        self, 
        payload: Union[str, List[Any]], 
        temperature: Optional[float] = None,
        agent_name: str = "Agent",
        cached_content: Optional[str] = None,
        tools: Optional[List[Any]] = None,
        system_instruction: Optional[str] = None
    ) -> Dict[str, Any]:
        """Orchestrates an autonomous iterative cycle for tool-use and inference.
        
        This logic implements the core 'Reasoning Loop', handling multi-turn 
        handshaking between the Gemini model and local Python tool logic.
        
        Args:
            payload: Initial prompt or multimodal content sequence.
            temperature: Model creativity override. Defaults to config value.
            agent_name: Logical identity for tracking and forensic logging.
            cached_content: ID of the active context cache resource.
            tools: List of function schemas available for dispatch.
            system_instruction: Shared intelligence prompt to bypass caching limits.
            
        Returns:
            A forensic dictionary containing either the parsed JSON output 
            or a structured error trace.
        """
        try:
            temp = temperature if temperature is not None else self.temperature
            contents = payload if isinstance(payload, list) else [payload]
            iteration = 0
            
            while iteration < self.max_tool_iterations:
                iteration += 1
                
                # Standardized retry strategy with exponential backoff
                retryer = Retrying(
                    stop=stop_after_attempt(self.retry_count),
                    wait=wait_exponential(
                        multiplier=self.retry_multiplier, 
                        min=self.retry_min, 
                        max=self.retry_max
                    ),
                    retry=retry_if_exception_type(Exception)
                )
                
                # Resolve Generation Configuration
                if cached_content:
                    # Note: Gemini rule - Tools/Instructions must be in cache, not in config.
                    gen_config = {
                        "temperature": temp,
                        "http_options": {"timeout": self.api_timeout * 1000},
                        "cached_content": cached_content,
                        "system_instruction": None,
                        "tools": None
                    }
                else:
                    gen_config = {
                        "temperature": temp,
                        "http_options": {"timeout": self.api_timeout * 1000},
                        "tools": tools
                    }
                    if system_instruction is not None:
                        gen_config["system_instruction"] = system_instruction
                        
                    if not tools:
                        # Fallback to direct JSON mode if no tools are allocated.
                        gen_config["response_mime_type"] = "application/json"

                response = retryer(
                    self.client.models.generate_content,
                    model=self.model,
                    contents=contents,
                    config=gen_config
                )
                
                # Token Forensics
                if response and response.usage_metadata:
                    m = response.usage_metadata
                    logger.info(
                        f"[{agent_name}] Usage: T={m.total_token_count} | "
                        f"P={m.prompt_token_count} | "
                        f"C={m.candidates_token_count} | "
                        f"Cache={m.cached_content_token_count or 0}"
                    )

                if not response or not response.candidates:
                    logger.error(f"BaseAgent: {agent_name} received NO_RESPONSE.")
                    return {"error": "NO_RESPONSE", "agent": agent_name}

                # Evaluate for Tool Dispatch (Function Calls)
                content = response.candidates[0].content
                parts = getattr(content, 'parts', []) or []
                tool_calls = [p.function_call for p in parts if p.function_call]
                
                if not tool_calls:
                    # Termination Condition: No further tools needed.
                    try:
                        # [v6.27] Simple Silence: Manually extract text to bypass SDK warnings for non-text parts
                        text = "".join([p.text for p in parts if hasattr(p, 'text') and p.text])
                        
                        if not text or not text.strip():
                            logger.error(f"BaseAgent: {agent_name} returned empty text.")
                            return {"error": "EMPTY_MODEL_RESPONSE", "agent": agent_name}
                    except Exception as e:
                        logger.error(f"BaseAgent: Text extraction failure for {agent_name}: {e}")
                        return {"error": "TEXT_FAILURE", "details": str(e), "agent": agent_name}
                        
                    return self._parse_and_validate_response(text, agent_name)
                
                # Tool Execution Cycle
                logger.info(f"{agent_name}: Found {len(tool_calls)} function calls. Executing...")
                contents.append(response.candidates[0].content) 
                
                response_parts = []
                for fc in tool_calls:
                    result = self._dispatch_tool_call(fc)
                    response_parts.append(
                        types.Part.from_function_response(
                            name=fc.name,
                            response={'result': result}
                        )
                    )
                
                contents.append(types.Content(parts=response_parts, role='user'))

            logger.error(f"{agent_name}: Iteration safety floor reached ({self.max_tool_iterations}).")
            return {"error": "MAX_ITERATIONS", "agent": agent_name}

        except Exception as e:
            # Handle SDK or Connectivity errors
            actual_error = e
            from tenacity import RetryError
            if isinstance(e, RetryError) and e.last_attempt and e.last_attempt.failed:
                actual_error = e.last_attempt.exception()

            err_msg = str(actual_error)
            if hasattr(actual_error, 'response') and hasattr(actual_error.response, 'text'):
                err_msg = f"{err_msg} | Body: {actual_error.response.text}"
            
            logger.error(f"{agent_name} Inference Failure: {err_msg}")
            return {
                "error": f"{agent_name.upper()}_FAILURE", 
                "details": err_msg, 
                "agent": agent_name
            }

    def _parse_and_validate_response(self, text: str, agent_name: str) -> Dict[str, Any]:
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
            return {"error": "MALFORMED_JSON", "raw": text, "agent": agent_name}
        return parsed

    def _dispatch_tool_call(self, fc: types.FunctionCall) -> Any:
        """Dynamically dispatches a tool-call to the local agent instance.
        
        Args:
            fc: Function call specification.
            
        Returns:
            The execution result or error string.
        """
        name = fc.name
        args = fc.args or {}
        
        try:
            if hasattr(self, name):
                method = getattr(self, name)
                logger.info(f"BaseAgent: Dispatching internal tool '{name}'...")
                return method(**args)
            else:
                logger.error(f"BaseAgent: Tool '{name}' is not integrated in {self.__name__}.")
                return f"Error: Tool '{name}' missing."
        except Exception as e:
            logger.error(f"BaseAgent: Tool '{name}' fatal error: {e}")
            return f"Tool Error: {str(e)}"
