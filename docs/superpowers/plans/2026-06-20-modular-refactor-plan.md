# Modular Refactor + Dashboard Backend — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Decouple AI backend from Gemini SDK, consolidate config dataclasses, decompose orchestrator, add FastAPI dashboard, reorganize tests — while preserving all strategy YAML keys and prompt content.

**Architecture:** Five sequential phases, each producing a working system. Phase 1 (AI decoupling) → Phase 2 (Config) → Phase 3 (Orchestrator) → Phase 4 (Dashboard) → Phase 5 (Tests). Each phase independently testable via `pytest`.

**Tech Stack:** Python 3.11+, google-genai, openai, ollama, fastapi, uvicorn, pytest

## Global Constraints

- `config/strategy_config.yaml` — all keys and values preserved
- `config/global_config.yaml` — all keys preserved (one path update for prompt relocation in Phase 2)
- `src/agent/prompts/*.md` — all content preserved
- `BinaryStarOrchestrator.execute_flow(observation, symbol)` — public signature preserved
- `SessionEngine.execute_cycle(timestamp_str)` — public signature preserved
- All existing CLI entry points continue working

---

## Phase 1: AI Backend Decoupling

### Task 1.1: Create AbstractAIClient interface and response types

**Files:**
- Create: `src/infrastructure/ai_client.py`

**Interfaces:**
- Produces: `AIResponse`, `ToolCall`, `UsageMetadata` dataclasses; `AbstractAIClient` ABC

- [ ] **Step 1: Write the interface file**

```python
"""Abstract AI client interface — decouples agents from LLM SDKs."""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


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

    @property
    def supports_context_cache(self) -> bool:
        return False

    # Cache hooks (Gemini only — no-op by default)
    def create_cache(self, **kwargs) -> str | None:
        return None

    def delete_cache(self, name: str) -> bool:
        return False
```

- [ ] **Step 2: Verify the module imports**

```bash
python -c "from src.infrastructure.ai_client import AbstractAIClient, AIResponse, ToolCall, UsageMetadata; print('OK')"
```
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add src/infrastructure/ai_client.py
git commit -m "feat: add AbstractAIClient interface and response types"
```

---

### Task 1.2: Create GeminiAdapter

**Files:**
- Create: `src/infrastructure/ai/__init__.py`
- Create: `src/infrastructure/ai/gemini_adapter.py`

**Interfaces:**
- Implements: `AbstractAIClient`
- Exposes: `raw_client` property for cache manager

- [ ] **Step 1: Write the adapter**

```python
"""GeminiAdapter — wraps google-genai SDK behind AbstractAIClient."""
import logging
from typing import Any

from google import genai
from google.genai import types

from src.infrastructure.ai_client import (
    AbstractAIClient, AIResponse, ToolCall, UsageMetadata,
)

logger = logging.getLogger(__name__)


class GeminiAdapter(AbstractAIClient):
    """Wraps Google GenAI SDK to match AbstractAIClient."""

    def __init__(self, api_key: str):
        self._client = genai.Client(api_key=api_key)

    @property
    def raw_client(self) -> genai.Client:
        """Expose underlying SDK client for cache operations."""
        return self._client

    @property
    def supports_context_cache(self) -> bool:
        return True

    def generate_content(
        self, model: str, contents: list[Any], *,
        system_instruction: str | None = None,
        tools: list[Any] | None = None,
        temperature: float = 0.5,
        response_json: bool = False,
        http_timeout: int | None = None,
    ) -> AIResponse:
        timeout_ms = (http_timeout or 240) * 1000

        gen_config: dict[str, Any] = {
            "temperature": temperature,
            "http_options": {"timeout": timeout_ms},
        }
        if tools:
            gen_config["tools"] = tools
        elif response_json:
            gen_config["response_mime_type"] = "application/json"
        if system_instruction is not None:
            gen_config["system_instruction"] = system_instruction

        gemini_contents = self._to_gemini_contents(contents)
        response = self._client.models.generate_content(
            model=model, contents=gemini_contents, config=gen_config,
        )
        return self._to_ai_response(response)

    def _to_gemini_contents(self, contents: list[Any]) -> list[types.Content]:
        result = []
        for item in contents:
            if isinstance(item, str):
                result.append(types.Content(
                    parts=[types.Part.from_text(text=item)], role="user"))
            elif isinstance(item, dict):
                role = "user" if item.get("role") != "model" else "model"
                if "text" in item:
                    result.append(types.Content(
                        parts=[types.Part.from_text(text=item["text"])], role=role))
                elif "tool_responses" in item:
                    parts = [
                        types.Part.from_function_response(
                            name=tr["name"], response={"result": tr["result"]})
                        for tr in item["tool_responses"]
                    ]
                    result.append(types.Content(parts=parts, role="user"))
                elif "tool_calls" in item:
                    parts = []
                    for tc in item["tool_calls"]:
                        parts.append(types.Part.from_function_call(
                            name=tc["name"], args=tc["args"]))
                    result.append(types.Content(parts=parts, role="model"))
        return result

    def _to_ai_response(self, response) -> AIResponse:
        if not response or not response.candidates:
            return AIResponse(text="")
        content = response.candidates[0].content
        parts = getattr(content, "parts", []) or []
        text = "".join(p.text for p in parts if hasattr(p, "text") and p.text)
        tool_calls = [
            ToolCall(name=fc.name, args=dict(fc.args or {}))
            for p in parts if (fc := getattr(p, "function_call", None))
        ] or None
        usage = None
        if response.usage_metadata:
            m = response.usage_metadata
            usage = UsageMetadata(
                total_token_count=m.total_token_count,
                prompt_token_count=m.prompt_token_count,
                candidates_token_count=m.candidates_token_count,
                cached_content_token_count=m.cached_content_token_count or 0,
            )
        return AIResponse(text=text, tool_calls=tool_calls, usage=usage)

    def create_cache(self, **kwargs) -> str | None:
        cache = self._client.caches.create(**kwargs)
        return cache.name

    def delete_cache(self, name: str) -> bool:
        try:
            self._client.caches.delete(name=name)
            return True
        except Exception:
            return False
```

- [ ] **Step 2: Write the ai package init**

```python
# src/infrastructure/ai/__init__.py
from src.infrastructure.ai.gemini_adapter import GeminiAdapter

__all__ = ["GeminiAdapter"]
```

- [ ] **Step 3: Verify**

```bash
python -c "from src.infrastructure.ai.gemini_adapter import GeminiAdapter; print('OK')"
```

- [ ] **Step 4: Commit**

```bash
git add src/infrastructure/ai/__init__.py src/infrastructure/ai/gemini_adapter.py
git commit -m "feat: add GeminiAdapter implementing AbstractAIClient"
```

---

### Task 1.3: Create shared OpenAI-format helpers

**Files:**
- Create: `src/infrastructure/ai/_openai_helpers.py`

These helpers are used by both DeepSeekAdapter and QwenAdapter (both speak OpenAI-compatible format).

- [ ] **Step 1: Write the helpers**

```python
"""Shared helpers for OpenAI-compatible adapters (DeepSeek, Qwen)."""
import json
from typing import Any

JSON_HINT = (
    "IMPORTANT: You MUST respond ONLY with a valid JSON object. "
    "Do NOT include markdown blocks, preamble, or explanations."
)


def build_messages(
    system_instruction: str | None, contents: list[Any]
) -> list[dict]:
    system_content = (
        f"{system_instruction}\n\n{JSON_HINT}"
        if system_instruction else JSON_HINT
    )
    messages: list[dict] = [{"role": "system", "content": system_content}]
    for item in contents:
        if isinstance(item, str):
            messages.append({"role": "user", "content": item})
        elif isinstance(item, dict):
            role = item.get("role", "user")
            if "text" in item:
                messages.append({"role": role, "content": item["text"]})
            elif "tool_responses" in item:
                for tr in item["tool_responses"]:
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tr["id"],
                        "content": json.dumps(tr.get("result", {})),
                    })
            elif "tool_calls" in item:
                tcs = [{
                    "id": tc["id"], "type": "function",
                    "function": {"name": tc["name"], "arguments": json.dumps(tc["args"])},
                } for tc in item["tool_calls"]]
                messages.append({"role": "assistant", "content": None, "tool_calls": tcs})
    return messages


