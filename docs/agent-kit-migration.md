# Agent-Kit Migration Plan

Crypto consumes `agent-kit` as a local path dependency, replacing its own
duplicate protocol layer. agent-kit is read-only — all changes are crypto-side.

**原则**
- 协议（`AIClient`, `AIResponse`, `ToolCall`, `Usage`, `ToolDeclaration`）来自 agent-kit
- 实现（adapter、agent 逻辑、VisualPart、Gemini 缓存）留在 crypto
- 每个 adapter 直接实现 `agent_kit.AIClient`，不额外包装

---

## 迁移后文件结构

```
src/infrastructure/
├── __init__.py
├── ai_factory.py               ← AIFactory (类型标注改为 AIClient)
├── visual_part.py              ← VisualPart (从 ai_client.py 迁出)
├── ai/
│   ├── __init__.py
│   ├── _openai_helpers.py      ← build_messages / convert_tools / clean_json_text
│   ├── openai_compat.py        ← [新建] crypto 的 OpenAICompatibleAdapter
│   ├── deepseek_adapter.py     ← 继承 openai_compat.py 的适配器
│   ├── qwen_adapter.py         ← 同上
│   └── gemini_adapter.py       ← 实现 AIClient (Gemini 不走 OpenAI 协议)
├── gemini/
│   ├── __init__.py
│   └── cache_manager.py        ← import VisualPart 的位置更新
├── exchange/
│   └── ...                     ← 不变
```

**关键改动：**
- `src/infrastructure/ai_client.py` → **删除**
- `src/infrastructure/visual_part.py` → **新建**（存放 VisualPart）
- `src/infrastructure/ai/openai_compat.py` → **新建**（crypto 的 OpenAICompatibleAdapter 从 `_openai_helpers.py` 拆出来，文件职责更清晰）
- `src/infrastructure/ai/_openai_helpers.py` → 只保留纯工具函数

之所以把 `OpenAICompatibleAdapter` 从 `_openai_helpers.py` 拆出来，因为：
- `_openai_helpers.py` 命名里有 "helpers"，但实际上有一个类定义 + 工具函数，职责不清
- `openai_compat.py` 命名直接表达"这是 OpenAI 兼容适配器"
- 工具函数（`build_messages`, `convert_tools`, `clean_json_text`）作为私有模块留在 `_openai_helpers.py`，只被 adapter 内部调用

---

## 步骤

### Step 1 — 添加依赖

```toml
# pyproject.toml
dependencies = [
    "agent-kit = {path = "../agent-kit"}",
    # 保留其他依赖不变
]
```

→ `pip install -e .`，验证 `from agent_kit import AIClient` 可工作。

### Step 2 — 新建 `visual_part.py`

从 `ai_client.py` 拆出 `VisualPart`，保持文件职责单一：

```python
"""Provider-agnostic visual content (image, chart, etc.)."""
from dataclasses import dataclass


@dataclass
class VisualPart:
    mime_type: str
    data: bytes
    label: str | None = None
```

### Step 3 — 新建 `openai_compat.py` + 精简 `_openai_helpers.py`

`_openai_helpers.py` 拆分为二：

**保留 `_openai_helpers.py`**，只保留工具函数：

```python
"""Shared helpers for OpenAI-compatible adapters (private module)."""
import base64
import json
import logging
from typing import Any

from agent_kit import AIClient, AIResponse, ToolCall, Usage
from src.infrastructure.visual_part import VisualPart

logger = logging.getLogger(__name__)

JSON_HINT = (
    "IMPORTANT: You MUST respond ONLY with a valid JSON object. "
    "Do NOT include markdown blocks, preamble, or explanations."
)


def build_messages(
    system_instruction: str | None, contents: list[Any],
    *, response_json: bool = False, supports_vision: bool = False,
) -> list[dict]:
    """Convert agent-agnostic contents to OpenAI message format."""
    # ... 与原实现相同，import 和字段名更新 ...


def convert_tools(tools: list[Any]) -> list[dict]:
    """Convert tool declarations to OpenAI function-calling format.
    Handles both Gemini Tool objects and plain dicts."""
    # ... 与原实现相同 ...


def clean_json_text(raw_text: str) -> str:
    """Remove markdown code fences from JSON response text."""
    # ... 与原实现相同 ...
```

**新建 `openai_compat.py`**，存放 adapter 类：

```python
"""OpenAI-compatible adapter — implements agent_kit.AIClient.

This is crypto's OWN adapter, not inherited from agent_kit's adapter.
It uses crypto-specific helper functions for vision, tool conversion,
and reasoning_content handling.
"""
from typing import Any

from openai import OpenAI

from agent_kit import AIClient, AIResponse, ToolCall, Usage
from src.infrastructure.ai._openai_helpers import (
    build_messages, convert_tools, clean_json_text,
)


class OpenAICompatibleAdapter(AIClient):
    """Base adapter for OpenAI-compatible providers (DeepSeek, Qwen)."""

    def __init__(self, api_key: str, default_model: str, base_url: str,
                 provider_label: str, *, supports_vision: bool = False,
                 http_timeout: int = 240):
        self.api_key = api_key
        self.default_model = default_model
        self.base_url = base_url
        self.provider_label = provider_label
        self._supports_vision = supports_vision
        self._http_timeout = http_timeout
        self._client = None
        self._model_logged = False

    @property
    def supports_context_cache(self) -> bool:
        return False

    def _get_client(self):
        if self._client is None:
            self._client = OpenAI(
                api_key=self.api_key, base_url=self.base_url,
                timeout=self._http_timeout,
            )
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
        messages = build_messages(system_instruction, contents,
                                  response_json=response_json,
                                  supports_vision=self._supports_vision)
        openai_tools = convert_tools(tools) if tools else None

        params: dict[str, Any] = {
            "model": target_model, "messages": messages,
            "temperature": temperature,
        }
        if openai_tools:
            params["tools"] = openai_tools
            params["tool_choice"] = "auto"
        if response_json:
            params["response_format"] = {"type": "json_object"}
        if http_timeout:
            params["timeout"] = http_timeout

        if not self._model_logged:
            logger.info("AI call | provider=%s | model=%s",
                        self.provider_label, target_model)
            self._model_logged = True
        else:
            logger.debug("AI call | provider=%s | model=%s",
                         self.provider_label, target_model)

        response = self._get_client().chat.completions.create(**params)
        return self._parse(response, response_json)

    def _parse(self, response, is_json: bool) -> AIResponse:
        # ... 与原实现相同，字段名映射更新 ...
```

