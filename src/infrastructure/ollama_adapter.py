import ollama
import logging
from typing import List, Dict, Any, Optional, Union
from dataclasses import dataclass

logger = logging.getLogger(__name__)

@dataclass
class MockUsageMetadata:
    total_token_count: int = 0
    prompt_token_count: int = 0
    candidates_token_count: int = 0
    cached_content_token_count: int = 0

class OllamaResponse:
    """Mocked response object to mirror Gemini SDK structure."""
    def __init__(self, text: str, tool_calls: List[Any] = None, usage: Dict[str, Any] = None):
        self.usage_metadata = MockUsageMetadata(
            total_token_count=usage.get('total_duration', 0) // 1000000, # Mocking tokens with duration for now
            prompt_token_count=0,
            candidates_token_count=0
        )
        
        # Mirroring: response.candidates[0].content.parts[0].text
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

class OllamaAdapter:
    """Bridges Google GenAI SDK calls to a local Ollama instance."""
    
    def __init__(self, base_url: str, default_model: str):
        self.base_url = base_url
        self.default_model = default_model
        # We mirror the client.models.generate_content structure
        self.models = self 

    def generate_content(self, model: str, contents: List[Any], config: Dict[str, Any]) -> OllamaResponse:
        """Translates and executes Gemini-style requests via Ollama."""
        
        # 1. Resolve Model (Ollama uses local names)
        # If model is passed from BaseAgent (like gemini-3-flash), we might want to override with our local default
        target_model = self.default_model if "gemini" in model.lower() else model
        
        # 2. Extract System Instruction
        system_instr = config.get("system_instruction")
        
        # 3. Convert Contents to Messages
        messages = []
        
        # v12.2: Universal JSON Enforcement for smaller local models
        # We inject a high-priority system constraint regardless of provider settings
        json_constraint = "IMPORTANT: You MUST respond ONLY with a valid JSON object. Do NOT include markdown blocks, preamble, or explanations."
        
        if system_instr:
            # Combine existing instruction with our JSON constraint
            enhanced_instr = f"{system_instr}\n\n{json_constraint}"
            messages.append({'role': 'system', 'content': enhanced_instr})
        else:
            messages.append({'role': 'system', 'content': json_constraint})
            
        for content in contents:
            # Handle list of parts (Gemini style) or raw string
            role = 'user' # Default
            text_parts = []
            images = []
            
            if isinstance(content, str):
                text_parts.append(content)
            elif hasattr(content, 'parts'):
                role = 'assistant' if getattr(content, 'role', '') == 'model' else 'user'
                for part in content.parts:
                    if hasattr(part, 'text') and part.text:
                        text_parts.append(part.text)
                    if hasattr(part, 'inline_data') and part.inline_data:
                        # Multimodal support (Gemini Part to Ollama Image)
                        images.append(part.inline_data.data)
            
            msg = {'role': role, 'content': "\n".join(text_parts)}
            if images:
                msg['images'] = images
            messages.append(msg)

        # 4. Handle Tools and Format
        tools = config.get("tools")
        ollama_tools = None
        if tools:
            ollama_tools = tools
            
        # v12.1: Force JSON mode if requested by BaseAgent
        is_json_requested = config.get("response_mime_type") == "application/json"
        
        # 5. Execute via Ollama
        try:
            logger.info(f"OllamaAdapter: Dispatching request to {target_model} (JSON_MODE={is_json_requested})...")
            response = ollama.chat(
                model=target_model,
                messages=messages,
                tools=ollama_tools,
                format='json' if is_json_requested else None,
                options={
                    'temperature': config.get('temperature', 0.1),
                    'num_ctx': 8192
                }
            )
            
            # 6. Re-package Response and Clean JSON
            msg = response.get('message', {})
            text = msg.get('content', "")
            
            # v12.1: Robust cleaning for local models that might still wrap in markdown
            if is_json_requested:
                text = text.strip()
                if text.startswith("```json"):
                    text = text.split("```json", 1)[1].rsplit("```", 1)[0].strip()
                elif text.startswith("```"):
                    text = text.split("```", 1)[1].rsplit("```", 1)[0].strip()
            tool_calls = msg.get('tool_calls') # Ollama format: [{'function': {'name':..., 'arguments':...}}]
            
            # Map Ollama tool calls to Gemini FunctionCall types if necessary
            mapped_tool_calls = None
            if tool_calls:
                from google.genai import types
                mapped_tool_calls = []
                for tc in tool_calls:
                    fn = tc.get('function', {})
                    mapped_tool_calls.append(
                        types.FunctionCall(
                            name=fn.get('name'),
                            args=fn.get('arguments')
                        )
                    )
            
            return OllamaResponse(text, mapped_tool_calls, response)
            
        except Exception as e:
            logger.error(f"OllamaAdapter Failure: {e}")
            raise