def convert_tools(tools: list[Any]) -> list[dict]:
    result = []
    for tool in tools:
        if hasattr(tool, "function_declarations"):
            for fd in tool.function_declarations:
                props, required = {}, []
                if hasattr(fd, "parameters") and fd.parameters:
                    for pn, ps in getattr(fd.parameters, "properties", {}).items():
                        props[pn] = {
                            "type": getattr(ps, "type", "string").lower(),
                            "description": getattr(ps, "description", ""),
                        }
                    required = list(getattr(fd.parameters, "required", []) or [])
                result.append({
                    "type": "function",
                    "function": {
                        "name": fd.name, "description": fd.description or "",
                        "parameters": {"type": "object", "properties": props, "required": required},
                    },
                })
    return result


def clean_json_text(raw_text: str) -> str:
    text = raw_text.strip()
    if text.startswith("```json"):
        text = text.split("```json", 1)[1].rsplit("```", 1)[0].strip()
    elif text.startswith("```"):
        text = text.split("```", 1)[1].rsplit("```", 1)[0].strip()
    return text
```

- [ ] **Step 2: Verify**

```bash
python -c "from src.infrastructure.ai._openai_helpers import build_messages, convert_tools; print('OK')"
```

- [ ] **Step 3: Commit**

```bash
git add src/infrastructure/ai/_openai_helpers.py
git commit -m "feat: add shared OpenAI-format message/tool helpers"
```

---

### Task 1.4: Refactor DeepSeekAdapter

**Files:**
- Create: `src/infrastructure/ai/deepseek_adapter.py`

- [ ] **Step 1: Write the adapter**

```python
"""DeepSeekAdapter — OpenAI-compatible adapter implementing AbstractAIClient."""
import json
import logging
from typing import Any

from src.infrastructure.ai_client import (
    AbstractAIClient, AIResponse, ToolCall, UsageMetadata,
)
from src.infrastructure.ai._openai_helpers import (
    build_messages, convert_tools, clean_json_text,
)

logger = logging.getLogger(__name__)


class DeepSeekAdapter(AbstractAIClient):
    """Talks to DeepSeek API natively — no Gemini mocks."""

    def __init__(self, api_key: str, default_model: str = "deepseek-v4-flash",
                 base_url: str = "https://api.deepseek.com"):
        self.api_key = api_key
        self.default_model = default_model
        self.base_url = base_url
        self._client = None

    @property
    def supports_context_cache(self) -> bool:
        return False

    def _get_client(self):
        if self._client is None:
            from openai import OpenAI
            self._client = OpenAI(api_key=self.api_key, base_url=self.base_url)
        return self._client

    def generate_content(
        self, model: str, contents: list[Any], *,
        system_instruction: str | None = None,
        tools: list[Any] | None = None,
        temperature: float = 0.5,
        response_json: bool = False,
        http_timeout: int | None = None,
    ) -> AIResponse:
        target_model = self.default_model if "gemini" in model.lower() else model
        messages = build_messages(system_instruction, contents)
        openai_tools = convert_tools(tools) if tools else None

        api_params: dict[str, Any] = {
            "model": target_model, "messages": messages,
            "temperature": temperature,
        }
        if openai_tools:
            api_params["tools"] = openai_tools
            api_params["tool_choice"] = "auto"
        if response_json:
            api_params["response_format"] = {"type": "json_object"}

        logger.info("DeepSeekAdapter: → %s", target_model)
        response = self._get_client().chat.completions.create(**api_params)
        return self._parse(response, response_json)

    def _parse(self, response, is_json: bool) -> AIResponse:
        msg = response.choices[0].message
        text = clean_json_text(msg.content or "") if is_json else (msg.content or "")
        tool_calls = None
        if msg.tool_calls:
            tool_calls = []
            for tc in msg.tool_calls:
                try:
                    args = json.loads(tc.function.arguments) if tc.function.arguments else {}
                except json.JSONDecodeError:
                    args = {}
                tool_calls.append(ToolCall(name=tc.function.name, args=args))
        usage = None
        if response.usage:
            usage = UsageMetadata(
                total_token_count=response.usage.total_tokens or 0,
                prompt_token_count=response.usage.prompt_tokens or 0,
                candidates_token_count=response.usage.completion_tokens or 0,
            )
        return AIResponse(text=text, tool_calls=tool_calls, usage=usage)
```

- [ ] **Step 2: Verify**

```bash
python -c "from src.infrastructure.ai.deepseek_adapter import DeepSeekAdapter; print('OK')"
```

- [ ] **Step 3: Commit**

```bash
git add src/infrastructure/ai/deepseek_adapter.py
git commit -m "refactor: DeepSeekAdapter implements AbstractAIClient"
```

---

### Task 1.5: Refactor QwenAdapter

**Files:**
- Create: `src/infrastructure/ai/qwen_adapter.py`

Same pattern as DeepSeekAdapter — uses shared `_openai_helpers`. Identical structure, just different default model/URL.

- [ ] **Step 1: Write the adapter**

```python
"""QwenAdapter — Alibaba Qwen via OpenAI-compatible API."""
import json
import logging
from typing import Any

from src.infrastructure.ai_client import (
    AbstractAIClient, AIResponse, ToolCall, UsageMetadata,
)
from src.infrastructure.ai._openai_helpers import (
    build_messages, convert_tools, clean_json_text,
)

logger = logging.getLogger(__name__)


