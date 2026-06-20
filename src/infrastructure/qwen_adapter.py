import logging
from typing import List, Dict, Any, Optional, Union
from dataclasses import dataclass

logger = logging.getLogger(__name__)

@dataclass
class MockUsageMetadata:
    """Mocked usage metadata to mirror Gemini SDK structure."""
    total_token_count: int = 0
    prompt_token_count: int = 0
    candidates_token_count: int = 0
    cached_content_token_count: int = 0


class QwenResponse:
    """Mocked response object to mirror Gemini SDK structure for Qwen API."""
    
    def __init__(self, text: str, tool_calls: List[Any] = None, usage: Dict[str, Any] = None):
        # Mirror: response.usage_metadata
        self.usage_metadata = MockUsageMetadata(
            total_token_count=usage.get('total_tokens', 0) if usage else 0,
            prompt_token_count=usage.get('prompt_tokens', 0) if usage else 0,
            candidates_token_count=usage.get('completion_tokens', 0) if usage else 0,
            cached_content_token_count=0
        )
        
        # Mirror: response.candidates[0].content.parts[0].text
        class Part:
            def __init__(self, text_val: str, fc_val: Any = None):
                self.text = text_val
                self.function_call = fc_val

        class Content:
            def __init__(self, text_val: str, fc_list: List[Any] = None):
                self.parts = [Part(text_val, fc) for fc in (fc_list or [None])]

        class Candidate:
            def __init__(self, text_val: str, fc_list: List[Any] = None):
                self.content = Content(text_val, fc_list)

        self.candidates = [Candidate(text, tool_calls)]


