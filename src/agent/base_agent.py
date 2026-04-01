import logging
from typing import Dict, Any, List, Optional, Union, Sequence
from google import genai
from google.genai import types
from tenacity import Retrying, stop_after_attempt, wait_exponential, retry_if_exception_type

from src.utils.agent_utils import read_prompt_template, safe_format
from src.utils.json_utils import extract_json_from_text
from src.utils.logger_utils import setup_logger

logger = setup_logger(__name__)

class BaseAgent:
    """
    Abstract Base Class for all AI-driven agents in the forensic trading pipeline.
    
    This class centralizes common AI interaction patterns, including:
    - Gemini client management and file API access.
    - Standardized prompt template loading and context injection.
    - Robust JSON extraction with 'Strict JSON' enforcement.
    - Unified error handling and logging across the agent triad.
    """
    
    def __init__(
        self, 
        model: str, 
        temperature: float, 
        ai_client: genai.Client, 
        max_tool_iterations: int,
        api_timeout: int,
        retry_count: int,
        retry_multiplier: float,
        retry_min: int,
        retry_max: int
    ):
        """
        Initializes the agent with core AI configuration and dependencies.
        """
        self.model = model
        self.temperature = temperature
        self.client = ai_client
        self.max_tool_iterations = max_tool_iterations
        self.api_timeout = api_timeout
        self.retry_count = retry_count
        self.retry_multiplier = retry_multiplier
        self.retry_min = retry_min
        self.retry_max = retry_max

    def _prepare_prompt(self, template_path: str, **context) -> str:
        """
        Reads a requirement template and injects semantic context variables.
        """
        try:
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
        tools: Optional[List[Any]] = None
    ) -> Dict[str, Any]:
        """
        Orchestrates an automatic iterative cycle for tool usage and response generation.
        """
        try:
            temp = temperature if temperature is not None else self.temperature
            contents = payload if isinstance(payload, list) else [payload]
            iteration = 0
            
            while iteration < self.max_tool_iterations:
                iteration += 1
                
                # Use dynamic retry strategy based on global_config.yaml
                retryer = Retrying(
                    stop=stop_after_attempt(self.retry_count),
                    wait=wait_exponential(
                        multiplier=self.retry_multiplier, 
                        min=self.retry_min, 
                        max=self.retry_max
                    ),
                    retry=retry_if_exception_type(Exception)
                )
                
                logger.info(f"{agent_name}: [TURN {iteration}] Requesting model synthesis...")
                response = retryer(
                    self.client.models.generate_content,
                    model=self.model,
                    contents=contents,
                    config=types.GenerateContentConfig(
                        temperature=temp,
                        response_mime_type="application/json",
                        http_options={'timeout': self.api_timeout * 1000},
                        cached_content=cached_content,
                        tools=tools
                    )
                )
                
                # Forensic Token Audit
                if response and response.usage_metadata:
                    m = response.usage_metadata
                    logger.info(
                        f"{agent_name}: Token Audit [Total={m.total_token_count}] "
                        f"(Prompt={m.prompt_token_count}, Candidate={m.candidates_token_count}, "
                        f"Cached={m.cached_content_token_count or 0})"
                    )

                if not response or not response.candidates:
                    return {"error": "NO_RESPONSE", "agent": agent_name}

                # Check for Function Calls (automatic tool loop)
                parts = response.candidates[0].content.parts
                tool_calls = [p.function_call for p in parts if p.function_call]
                
                if not tool_calls:
                    # Final text response obtained
                    return self._parse_and_validate_response(response, agent_name)
                
                # Execute Tools and feed back to the model
                logger.info(f"{agent_name}: Found {len(tool_calls)} tool calls. Dispatching...")
                contents.append(response.candidates[0].content) # Model needs history
                
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
                # Loop continues to next iteration to provide the tool response back to model

            logger.error(f"{agent_name}: Max tool iterations ({self.max_tool_iterations}) reached without final answer.")
            return {"error": "MAX_ITERATIONS_REACHED", "agent": agent_name}

        except Exception as e:
            logger.error(f"{agent_name} AI execution failed: {e}", exc_info=True)
            return {"error": f"{agent_name.upper()}_EXECUTION_FAILURE", "details": str(e), "agent": agent_name}

    def _parse_and_validate_response(self, response: Any, agent_name: str) -> Dict[str, Any]:
        """Extracts and validates structured output from the FINAL response."""
        parsed = extract_json_from_text(response.text)
        if parsed is None:
            logger.error(f"{agent_name}: Failed to parse JSON: {response.text}")
            return {"error": "JSON_PARSE_FAILURE", "raw_response": response.text, "agent": agent_name}
        return parsed

    def _dispatch_tool_call(self, fc: types.FunctionCall) -> Any:
        """
        Dynamically dispatches a function call to a local Python method.
        """
        method_name = fc.name
        args = fc.args or {}
        
        try:
            if hasattr(self, method_name):
                method = getattr(self, method_name)
                logger.info(f"BaseAgent: Executing tool '{method_name}' with args: {args}")
                return method(**args)
            else:
                logger.error(f"BaseAgent: Tool '{method_name}' not found on {self.__class__.__name__}")
                return f"Error: Tool '{method_name}' not found."
        except Exception as e:
            logger.error(f"BaseAgent: Tool '{method_name}' execution failed: {e}")
            return f"Error: {str(e)}"