class QwenAdapter(AbstractAIClient):
    def __init__(self, api_key: str, default_model: str = "qwen-plus",
                 base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"):
        self.api_key = api_key
        self.default_model = default_model
        self.base_url = base_url
        self._client = None

    @property
    def supports_context_cache(self) -> bool:
        return False

    def _get_client(self):
        if self._client is None:
            from openai import OpenAI
            self._client = OpenAI(api_key=self.api_key, base_url=self.base_url)
        return self._client

    def generate_content(
        self, model: str, contents: list[Any], *,
        system_instruction: str | None = None,
        tools: list[Any] | None = None,
        temperature: float = 0.5,
        response_json: bool = False,
        http_timeout: int | None = None,
    ) -> AIResponse:
        target_model = self.default_model if "gemini" in model.lower() else model
        messages = build_messages(system_instruction, contents)
        openai_tools = convert_tools(tools) if tools else None

        api_params: dict[str, Any] = {
            "model": target_model, "messages": messages,
            "temperature": temperature,
        }
        if openai_tools:
            api_params["tools"] = openai_tools
            api_params["tool_choice"] = "auto"
        if response_json:
            api_params["response_format"] = {"type": "json_object"}

        logger.info("QwenAdapter: → %s", target_model)
        response = self._get_client().chat.completions.create(**api_params)
        return self._parse(response, response_json)

    def _parse(self, response, is_json: bool) -> AIResponse:
        msg = response.choices[0].message
        text = clean_json_text(msg.content or "") if is_json else (msg.content or "")
        tool_calls = None
        if msg.tool_calls:
            tool_calls = []
            for tc in msg.tool_calls:
                try:
                    args = json.loads(tc.function.arguments) if tc.function.arguments else {}
                except json.JSONDecodeError:
                    args = {}
                tool_calls.append(ToolCall(name=tc.function.name, args=args))
        usage = None
        if response.usage:
            usage = UsageMetadata(
                total_token_count=response.usage.total_tokens or 0,
                prompt_token_count=response.usage.prompt_tokens or 0,
                candidates_token_count=response.usage.completion_tokens or 0,
            )
        return AIResponse(text=text, tool_calls=tool_calls, usage=usage)
```

- [ ] **Step 2: Verify then commit**

```bash
python -c "from src.infrastructure.ai.qwen_adapter import QwenAdapter; print('OK')"
git add src/infrastructure/ai/qwen_adapter.py
git commit -m "refactor: QwenAdapter implements AbstractAIClient"
```

---

### Task 1.6: Refactor OllamaAdapter

**Files:**
- Create: `src/infrastructure/ai/ollama_adapter.py`

- [ ] **Step 1: Write, verify, commit**

```python
"""OllamaAdapter — local Ollama implementing AbstractAIClient."""
import logging
from typing import Any

from src.infrastructure.ai_client import (
    AbstractAIClient, AIResponse, UsageMetadata,
)
from src.infrastructure.ai._openai_helpers import JSON_HINT, clean_json_text

logger = logging.getLogger(__name__)


class OllamaAdapter(AbstractAIClient):
    def __init__(self, base_url: str, default_model: str):
        self.base_url = base_url
        self.default_model = default_model

    @property
    def supports_context_cache(self) -> bool:
        return False

    def generate_content(
        self, model: str, contents: list[Any], *,
        system_instruction: str | None = None,
        tools: list[Any] | None = None,
        temperature: float = 0.5,
        response_json: bool = False,
        http_timeout: int | None = None,
    ) -> AIResponse:
        target_model = self.default_model if "gemini" in model.lower() else model
        system_content = (
            f"{system_instruction}\n\n{JSON_HINT}"
            if system_instruction else JSON_HINT
        )
        messages: list[dict] = [{"role": "system", "content": system_content}]
        for item in contents:
            if isinstance(item, str):
                messages.append({"role": "user", "content": item})
            elif isinstance(item, dict) and "text" in item:
                messages.append({"role": item.get("role", "user"), "content": item["text"]})

        import ollama
        logger.info("OllamaAdapter: → %s", target_model)
        response = ollama.chat(
            model=target_model, messages=messages,
            format="json" if response_json else None,
            options={"temperature": temperature, "num_ctx": 8192},
        )
        msg = response.get("message", {})
        text = clean_json_text(msg.get("content", "")) if response_json else msg.get("content", "")
        return AIResponse(
            text=text,
            usage=UsageMetadata(
                total_token_count=response.get("total_duration", 0) // 1_000_000,
            ),
        )
```

```bash
python -c "from src.infrastructure.ai.ollama_adapter import OllamaAdapter; print('OK')"
git add src/infrastructure/ai/ollama_adapter.py
git commit -m "refactor: OllamaAdapter implements AbstractAIClient"
```

---

### Task 1.7: Update AIFactory to return AbstractAIClient

**Files:**
- Modify: `src/infrastructure/ai_factory.py`

- [ ] **Step 1: Rewrite AIFactory**

Replace all `genai.Client` returns and adapter imports. The new imports come from `src.infrastructure.ai.*` instead of `src.infrastructure.*_adapter`. The factory now always returns `AbstractAIClient`.

Key change: `genai.Client(api_key=api_key)` → `GeminiAdapter(api_key=api_key)`.
All adapter imports change path: `src.infrastructure.deepseek_adapter` → `src.infrastructure.ai.deepseek_adapter`.

```python
"""Factory for AI clients — returns AbstractAIClient implementations."""
import logging
import os
from typing import Any

from src.infrastructure.ai_client import AbstractAIClient
from src.utils.pipeline_utils import load_config

logger = logging.getLogger(__name__)


class AIFactory:
    @staticmethod
    def create_client(
        api_key: str | None = None,
        config_dict: dict[str, Any] | None = None,
    ) -> AbstractAIClient:
        config = config_dict or load_config("config/global_config.yaml")
        llm_cfg = config.get("llm", {})
        provider = llm_cfg.get("active_provider", "gemini").lower()

        if provider == "ollama":
            from src.infrastructure.ai.ollama_adapter import OllamaAdapter
            cfg = llm_cfg.get("ollama", {})
            return OllamaAdapter(
                base_url=cfg.get("base_url"),
                default_model=cfg.get("model"),
            )
        elif provider == "deepseek":
            from src.infrastructure.ai.deepseek_adapter import DeepSeekAdapter
            cfg = llm_cfg.get("deepseek", {})
            key = api_key or os.getenv("DEEPSEEK_API_KEY")
            if not key:
                raise ValueError("DEEPSEEK_API_KEY not found")
            return DeepSeekAdapter(
                api_key=key,
                default_model=cfg.get("model", "deepseek-v4-flash"),
                base_url=cfg.get("base_url", "https://api.deepseek.com"),
            )
        elif provider == "qwen":
            from src.infrastructure.ai.qwen_adapter import QwenAdapter
            cfg = llm_cfg.get("qwen", {})
            key = api_key or os.getenv("QWEN_API_KEY")
            if not key:
                raise ValueError("QWEN_API_KEY not found")
            return QwenAdapter(
                api_key=key,
                default_model=cfg.get("model", "qwen-plus"),
                base_url=cfg.get("base_url", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
            )
        else:  # gemini
            from src.infrastructure.ai.gemini_adapter import GeminiAdapter
            return GeminiAdapter(api_key=api_key)
```

- [ ] **Step 2: Verify import**

```bash
python -c "from src.infrastructure.ai_factory import AIFactory; c = AIFactory.create_client(api_key='test', config_dict={'llm': {'active_provider': 'gemini'}}); print(type(c).__name__)"
```

Expected: `GeminiAdapter`

- [ ] **Step 3: Commit**

```bash
git add src/infrastructure/ai_factory.py
git commit -m "refactor: AIFactory returns AbstractAIClient implementations"
```

---

### Task 1.8: Update BaseAgent to use AbstractAIClient

**Files:**
- Modify: `src/agent/base_agent.py`

This is the critical change. BaseAgent drops all `google.genai`/`google.genai.types` imports and works with `AbstractAIClient` + plain dict contents.

- [ ] **Step 1: Write the refactored `_execute_ai_cycle` method**

Replace the existing method (lines 97-244). The constructor signature changes: `ai_client: genai.Client` → `ai_client: AbstractAIClient`. The import block at the top replaces `from google import genai` + `from google.genai import types` with `from src.infrastructure.ai_client import AbstractAIClient, AIResponse, ToolCall`.

The new `_execute_ai_cycle`:

```python
def _execute_ai_cycle(
    self,
    payload: str | list[Any],
    temperature: float | None = None,
    agent_name: str = "Agent",
    cached_content: str | None = None,
    tools: list[Any] | None = None,
    system_instruction: str | None = None,
) -> dict[str, Any]:
    try:
        temp = temperature if temperature is not None else self.temperature
        contents: list[Any] = payload if isinstance(payload, list) else [payload]
        iteration = 0
        next_tc_id = 0

        while iteration < self.max_tool_iterations:
            iteration += 1

            retryer = Retrying(
                stop=stop_after_attempt(self.retry_count),
                wait=wait_exponential(
                    multiplier=self.retry_multiplier,
                    min=self.retry_min, max=self.retry_max,
                ),
                retry=retry_if_exception_type(Exception),
            )

            use_json_mode = not tools and not cached_content

            if self.congestion_controller:
                self.congestion_controller.pace(agent_name=agent_name)

            response: AIResponse = retryer(
                self.client.generate_content,
                model=self.model,
                contents=contents,
                system_instruction=system_instruction if not cached_content else None,
                tools=tools if not cached_content else None,
                temperature=temp,
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

            if not response.text and not response.tool_calls:
                logger.error("BaseAgent: %s returned empty response.", agent_name)
                return {"error": "EMPTY_MODEL_RESPONSE", "agent": agent_name}

            # No tool calls → termination
            if not response.tool_calls:
                if not response.text.strip():
                    logger.error("BaseAgent: %s returned empty text.", agent_name)
                    return {"error": "EMPTY_MODEL_RESPONSE", "agent": agent_name}
                return self._parse_and_validate_response(response.text, agent_name)

            # Tool execution cycle
            tc_entries = []
            for tc in response.tool_calls:
                tc_entries.append({
                    "id": f"call_{next_tc_id}", "name": tc.name, "args": tc.args,
                })
                next_tc_id += 1
            contents.append({"role": "model", "tool_calls": tc_entries})

            tool_responses = []
            for entry, tc in zip(tc_entries, response.tool_calls):
                result = self._dispatch_tool_call(tc)
                tool_responses.append({
                    "id": entry["id"], "name": tc.name, "result": result,
                })
            contents.append({"role": "user", "tool_responses": tool_responses})

        logger.error("%s: max iterations (%d).", agent_name, self.max_tool_iterations)
        return {"error": "MAX_ITERATIONS", "agent": agent_name}

    except Exception as e:
        from tenacity import RetryError

        actual_error = e
        if isinstance(e, RetryError) and e.last_attempt and e.last_attempt.failed:
            actual_error = e.last_attempt.exception()
        err_msg = str(actual_error)
        if hasattr(actual_error, "response") and hasattr(actual_error.response, "text"):
            err_msg = f"{err_msg} | Body: {actual_error.response.text}"
        logger.error("%s Inference Failure: %s", agent_name, err_msg)
        return {
            "error": f"{agent_name.upper()}_FAILURE",
            "details": err_msg, "agent": agent_name,
        }
```

And update `_dispatch_tool_call` signature:

```python
def _dispatch_tool_call(self, tc: ToolCall) -> Any:
    name = tc.name
    args = tc.args or {}
    try:
        if hasattr(self, name):
            method = getattr(self, name)
            logger.info("BaseAgent: Dispatching tool '%s'...", name)
            return method(**args)
        else:
            logger.error("BaseAgent: Tool '%s' not found.", name)
            return f"Error: Tool '{name}' missing."
    except Exception as e:
        logger.error("BaseAgent: Tool '%s' error: %s", name, e)
        return f"Tool Error: {str(e)}"
```

Update imports at top: remove `from google import genai` and `from google.genai import types`. Add `from src.infrastructure.ai_client import AbstractAIClient, AIResponse, ToolCall, UsageMetadata`.

Update constructor: `ai_client: genai.Client` → `ai_client: AbstractAIClient`.

- [ ] **Step 2: Run existing tests to check for regressions**

```bash
python -m pytest tests/ -x -v --tb=short 2>&1 | head -60
```

Fix any import errors or type mismatches. Common issues:
- Other files importing `genai.Client` and passing to BaseAgent constructor — update to pass AbstractAIClient
- `session_agent.py` and `critic_agent.py` still import `from google import genai` for type hints — update to `AbstractAIClient`

- [ ] **Step 3: Commit**

```bash
git add src/agent/base_agent.py
git commit -m "refactor: BaseAgent uses AbstractAIClient, drops Gemini SDK dependency"
```

---

### Task 1.9: Update SessionAgent and CriticAgent constructors

**Files:**
- Modify: `src/agent/session_agent.py` (constructor type hint only)
- Modify: `src/agent/critic_agent.py` (constructor type hint only)

- [ ] **Step 1: Change import and type hint**

In `session_agent.py`:
- Remove `from google import genai`
- Change `ai_client: genai.Client` → `ai_client: AbstractAIClient` in `__init__`
- Add import: `from src.infrastructure.ai_client import AbstractAIClient`

Same for `critic_agent.py`.

- [ ] **Step 2: Verify imports**

```bash
python -c "from src.agent.session_agent import SessionAgent; from src.agent.critic_agent import CriticAgent; print('OK')"
```

- [ ] **Step 3: Commit**

```bash
git add src/agent/session_agent.py src/agent/critic_agent.py
git commit -m "refactor: SessionAgent and CriticAgent use AbstractAIClient type hints"
```

---

### Task 1.10: Update BinaryStarOrchestrator for adapter changes

**Files:**
- Modify: `src/agent/binary_star_orchestrator.py`

Key changes:
- The orchestrator's `self.client` is now an `AbstractAIClient` (GeminiAdapter), not `genai.Client`
- `_extract_visual_parts()` still uses `types.Part` — this is OK since visual parts are Gemini-specific
- `create_market_cache()` call on cache_manager — needs to use `GeminiAdapter.raw_client` for cache operations
- `types.Tool()` usage for tool declarations — keep, Gemini-specific
- The orchestrator creates tool declarations as raw dicts (lines 308-336), then wraps in `types.Tool(function_declarations=...)` — keep as-is since this flows to Gemini cache API

- [ ] **Step 1: Update cache_manager initialization**

The `GeminiCacheManager` currently takes `client: genai.Client`. Change it to accept `GeminiAdapter` and use `.raw_client` internally.

In `cache_manager.py`:
```python
from src.infrastructure.ai.gemini_adapter import GeminiAdapter

class GeminiCacheManager:
    def __init__(self, adapter: GeminiAdapter, congestion_controller=None):
        self._adapter = adapter
        self.client = adapter.raw_client  # underlying genai.Client
        ...
```

In `binary_star_orchestrator.py`, pass `self.client` (now a GeminiAdapter) directly:
```python
self.cache_manager = GeminiCacheManager(
    adapter=self.client,  # GeminiAdapter
    congestion_controller=self.congestion_controller,
)
```

- [ ] **Step 2: Update cache creation in execute_flow**

The `create_market_cache` call passes `types.Tool(...)` and `types.Part` — these remain as-is since `GeminiCacheManager` still uses `genai.Client` internally.

- [ ] **Step 3: Run tests and commit**

```bash
python -m pytest tests/ -x -v --tb=short 2>&1 | tail -20
git add src/agent/binary_star_orchestrator.py src/infrastructure/gemini/cache_manager.py
git commit -m "refactor: orchestrator and cache manager work with GeminiAdapter"
```

---

### Task 1.11: Remove old adapter files, update remaining imports

**Files:**
- Delete: `src/infrastructure/deepseek_adapter.py`
- Delete: `src/infrastructure/qwen_adapter.py`
- Delete: `src/infrastructure/ollama_adapter.py`
- Update: any file still importing from old paths

- [ ] **Step 1: Find remaining references**

```bash
grep -r "deepseek_adapter\|qwen_adapter\|ollama_adapter" src/ tests/ --include="*.py"
```

Expected: only references should be in `ai_factory.py` (already updated) or old files to delete.

- [ ] **Step 2: Delete old files and verify**

```bash
rm src/infrastructure/deepseek_adapter.py src/infrastructure/qwen_adapter.py src/infrastructure/ollama_adapter.py
python -m pytest tests/ -x -v --tb=short 2>&1 | tail -20
```

- [ ] **Step 3: Commit**

```bash
git add -A
git commit -m "chore: remove old adapter files, Phase 1 complete"
```

---

## Phase 2: Config Consolidation

### Task 2.1: Create sub-config dataclasses

**Files:**
- Create: `src/config/__init__.py`
- Create: `src/config/sub_configs.py`

- [ ] **Step 1: Write sub-config dataclasses**

```python
"""Logical sub-config groupings extracted from monolithic config dataclasses."""
from dataclasses import dataclass


@dataclass(frozen=True)
class RegimeConfig:
    """Market regime thresholds."""
    trend_intensity_threshold: float
    trend_intensity_strong: float
    trend_intensity_min_expansion: float
    volatility_baseline_ratio: float
    volatility_extreme_ratio: float
    volume_surge_vs_ma_ratio: float
    long_short_imbalance_ratio: float
    short_heavy_imbalance_ratio: float
    squeeze_threshold: float
    squeeze_audit_threshold: float
    ranging_width_atr: float
    min_volume_participation_ratio: float
    vacuum_risk_score: float
    wick_skew_exhaustion: float
    cvd_intensity_threshold: float
    cvd_intensity_extreme: float
    funding_extreme_threshold: float
    breakout_frontrun_atr: float


@dataclass(frozen=True)
class TemporalConfig:
    """Time dilation and velocity parameters."""
    min_trade_velocity: float
    temporal_dilation_dead_water: float
    temporal_dilation_highway: float
    temporal_dilation_climax: float
    temporal_dilation_standard: float
    temporal_weight_dead_water: float
    temporal_weight_highway: float
    temporal_weight_climax: float
    temporal_weight_standard: float


@dataclass(frozen=True)
class RiskConfig:
    """Risk-reward and structural protection thresholds."""
    min_rr_ranging: float
    min_rr_trending: float
    structural_buffer_atr: float
    stop_loss_buffer_min: float
    poc_gravity_atr_distance: float
    max_entry_distance_atr: float
    chaos_rr_discount: float
    structural_proximity_threshold: float
    max_holding_hours: float


@dataclass(frozen=True)
class AuditConfig:
    """Forensic audit thresholds."""
    mae_threshold_pinpoint: float
    mae_threshold_standard: float
    mae_threshold_luck: float
    missed_opportunity_atr_threshold: float


@dataclass(frozen=True)
class VisualConfig:
    """Chart rendering parameters."""
    volume_profile_width_ratio: float
    volume_profile_value_area_width: float
    render_dpi: int
    up_color: str
    down_color: str
    bg_color: str
    poc_color: str
    vah_val_color: str
    current_price_color: str
```

- [ ] **Step 2: Commit**

```bash
git add src/config/
git commit -m "feat: add sub-config dataclasses (Regime, Temporal, Risk, Audit, Visual)"
```

---

### Task 2.2: Create config loader that builds sub-configs from YAML

**Files:**
- Create: `src/config/loader.py`

- [ ] **Step 1: Write the loader with `from_yaml` helpers**

Each sub-config gets a `from_yaml` classmethod that reads from the same YAML dict keys as before. This is purely a reorganization — no YAML key changes.

```python
"""Config loaders that build sub-configs from YAML dicts."""
from typing import Any
from src.config.sub_configs import (
    RegimeConfig, TemporalConfig, RiskConfig, AuditConfig, VisualConfig,
)


def _f(d: dict, key: str) -> float:
    return float(d[key])


def _i(d: dict, key: str) -> int:
    return int(d[key])


def _s(d: dict, key: str) -> str:
    return str(d[key])


def load_regime_config(cfg: dict[str, Any]) -> RegimeConfig:
    r = cfg["regime_parameters"]
    return RegimeConfig(
        trend_intensity_threshold=_f(r, "trend_intensity_threshold"),
        trend_intensity_strong=_f(r, "trend_intensity_strong"),
        trend_intensity_min_expansion=_f(r, "trend_intensity_min_expansion"),
        volatility_baseline_ratio=_f(r, "volatility_baseline_ratio"),
        volatility_extreme_ratio=_f(r, "volatility_extreme_ratio"),
        volume_surge_vs_ma_ratio=_f(r, "volume_surge_vs_ma_ratio"),
        long_short_imbalance_ratio=_f(r, "long_short_imbalance_ratio"),
        short_heavy_imbalance_ratio=_f(r, "short_heavy_imbalance_ratio"),
        squeeze_threshold=_f(r, "squeeze_threshold"),
        squeeze_audit_threshold=_f(r, "squeeze_audit_threshold"),
        ranging_width_atr=_f(r, "ranging_width_atr"),
        min_volume_participation_ratio=_f(r, "min_volume_participation_ratio"),
        vacuum_risk_score=_f(r, "vacuum_risk_score"),
        wick_skew_exhaustion=_f(r, "wick_skew_exhaustion"),
        cvd_intensity_threshold=_f(r, "cvd_intensity_threshold"),
        cvd_intensity_extreme=_f(r, "cvd_intensity_extreme"),
        funding_extreme_threshold=_f(r, "funding_extreme_threshold"),
        breakout_frontrun_atr=_f(r, "breakout_frontrun_atr"),
    )


def load_temporal_config(cfg: dict[str, Any]) -> TemporalConfig:
    s = cfg["binary_star"]["session"]
    return TemporalConfig(
        min_trade_velocity=_f(s, "min_trade_velocity"),
        temporal_dilation_dead_water=_f(s, "temporal_dilation_dead_water"),
        temporal_dilation_highway=_f(s, "temporal_dilation_highway"),
        temporal_dilation_climax=_f(s, "temporal_dilation_climax"),
        temporal_dilation_standard=_f(s, "temporal_dilation_standard"),
        temporal_weight_dead_water=_f(s, "temporal_weight_dead_water"),
        temporal_weight_highway=_f(s, "temporal_weight_highway"),
        temporal_weight_climax=_f(s, "temporal_weight_climax"),
        temporal_weight_standard=_f(s, "temporal_weight_standard"),
    )


def load_risk_config(cfg: dict[str, Any]) -> RiskConfig:
    r = cfg["regime_parameters"]
    s = cfg["binary_star"]["session"]
    return RiskConfig(
        min_rr_ranging=_f(r, "min_rr_ranging"),
        min_rr_trending=_f(r, "min_rr_trending"),
        structural_buffer_atr=_f(r, "structural_buffer_atr"),
        stop_loss_buffer_min=_f(s, "stop_loss_buffer_min"),
        poc_gravity_atr_distance=_f(r, "poc_gravity_atr_distance"),
        max_entry_distance_atr=_f(r, "max_entry_distance_atr"),
        chaos_rr_discount=_f(r, "chaos_rr_discount"),
        structural_proximity_threshold=_f(r, "structural_proximity_threshold"),
        max_holding_hours=_f(s, "max_holding_hours"),
    )


def load_audit_config(cfg: dict[str, Any]) -> AuditConfig:
    a = cfg["audit_review"]
    return AuditConfig(
        mae_threshold_pinpoint=_f(a, "mae_threshold_pinpoint"),
        mae_threshold_standard=_f(a, "mae_threshold_standard"),
        mae_threshold_luck=_f(a, "mae_threshold_luck"),
        missed_opportunity_atr_threshold=_f(a, "missed_opportunity_atr_threshold"),
    )


def load_visual_config(cfg: dict[str, Any]) -> VisualConfig:
    v = cfg["visuals"]
    t = cfg["topography_parameters"]
    return VisualConfig(
        volume_profile_width_ratio=_f(v["volume_profile"], "width_ratio"),
        volume_profile_value_area_width=_f(t, "volume_profile_value_area_width"),
        render_dpi=_i(v, "render_dpi"),
        up_color=_s(v, "up_color"),
        down_color=_s(v, "down_color"),
        bg_color=_s(v, "bg_color"),
        poc_color=_s(v, "poc_color"),
        vah_val_color=_s(v, "vah_val_color"),
        current_price_color=_s(v, "current_price_color"),
    )
```

- [ ] **Step 2: Verify loading against actual YAML**

```bash
python -c "
from src.utils.pipeline_utils import load_config
from src.config.loader import load_regime_config, load_temporal_config, load_risk_config
cfg = load_config()
r = load_regime_config(cfg)
print(f'Regime OK: trend_thresh={r.trend_intensity_threshold}')
t = load_temporal_config(cfg)
print(f'Temporal OK: dilation_dead={t.temporal_dilation_dead_water}')
k = load_risk_config(cfg)
print(f'Risk OK: min_rr_trending={k.min_rr_trending}')
"
```
Expected: values matching `strategy_config.yaml`

- [ ] **Step 3: Commit**

```bash
git add src/config/loader.py
git commit -m "feat: add config loaders that build sub-configs from YAML"
```

---

### Task 2.3: Refactor SessionConfig to compose sub-configs

**Files:**
- Modify: `src/agent/session_agent.py`

- [ ] **Step 1: Replace the giant dataclass**

`SessionConfig` drops its 45+ individual fields and instead holds sub-config instances:

```python
@dataclass(frozen=True)
class SessionConfig(AgentConfig):
    """Strategic configuration composed from logical sub-configs."""
    regime: RegimeConfig
    temporal: TemporalConfig
    risk: RiskConfig
    audit: AuditConfig
    visual: VisualConfig
    strategy_intent: str
    macro_interval: str
    micro_interval: str
    instruction_literal: str | None = None

    @classmethod
    def from_dict(cls, cfg: dict[str, Any], instruction_literal: str | None = None) -> "SessionConfig":
        from src.config.loader import (
            load_regime_config, load_temporal_config, load_risk_config,
            load_audit_config, load_visual_config,
        )
        llm_cfg = cfg["llm"]
        provider = llm_cfg.get("active_provider", "gemini").lower()
        provider_cfg = llm_cfg.get(provider, {})
        sampling = cfg["analysis_window"]

        return cls(
            model=str(provider_cfg.get("model")),
            model_temperature=float(provider_cfg.get("session_temperature", 0.5)),
            instruction_path=os.path.join(resolve_project_root(), llm_cfg["binary_star"]["session_role_prompt"]),
            max_tool_iterations=int(cfg["network"]["gemini"]["max_tool_iterations"]),
            regime=load_regime_config(cfg),
            temporal=load_temporal_config(cfg),
            risk=load_risk_config(cfg),
            audit=load_audit_config(cfg),
            visual=load_visual_config(cfg),
            strategy_intent=str(cfg.get("strategy_intent", "")),
            macro_interval=str(sampling["macro_context"]["time_interval"]),
            micro_interval=str(sampling["micro_context"]["time_interval"]),
            instruction_literal=instruction_literal,
        )
```

- [ ] **Step 2: Update all field accesses in SessionAgent**

The `_build_prompt` method accesses `self.config.min_rr_ranging`, `self.config.structural_buffer_atr`, etc. These become `self.config.risk.min_rr_ranging`, `self.config.risk.structural_buffer_atr`, etc.

Prompt variable names stay the same — only the Python attribute path changes.

- [ ] **Step 3: Run tests, fix access paths, commit**

```bash
python -m pytest tests/ -x -v --tb=short 2>&1 | grep -E "PASSED|FAILED|ERROR"
git add src/agent/session_agent.py
git commit -m "refactor: SessionConfig composed from sub-configs"
```

---

### Task 2.4: Refactor CriticConfig to compose sub-configs

**Files:**
- Modify: `src/agent/critic_agent.py`

Same pattern as Task 2.3. `CriticConfig` drops its 48 fields and holds the same sub-configs plus critic-only fields.

- [ ] **Step 1: Rewrite CriticConfig**

```python
@dataclass(frozen=True)
class CriticConfig(AgentConfig):
    regime: RegimeConfig
    temporal: TemporalConfig
    risk: RiskConfig
    audit: AuditConfig
    visual: VisualConfig
    strategy_intent: str
    macro_interval: str
    micro_interval: str
    cvd_micro_lookback_candles: int
    instruction_literal: str | None = None

    @classmethod
    def from_dict(cls, cfg_dict, instruction_literal=None):
        # ... same pattern as SessionConfig.from_dict with sub-config loaders
```

- [ ] **Step 2: Update field accesses in CriticAgent._build_context**

`self.config.long_short_imbalance_ratio` → `self.config.regime.long_short_imbalance_ratio`, etc.

- [ ] **Step 3: Run tests, fix, commit**

---

### Task 2.5: Refactor MarketObserverConfig to use sub-configs

**Files:**
- Modify: `src/analyzer/market_observer.py`

- [ ] **Step 1: Rewrite MarketObserverConfig**

The observer config needs more fields than the agents (it has timeframe configs, volume profile params, liquidation params). Compose it from `RegimeConfig`, `TemporalConfig`, `VisualConfig` plus observer-specific fields.

- [ ] **Step 2: Update field access in MarketObserver, MarketDataLoader, MarketMetricsRefiner**

- [ ] **Step 3: Run tests, fix, commit**

---

### Task 2.6: Update all consumers of config fields across the codebase

**Files:**
- Modify: `src/agent/binary_star_orchestrator.py` — accesses many config fields directly
- Modify: `src/agent/evolver_agent.py` — if it accesses config fields
- Modify: `src/analyzer/audit_assembler.py`, `src/analyzer/audit_controller.py` — if they access config fields

- [ ] **Step 1: Search for all direct config field accesses**

```bash
grep -rn "self\.session_config\." src/ --include="*.py"
grep -rn "self\.critic_config\." src/ --include="*.py"
grep -rn "self\.obs_config\." src/ --include="*.py"
```

- [ ] **Step 2: Update each access to use sub-config paths**

For example in `binary_star_orchestrator.py`:
- `self.session_config.min_trade_velocity` → `self.session_config.temporal.min_trade_velocity`
- `self.critic_config.volatility_baseline_ratio` → `self.critic_config.regime.volatility_baseline_ratio`

- [ ] **Step 3: Run full test suite**

```bash
python -m pytest tests/ -v --tb=short 2>&1 | tail -30
```

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "refactor: update all config field accesses to sub-config paths"
```

---

### Task 2.7: Move prompts to config/prompts/

**Files:**
- Move: `src/agent/prompts/*.md` → `config/prompts/*.md`
- Modify: `config/global_config.yaml` — update 3 paths

- [ ] **Step 1: Move files**

```bash
mkdir -p config/prompts
mv src/agent/prompts/binary_star.md config/prompts/
mv src/agent/prompts/session.md config/prompts/
mv src/agent/prompts/critic.md config/prompts/
mv src/agent/prompts/evolver.md config/prompts/
```

- [ ] **Step 2: Update paths in global_config.yaml**

```yaml
llm:
  binary_star:
    system_instruction: "config/prompts/binary_star.md"
    session_role_prompt: "config/prompts/session.md"
    critic_role_prompt: "config/prompts/critic.md"
  evolver:
    role_prompt: "config/prompts/evolver.md"
```

- [ ] **Step 3: Verify system still finds prompts**

```bash
python -c "
from src.utils.pipeline_utils import read_prompt_template
from src.utils.path_utils import resolve_project_root
import os
path = os.path.join(resolve_project_root(), 'config/prompts/session.md')
print(read_prompt_template(path)[:80])
"
```

- [ ] **Step 4: Commit**

```bash
git add config/prompts/ config/global_config.yaml
git rm src/agent/prompts/binary_star.md src/agent/prompts/session.md src/agent/prompts/critic.md src/agent/prompts/evolver.md
git commit -m "refactor: move prompts to config/prompts/"
```

---

## Phase 3: Orchestrator Decomposition

### Task 3.1: Extract MathFactChecker

**Files:**
- Create: `src/analyzer/math_fact_checker.py`
- Modify: `src/agent/binary_star_orchestrator.py`

- [ ] **Step 1: Move `_assemble_math_fact_check` into new class**

```python
"""MathFactChecker — deterministic trade geometry verification."""
import logging
from typing import Any
from src.utils.math_utils import MathTools
from src.utils.datetime_utils import get_interval_minutes

logger = logging.getLogger(__name__)


class MathFactChecker:
    """Deterministic math verification for AI trade proposals."""

    def __init__(self, math_tools: MathTools, session_config, critic_config,
                 macro_interval: str):
        self.math = math_tools
        self.session_config = session_config
        self.critic_config = critic_config
        self.macro_interval = macro_interval

    def verify(self, plan: dict[str, Any], observation: dict[str, Any]) -> dict[str, Any]:
        """Run full deterministic fact-check against a trade proposal."""
        # ... (moved _assemble_math_fact_check logic here)
```

The method is a pure extraction — logic stays identical, just lives in its own class.

- [ ] **Step 2: Update orchestrator to use the new class**

```python
# In BinaryStarOrchestrator.__init__:
self.math_checker = MathFactChecker(
    math_tools=self.math_tools,
    session_config=self.session_config,
    critic_config=self.critic_config,
    macro_interval=self.macro_interval,
)

# In execute_flow:
math_fact_check = self.math_checker.verify(last_plan, observation)
```

- [ ] **Step 3: Verify with existing tests**

```bash
python -m pytest tests/ -v --tb=short 2>&1 | tail -20
```

- [ ] **Step 4: Commit**

```bash
git add src/analyzer/math_fact_checker.py src/agent/binary_star_orchestrator.py
git commit -m "refactor: extract MathFactChecker from orchestrator"
```

---

### Task 3.2: Extract DebateLoop

**Files:**
- Create: `src/agent/debate_loop.py`
- Modify: `src/agent/binary_star_orchestrator.py`

- [ ] **Step 1: Move debate loop logic into new class**

```python
"""DebateLoop — adversarial debate round management."""
import logging
from typing import Any

logger = logging.getLogger(__name__)


class DebateLoop:
    """Manages the round-by-round adversarial debate between Session and Critic."""

    def __init__(self, session_agent, critic_agent, math_checker,
                 max_rounds: int, cache_resource_name: str | None,
                 tools: list, visual_parts: list, shared_instruction: str,
                 session_config, critic_config):
        self.session_agent = session_agent
        self.critic_agent = critic_agent
        self.math_checker = math_checker
        self.max_rounds = max_rounds
        self.cache_id = cache_resource_name
        self.tools = tools
        self.visual_parts = visual_parts
        self.shared_instruction = shared_instruction
        self.session_config = session_config
        self.critic_config = critic_config

    def run(self, observation: dict, symbol: str) -> dict[str, Any]:
        """Execute the full debate and return final results."""
        # ... moved execute_flow debate portion here
        # Returns: {"final_decision": ..., "debate_history": ..., "early_exit": bool}
```

The `run()` method contains the while-loop from `execute_flow()` (planning → audit → repeat), plus `_compress_debate_history()` and `_evaluate_critic_fast_pass()`.

- [ ] **Step 2: Simplify BinaryStarOrchestrator.execute_flow**

The orchestrator's `execute_flow` becomes:
1. Inject regime benchmarks into observation
2. Set up cache
3. Call `self.debate_loop.run(observation, symbol)`
4. Run final synthesis if needed
5. Sanitize result
6. Package forensic output

~50-60 lines instead of ~280.

- [ ] **Step 3: Verify and commit**

```bash
python -m pytest tests/ -v --tb=short 2>&1 | tail -20
git add src/agent/debate_loop.py src/agent/binary_star_orchestrator.py
git commit -m "refactor: extract DebateLoop from orchestrator"
```

---

## Phase 4: Dashboard Module

### Task 4.1: Add FastAPI dependency and create package skeleton

**Files:**
- Modify: `requirements.txt`
- Create: `src/dashboard/__init__.py`

- [ ] **Step 1: Add dependencies**

```
fastapi>=0.115.0
uvicorn>=0.34.0
```

- [ ] **Step 2: Install and create skeleton**

```bash
pip install fastapi uvicorn
mkdir -p src/dashboard/templates src/dashboard/static src/dashboard/api
touch src/dashboard/__init__.py src/dashboard/api/__init__.py
```

- [ ] **Step 3: Commit**

```bash
git add requirements.txt src/dashboard/
git commit -m "feat: add dashboard package skeleton + FastAPI dependency"
```

---

### Task 4.2: Create API endpoints

**Files:**
- Create: `src/dashboard/api/sessions.py`
- Create: `src/dashboard/server.py`

- [ ] **Step 1: Write session listing and detail endpoints**

```python
# src/dashboard/api/sessions.py
"""API endpoints for session data."""
import os
import json
from pathlib import Path
from fastapi import APIRouter, Query

router = APIRouter(prefix="/api")


def _find_session_files(data_root: str) -> list[Path]:
    sessions_dir = Path(data_root) / "sessions"
    if not sessions_dir.exists():
        return []
    return sorted(sessions_dir.glob("*_session_*.json"), reverse=True)


@router.get("/sessions")
def list_sessions(
    data_root: str = Query("data/prod"),
    symbol: str | None = None,
    limit: int = 50,
):
    files = _find_session_files(data_root)
    if symbol:
        files = [f for f in files if symbol.upper() in f.name.upper()]
    results = []
    for f in files[:limit]:
        try:
            data = json.loads(f.read_text())
            decision = data.get("final_decision", {})
            results.append({
                "filename": f.name,
                "symbol": data.get("observation", {}).get("symbol", ""),
                "observed_at": data.get("observation", {}).get("observed_at", ""),
                "opinion": decision.get("opinion", "UNKNOWN"),
                "confidence": decision.get("confidence_score"),
                "tactical": decision.get("tactical_parameters", {}),
            })
        except Exception:
            results.append({"filename": f.name, "error": "Failed to parse"})
    return {"sessions": results, "total": len(files)}


@router.get("/sessions/{filename}")
def get_session(filename: str, data_root: str = Query("data/prod")):
    path = Path(data_root) / "sessions" / filename
    if not path.exists():
        return {"error": "Not found"}
    return json.loads(path.read_text())
```

- [ ] **Step 2: Write the server entry point**

```python
# src/dashboard/server.py
"""FastAPI dashboard server for Singularity session visualization."""
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from fastapi import FastAPI, Query
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
from src.dashboard.api.sessions import router as sessions_router

app = FastAPI(title="Singularity Dashboard", version="1.0")

static_dir = Path(__file__).parent / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

app.include_router(sessions_router)

TEMPLATES_DIR = Path(__file__).parent / "templates"


def read_template(name: str) -> str:
    path = TEMPLATES_DIR / name
    return path.read_text() if path.exists() else "<h1>Template missing</h1>"


@app.get("/", response_class=HTMLResponse)
def index(data_root: str = Query("data/prod")):
    return read_template("index.html")


@app.get("/sessions/{filename}", response_class=HTMLResponse)
def session_view(filename: str, data_root: str = Query("data/prod")):
    return read_template("session.html")


@app.get("/ledger", response_class=HTMLResponse)
def ledger(data_root: str = Query("data/prod")):
    return read_template("ledger.html")


def main():
    import uvicorn
    uvicorn.run("src.dashboard.server:app", host="0.0.0.0", port=8080, reload=True)


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Verify server starts**

```bash
timeout 5 python -c "from src.dashboard.server import app; print('Server OK')" 2>&1 || true
```

- [ ] **Step 4: Commit**

```bash
git add src/dashboard/api/sessions.py src/dashboard/server.py
git commit -m "feat: add FastAPI server with session API endpoints"
```

---

### Task 4.3: Create HTML templates

**Files:**
- Create: `src/dashboard/templates/base.html`
- Create: `src/dashboard/templates/index.html`
- Create: `src/dashboard/templates/session.html`
- Create: `src/dashboard/templates/ledger.html`

- [ ] **Step 1: Write base template**

```html
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Singularity Dashboard</title>
    <link rel="stylesheet" href="/static/dashboard.css">
</head>
<body class="dark">
    <nav>
        <a href="/">Sessions</a>
        <a href="/ledger">Ledger</a>
    </nav>
    <main>{% block content %}{% endblock %}</main>
    <script>
        // Simple template variable substitution
        document.addEventListener('DOMContentLoaded', () => {
            document.body.innerHTML = document.body.innerHTML.replace(
                /\{\{\s*(\w+)\s*\}\}/g, (_, key) => ''
            );
        });
    </script>
</body>
</html>
```

Wait — we're not using Jinja2. Let's keep it simple: pure HTML/JS that fetches from `/api/` endpoints. No server-side templating.

- [ ] **Step 1 (revised): Write index.html — session browser**

The index page fetches `/api/sessions` and renders a table. Each row links to `/sessions/{filename}`. Pure HTML + vanilla JS.

- [ ] **Step 2: Write session.html — single session view**

Fetches `/api/sessions/{filename}` and renders the decision card, debate rounds, and chart images.

- [ ] **Step 3: Write ledger.html — multi-session ledger**

Fetches `/api/sessions` and renders a sortable P&L table with MAE/MFE bars.

- [ ] **Step 4: Commit**

```bash
git add src/dashboard/templates/
git commit -m "feat: add dashboard HTML templates (index, session, ledger)"
```

---

### Task 4.4: Create CSS stylesheet

**Files:**
- Create: `src/dashboard/static/dashboard.css`

- [ ] **Step 1: Write dark-themed stylesheet**

Dark theme matching existing chart aesthetic (`#0d1117` background). Card-based layout. Responsive grid for the index page. Monospace font for data tables.

- [ ] **Step 2: Commit**

```bash
git add src/dashboard/static/dashboard.css
git commit -m "feat: add dashboard CSS (dark theme)"
```

---

### Task 4.5: End-to-end dashboard test

- [ ] **Step 1: Start the server**

```bash
python -m src.dashboard.server &
sleep 3
curl -s http://localhost:8080/api/sessions?data_root=data/prod | python -m json.tool | head -30
```

Expected: JSON array of session files.

- [ ] **Step 2: Verify HTML pages load**

```bash
curl -s http://localhost:8080/ | head -10
curl -s http://localhost:8080/ledger | head -10
```

- [ ] **Step 3: Kill server and commit any fixes**

```bash
kill %1 2>/dev/null || true
```

---

## Phase 5: Test Reorganization

### Task 5.1: Restructure test directory

- [ ] **Step 1: Create new directory layout**

```bash
mkdir -p tests/unit tests/integration tests/system
```

- [ ] **Step 2: Move test files to appropriate directories**

```bash
# Unit tests (pure functions, no I/O)
mv tests/test_math_utils.py tests/unit/
mv tests/test_json_utils.py tests/unit/ 2>/dev/null || true
mv tests/test_pipeline_utils.py tests/unit/
mv tests/test_evolution_utils.py tests/unit/
mv tests/test_slippage.py tests/unit/

# Integration tests (multiple modules, mocked I/O)
mv tests/test_market_regime.py tests/integration/
mv tests/test_calculate_qty.py tests/integration/
mv tests/test_evolver_sandbox.py tests/integration/

# System tests (end-to-end with mocks)
mv tests/test_binary_star.py tests/system/
mv tests/test_adapters.py tests/system/
mv tests/test_order_executor.py tests/system/
mv tests/test_chaos_logic.py tests/system/
mv tests/test_patch.py tests/system/

# Keep shared fixtures at top level
# tests/conftest.py, tests/mock_factory.py stay
```

- [ ] **Step 3: Update imports in moved test files**

`from tests.mock_factory import ...` → `from tests.mock_factory import ...` (still works since tests/ is the package root)

- [ ] **Step 4: Run full test suite**

```bash
python -m pytest tests/ -v --tb=short 2>&1 | tail -40
```

- [ ] **Step 5: Commit**

```bash
git add tests/
git commit -m "refactor: reorganize tests into unit/integration/system"
```

---

### Task 5.2: Review and improve test quality

- [ ] **Step 1: Run coverage to find gaps**

```bash
python -m pytest tests/ --cov=src --cov-report=term-missing 2>&1 | tail -50
```

- [ ] **Step 2: Evaluate each test**

For each test file, check: is it testing real behavior or just asserting mocks? Drop tests that can't catch a regression. Add tests for critical paths that are uncovered:
- `MathTools.calculate_risk_reward()` edge cases (zero stop loss, negative prices)
- Config loading from actual YAML files (Task 5.3)
- DebateLoop contract (mocked agents)

- [ ] **Step 3: Commit improvements**

```bash
git add tests/
git commit -m "test: improve test coverage and quality"
```

---

### Task 5.3: Add new tests for refactored components

**Files:**
- Create: `tests/unit/test_config.py` — sub-config loading from YAML
- Create: `tests/integration/test_ai_client.py` — adapter contract compliance
- Create: `tests/integration/test_debate_loop.py` — debate flow with mocked agents

- [ ] **Step 1: Write config loading test**

```python
"""Test that sub-config loaders produce correct values from actual YAML."""
from src.utils.pipeline_utils import load_config
from src.config.loader import (
    load_regime_config, load_temporal_config, load_risk_config,
)


def test_regime_config_loads_from_yaml():
    cfg = load_config()
    r = load_regime_config(cfg)
    assert r.trend_intensity_threshold == 0.2
    assert r.volatility_extreme_ratio == 2.2
    assert isinstance(r.squeeze_threshold, float)


def test_temporal_config_loads_from_yaml():
    cfg = load_config()
    t = load_temporal_config(cfg)
    assert isinstance(t.min_trade_velocity, float)
    assert t.temporal_dilation_standard > 0


def test_risk_config_loads_from_yaml():
    cfg = load_config()
    k = load_risk_config(cfg)
    assert k.min_rr_trending > 0
    assert k.structural_buffer_atr > 0
```

- [ ] **Step 2: Write adapter contract test**

```python
"""Verify all adapters satisfy AbstractAIClient interface."""
from src.infrastructure.ai_client import AbstractAIClient
from src.infrastructure.ai.gemini_adapter import GeminiAdapter
from src.infrastructure.ai.deepseek_adapter import DeepSeekAdapter
from src.infrastructure.ai.qwen_adapter import QwenAdapter
from src.infrastructure.ai.ollama_adapter import OllamaAdapter


def test_all_adapters_implement_interface():
    adapters = [
        GeminiAdapter("test"),
        DeepSeekAdapter("test"),
        QwenAdapter("test"),
        OllamaAdapter("http://localhost:11434", "test-model"),
    ]
    for adapter in adapters:
        assert isinstance(adapter, AbstractAIClient)


def test_ai_response_dataclass():
    from src.infrastructure.ai_client import AIResponse, ToolCall, UsageMetadata
    r = AIResponse(text="{}", usage=UsageMetadata(total_token_count=100))
    assert r.text == "{}"
    assert r.usage.total_token_count == 100
```

- [ ] **Step 3: Write debate loop test**

```python
"""Test DebateLoop with mocked agents."""
from unittest.mock import MagicMock
from src.agent.debate_loop import DebateLoop


def test_debate_loop_exits_on_pass():
    mock_session = MagicMock()
    mock_session.execute_session_cycle.return_value = {
        "opinion": "BULLISH", "confidence_score": 85,
        "tactical_parameters": {"entry": 100, "stop_loss": 98, "take_profit": 106},
    }
    mock_critic = MagicMock()
    mock_critic.evaluate.return_value = {"veto_level": "PASS", "invalidations": []}

    mock_math = MagicMock()
    mock_math.verify.return_value = {"status": "VERIFIED", "compliance_verdict": {}}

    loop = DebateLoop(
        session_agent=mock_session, critic_agent=mock_critic,
        math_checker=mock_math, max_rounds=3,
        cache_resource_name=None, tools=[], visual_parts=[],
        shared_instruction="Test instruction",
        session_config=MagicMock(), critic_config=MagicMock(),
    )
    result = loop.run({"quantitative_metrics": {}}, "BTCUSDT")

    assert result["early_exit"] is True
    assert result["final_decision"]["opinion"] == "BULLISH"
```

- [ ] **Step 4: Run new tests**

```bash
python -m pytest tests/unit/test_config.py tests/integration/test_ai_client.py tests/integration/test_debate_loop.py -v
```

- [ ] **Step 5: Commit**

```bash
git add tests/
git commit -m "test: add tests for config loading, adapter contract, and debate loop"
```

---

## Final Verification

- [ ] **Run full test suite**

```bash
python -m pytest tests/ -v --tb=short 2>&1
```

- [ ] **Verify CLI entry points import cleanly**

```bash
python -c "from run_session import main; print('run_session OK')"
python -c "from run_sniper import SniperDaemon; print('run_sniper OK')"
python -c "from run_evolution import EvolutionEngine; print('run_evolution OK')"
python -c "from run_audit import main; print('run_audit OK')"
```

- [ ] **Verify dashboard starts**

```bash
python -c "from src.dashboard.server import app; print('Dashboard OK')"
```

- [ ] **Final commit**

```bash
git add -A
git commit -m "chore: final verification, refactor complete"
```