class QwenAdapter:
    """Bridges Google GenAI SDK calls to Alibaba Cloud Qwen's OpenAI-compatible API.
    
    Qwen uses an OpenAI-compatible format via DashScope/OpenRouter, so we use the 
    `openai` SDK but wrap responses to match Gemini's structure expected by BaseAgent.
    """
    
    def __init__(self, api_key: str, default_model: str = "qwen-plus", base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"):
        self.api_key = api_key
        self.default_model = default_model
        self.base_url = base_url
        # We mirror the client.models.generate_content structure
        self.models = self
        
        # Initialize OpenAI client lazily
        self._client = None

    @property
    def client(self):
        """Lazy initialization of OpenAI client."""
        if self._client is None:
            try:
                from openai import OpenAI
                self._client = OpenAI(
                    api_key=self.api_key,
                    base_url=self.base_url
                )
                logger.info(f"QwenAdapter: Initialized with model={self.default_model}, base_url={self.base_url}")
            except ImportError:
                raise ImportError("QwenAdapter requires 'openai' package. Install with: pip install openai")
        return self._client

    def generate_content(self, model: str, contents: List[Any], config: Dict[str, Any]) -> QwenResponse:
        """Translates and executes Gemini-style requests via Qwen API."""
        
        # 1. Resolve Model (Use default if gemini model name is passed)
        target_model = self.default_model if "gemini" in model.lower() else model
        
        # 2. Extract System Instruction
        system_instr = config.get("system_instruction")
        
        # 3. Convert Contents to Messages
        messages = []
        
        # v12.2: Universal JSON Enforcement
        json_constraint = "IMPORTANT: You MUST respond ONLY with a valid JSON object. Do NOT include markdown blocks, preamble, or explanations."
        
        if system_instr:
            enhanced_instr = f"{system_instr}\n\n{json_constraint}"
            messages.append({'role': 'system', 'content': enhanced_instr})
        else:
            messages.append({'role': 'system', 'content': json_constraint})
            
        for content in contents:
            role = 'user'
            text_parts = []
            
            if isinstance(content, str):
                text_parts.append(content)
            elif hasattr(content, 'parts'):
                role = 'assistant' if getattr(content, 'role', '') == 'model' else 'user'
                for part in content.parts:
                    if hasattr(part, 'text') and part.text:
                        text_parts.append(part.text)
                    # Note: Qwen VL models support images, but standard models don't
                    if hasattr(part, 'inline_data'):
                        logger.warning("QwenAdapter: Multimodal image parts detected. Use qwen-vl-max for image support.")
            
            msg = {'role': role, 'content': "\n".join(text_parts)}
            messages.append(msg)

        # 4. Handle Tools and Format
        tools = config.get("tools")
        qwen_tools = None
        if tools:
            # Convert Gemini tool format to OpenAI function calling format
            qwen_tools = self._convert_tools_to_openai_format(tools)
            
        # v12.1: Force JSON mode if requested
        is_json_requested = config.get("response_mime_type") == "application/json"
        
        # 5. Execute via OpenAI SDK (Qwen compatible)
        try:
            logger.info(f"QwenAdapter: Dispatching request to {target_model} (JSON_MODE={is_json_requested})...")
            
            # Prepare API call parameters
            api_params = {
                'model': target_model,
                'messages': messages,
                'temperature': config.get('temperature', 0.1),
            }
            
            # Add tools if available
            if qwen_tools:
                api_params['tools'] = qwen_tools
                api_params['tool_choice'] = 'auto'
            
            # Add JSON mode enforcement
            if is_json_requested:
                api_params['response_format'] = {"type": "json_object"}
            
            response = self.client.chat.completions.create(**api_params)
            
            # 6. Re-package Response and Clean JSON
            choice = response.choices[0]
            message = choice.message
            text = message.content or ""
            
            # v12.1: Robust cleaning for models that might still wrap in markdown
            if is_json_requested:
                text = text.strip()
                if text.startswith("```json"):
                    text = text.split("```json", 1)[1].rsplit("```", 1)[0].strip()
                elif text.startswith("```"):
                    text = text.split("```", 1)[1].rsplit("```", 1)[0].strip()
            
            # Handle tool calls
            tool_calls = None
            if message.tool_calls:
                from google.genai import types
                tool_calls = []
                for tc in message.tool_calls:
                    import json
                    try:
                        args = json.loads(tc.function.arguments) if tc.function.arguments else {}
                    except json.JSONDecodeError:
                        args = {}
                    
                    tool_calls.append(
                        types.FunctionCall(
                            name=tc.function.name,
                            args=args
                        )
                    )
            
            # Extract usage metadata
            usage = {
                'total_tokens': response.usage.total_tokens if response.usage else 0,
                'prompt_tokens': response.usage.prompt_tokens if response.usage else 0,
                'completion_tokens': response.usage.completion_tokens if response.usage else 0,
            }
            
            return QwenResponse(text, tool_calls, usage)
            
        except Exception as e:
            logger.error(f"QwenAdapter Failure: {e}")
            raise

    def _convert_tools_to_openai_format(self, gemini_tools: List[Any]) -> List[Dict[str, Any]]:
        """Converts Gemini Tool declarations to OpenAI function calling format."""
        openai_tools = []
        
        for tool in gemini_tools:
            if hasattr(tool, 'function_declarations'):
                for func_decl in tool.function_declarations:
                    openai_tool = {
                        'type': 'function',
                        'function': {
                            'name': func_decl.name,
                            'description': func_decl.description or '',
                            'parameters': {
                                'type': 'object',
                                'properties': {},
                                'required': []
                            }
                        }
                    }
                    
                    # Convert parameter schema
                    if hasattr(func_decl, 'parameters') and func_decl.parameters:
                        params = func_decl.parameters
                        if hasattr(params, 'properties'):
                            for prop_name, prop_schema in params.properties.items():
                                openai_tool['function']['parameters']['properties'][prop_name] = {
                                    'type': self._convert_gemini_type_to_openai(getattr(prop_schema, 'type', 'string')),
                                    'description': getattr(prop_schema, 'description', '')
                                }
                        
                        if hasattr(params, 'required') and params.required:
                            openai_tool['function']['parameters']['required'] = list(params.required)
                    
                    openai_tools.append(openai_tool)
        
        return openai_tools

    def _convert_gemini_type_to_openai(self, gemini_type: str) -> str:
        """Maps Gemini parameter types to OpenAI JSON Schema types."""
        type_map = {
            'STRING': 'string',
            'NUMBER': 'number',
            'INTEGER': 'integer',
            'BOOLEAN': 'boolean',
            'ARRAY': 'array',
            'OBJECT': 'object',
        }
        return type_map.get(gemini_type.upper(), 'string')