### Step 4 — 更新 `DeepSeekAdapter` / `QwenAdapter`

这两个文件各 6 行，只改 import 路径：

```python
# Before
from src.infrastructure.ai._openai_helpers import OpenAICompatibleAdapter

# After
from src.infrastructure.ai.openai_compat import OpenAICompatibleAdapter
```

类定义不变。

### Step 5 — 更新 `GeminiAdapter`

```python
# Before
from src.infrastructure.ai_client import (
    AbstractAIClient, AIResponse, ToolCall, UsageMetadata, VisualPart,
)

# After
from agent_kit import AIClient, AIResponse, ToolCall, Usage
from src.infrastructure.visual_part import VisualPart

# Before
class GeminiAdapter(AbstractAIClient):

# After
class GeminiAdapter(AIClient):
```

`usage` 字段名映射：
- `m.prompt_token_count` → `input_token_count`
- `m.candidates_token_count` → `output_token_count`
- `m.cached_content_token_count` → 额外属性 `usage.cached_content_token_count = ...`

### Step 6 — 更新所有 agent import

| 文件 | Before | After |
|---|---|---|
| `src/agent/base_agent.py` | `from src.infrastructure.ai_client import AbstractAIClient, AIResponse, ToolCall, UsageMetadata` | `from agent_kit import AIClient, AIResponse, ToolCall, Usage` |
| `src/agent/critic_agent.py` | `from src.infrastructure.ai_client import AbstractAIClient` | `from agent_kit import AIClient` |
| `src/agent/session_agent.py` | 同上 | 同上 |
| `src/agent/evolver_agent.py` | 同上 | 同上 |
| `src/agent/binary_star_orchestrator.py` | `from src.infrastructure.ai_client import VisualPart` | `from src.infrastructure.visual_part import VisualPart` |
| `src/infrastructure/ai_factory.py` | `from src.infrastructure.ai_client import AbstractAIClient` | `from agent_kit import AIClient` |

### Step 7 — `reasoning_content` 处理

agent-kit 的 `AIResponse` 没有 `reasoning_content`。crypto 的 `_parse()` 和 agent 访问处改成 setattr/getattr 模式：

```python
# openai_compat.py _parse()
response = AIResponse(text=text, tool_calls=tool_calls, usage=usage)
response.reasoning_content = reasoning  # dataclass 支持额外属性
return response

# base_agent.py 读取
getattr(response, 'reasoning_content', None)
```

### Step 8 — `supports_context_cache` 处理

agent-kit 的 `AIClient` 没有这个 property。各 adapter 自己保留（`OpenAICompatibleAdapter` 返回 `False`，`GeminiAdapter` 返回 `True`），orchestrator 改为安全访问：

```python
# binary_star_orchestrator.py
getattr(self.client, 'supports_context_cache', False)
```

### Step 9 — 清理测试

`tests/integration/test_ai_client.py`：

```python
"""Verify all adapters satisfy AIClient protocol (agent-kit)."""
import pytest
from agent_kit import AIClient, AIResponse, ToolCall, Usage
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
        assert isinstance(adapter, AIClient), \
            f"{type(adapter).__name__} does not implement AIClient"


def test_gemini_adapter_supports_cache():
    adapter = GeminiAdapter("test-key")
    assert adapter.supports_context_cache is True


def test_openai_adapters_no_cache():
    adapters = [
        DeepSeekAdapter("test-key", default_model="test-model"),
        QwenAdapter("test-key", default_model="test-model"),
    ]
    for adapter in adapters:
        assert adapter.supports_context_cache is False


def test_ai_response_dataclass():
    r = AIResponse(text="{}", usage=Usage(total_token_count=100))
    assert r.text == "{}"
    assert r.usage.total_token_count == 100


def test_usage_fields():
    u = Usage()
    assert u.total_token_count == 0
    assert u.input_token_count == 0
    assert u.output_token_count == 0


def test_abstract_client_cannot_instantiate():
    with pytest.raises(TypeError):
        AIClient()
```

### Step 10 — 删除旧文件 + 验证

```bash
rm src/infrastructure/ai_client.py
```

验证：

```bash
# 无残留旧名
grep -rn "AbstractAIClient\|UsageMetadata" src/ tests/   # empty

# 测试全绿
pytest tests/ -x --tb=short

# agent-kit 已安装
python -c "from agent_kit import AIClient, AIResponse, ToolCall, Usage"
```
