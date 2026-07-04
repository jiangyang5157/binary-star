# Visual Mode Enum — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace `supports_vision: bool` with `VisualMode` enum; rename `visual_context_text` → `visual_text` across 4 files.

**Architecture:** A 3-value enum (`NONE | TEXT | IMAGE`) declared on `AbstractAIClient` as a property. Each adapter hardcodes its mode. The orchestrator switches on `self.client.visual_mode`. The variable rename is purely mechanical.

**Tech Stack:** Python 3.13 — no new dependencies.

## Global Constraints

- Prompt templates (`session.md`, `critic.md`, `binary_star.md`) — ZERO modifications
- `build_messages()` / `_openai_helpers.py` — parameter rename only, logic unchanged
- `ChartGenerator`, `MarketObserver`, `VisualContextSummarizer` — ZERO modifications
- `global_config.yaml` — ZERO modifications (dead config already removed)
- `cache_manager.py` — ZERO modifications (cache refactor deferred)
- No backward compatibility needed

---

### Task 1: Add VisualMode enum + update all adapter properties

**Files:**
- Modify: `src/infrastructure/ai_client.py:1-4` (add import), `:73-76` (replace property)
- Modify: `src/infrastructure/ai/gemini_adapter.py:36-38` (replace property)
- Modify: `src/infrastructure/ai/deepseek_adapter.py:8-12` (add property)
- Modify: `src/infrastructure/ai/qwen_adapter.py:5-14` (add property)

**Interfaces:**
- Produces: `VisualMode` enum in `ai_client.py`
- Produces: `AbstractAIClient.visual_mode → VisualMode.NONE`
- Produces: `GeminiAdapter.visual_mode → VisualMode.IMAGE`
- Produces: `DeepSeekAdapter.visual_mode → VisualMode.TEXT`
- Produces: `QwenAdapter.visual_mode → VisualMode.TEXT`

- [ ] **Step 1: Add VisualMode enum + replace AbstractAIClient property**

In `src/infrastructure/ai_client.py`, add import after line 3:

```python
from enum import Enum
```

After the `VisualPart` dataclass (before `ToolCall`), add:

```python
class VisualMode(Enum):
    """How visual context is delivered to the model."""
    NONE = "none"    # skip entirely (save tokens)
    TEXT = "text"    # inject .md text summary into prompt
    IMAGE = "image"  # attach .png images as VisualPart
```

Replace lines 73-76:

```python
    # Before:
    @property
    def supports_vision(self) -> bool:
        """Whether this provider natively consumes image data (VisualPart)."""
        return False

    # After:
    @property
    def visual_mode(self) -> VisualMode:
        """How this provider receives visual context."""
        return VisualMode.NONE
```

- [ ] **Step 2: Update GeminiAdapter**

In `src/infrastructure/ai/gemini_adapter.py`, replace lines 36-38:

```python
    # Before:
    @property
    def supports_vision(self) -> bool:
        return True

    # After:
    @property
    def visual_mode(self) -> VisualMode:
        return VisualMode.IMAGE
```

Add import at top (after existing imports):

```python
from src.infrastructure.ai_client import (
    AbstractAIClient, AIResponse, ToolCall, UsageMetadata, VisualPart, VisualMode,
)
```

- [ ] **Step 3: Add property to DeepSeekAdapter**

In `src/infrastructure/ai/deepseek_adapter.py`, add after `__init__`:

```python
    @property
    def visual_mode(self) -> "VisualMode":
        return VisualMode.TEXT
```

Add import:

```python
from src.infrastructure.ai_client import VisualMode
```

Full file after change:

```python
"""DeepSeekAdapter — thin subclass of OpenAICompatibleAdapter."""
from src.infrastructure.ai._openai_helpers import OpenAICompatibleAdapter
from src.infrastructure.ai_client import VisualMode


class DeepSeekAdapter(OpenAICompatibleAdapter):
    """Talks to DeepSeek API via the shared OpenAI-compatible protocol."""

    def __init__(self, api_key: str, default_model: str = "deepseek-v4-flash",
                 base_url: str = "https://api.deepseek.com",
                 *, http_timeout: int = 240):
        super().__init__(api_key=api_key, default_model=default_model,
                         base_url=base_url, provider_label="DeepSeekAdapter",
                         http_timeout=http_timeout)

    @property
    def visual_mode(self) -> "VisualMode":
        return VisualMode.TEXT
```

- [ ] **Step 4: Add property to QwenAdapter**

Same pattern. In `src/infrastructure/ai/qwen_adapter.py`:

```python
"""QwenAdapter — thin subclass of OpenAICompatibleAdapter."""
from src.infrastructure.ai._openai_helpers import OpenAICompatibleAdapter
from src.infrastructure.ai_client import VisualMode


class QwenAdapter(OpenAICompatibleAdapter):
    """Talks to Alibaba Qwen (DashScope) via the shared OpenAI-compatible protocol."""

    def __init__(self, api_key: str, default_model: str = "qwen-plus",
                 base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1",
                 *, http_timeout: int = 240):
        super().__init__(api_key=api_key, default_model=default_model,
                         base_url=base_url, provider_label="QwenAdapter",
                         http_timeout=http_timeout)

    @property
    def visual_mode(self) -> "VisualMode":
        return VisualMode.TEXT
```

- [ ] **Step 5: Verify tests pass**

```bash
cd /Users/yangjiang/Documents/workspace/crypto && python -m pytest tests/ -x -q 2>&1 | tail -3
```

Expected: 276 passed.

- [ ] **Step 6: Commit**

```bash
git add src/infrastructure/ai_client.py src/infrastructure/ai/gemini_adapter.py src/infrastructure/ai/deepseek_adapter.py src/infrastructure/ai/qwen_adapter.py
git commit -m "feat: replace supports_vision bool with VisualMode enum"
```

---

### Task 2: Update _openai_helpers.py adapter reference

**Files:**
- Modify: `src/infrastructure/ai/_openai_helpers.py:207`

**Interfaces:**
- Consumes: `VisualMode` enum from Task 1
- Uses: `self.visual_mode == VisualMode.IMAGE` instead of `self.supports_vision`

- [ ] **Step 1: Replace the single reference**

In `src/infrastructure/ai/_openai_helpers.py`, line 207:

```python
    # Before:
                                  supports_vision=self.supports_vision)

    # After:
                                  supports_vision=(self.visual_mode == VisualMode.IMAGE))
```

Add import at top:

```python
from src.infrastructure.ai_client import VisualMode
```

- [ ] **Step 2: Verify tests pass**

```bash
cd /Users/yangjiang/Documents/workspace/crypto && python -m pytest tests/ -x -q 2>&1 | tail -3
```

Expected: 276 passed.

- [ ] **Step 3: Commit**

```bash
git add src/infrastructure/ai/_openai_helpers.py
git commit -m "refactor: use self.visual_mode in OpenAICompatibleAdapter"
```

---

### Task 3: Update orchestrator — switch routing + variable rename

**Files:**
- Modify: `src/agent/binary_star_orchestrator.py:233` (store mode)
- Modify: `src/agent/binary_star_orchestrator.py:329-340` (path correction)
- Modify: `src/agent/binary_star_orchestrator.py:343-355` (DebateLoop call)
- Modify: `src/agent/binary_star_orchestrator.py:462-500` (`_finalize_and_sanitize`)
- Modify: `src/agent/binary_star_orchestrator.py:528-565` (`_load_visual_assets`)

**Interfaces:**
- Consumes: `VisualMode` from Task 1
- Produces: `visual_text` (renamed from `visual_context_text`) to DebateLoop

- [ ] **Step 1: Replace `_supports_vision` with `_visual_mode`**

In `src/agent/binary_star_orchestrator.py`, line 233:

```python
    # Before:
        self._supports_vision = self.client.supports_vision

    # After:
        self._visual_mode = self.client.visual_mode
```

- [ ] **Step 2: Replace `_load_visual_assets` with `match/case`**

Replace lines 528-565:

```python
    def _load_visual_assets(self, observation: Dict[str, Any]) -> tuple[List[VisualPart], str | None]:
        """Load visual assets based on provider visual mode."""
        vc = observation.get('visual_context', {})

        match self._visual_mode:
            case VisualMode.IMAGE:
                parts: list[VisualPart] = []
                for key in ('macro_snapshot', 'micro_snapshot'):
                    path = vc.get(key)
                    if path and os.path.exists(path):
                        try:
                            with open(path, 'rb') as f:
                                parts.append(VisualPart(
                                    mime_type='image/png',
                                    data=f.read(),
                                    label=f'[VISUAL_CONTEXT: {key.upper()}]',
                                ))
                        except Exception as e:
                            logger.warning(f"failed to read visual asset {path}: {e}")
                return parts, None

            case VisualMode.TEXT:
                text_blocks: list[str] = []
                for label, key in [
                    ('VISUAL_CONTEXT: MACRO_SNAPSHOT', 'macro_snapshot_summary'),
                    ('VISUAL_CONTEXT: MICRO_SNAPSHOT', 'micro_snapshot_summary'),
                ]:
                    path = vc.get(key)
                    if path and os.path.exists(path):
                        try:
                            with open(path, 'r') as f:
                                text_blocks.append(f'{label}\n\n{f.read()}')
                        except Exception as e:
                            logger.warning(f"failed to read visual asset {path}: {e}")
                text = '\n\n'.join(text_blocks) if text_blocks else None
                return [], text

            case VisualMode.NONE:
                return [], None
```

Add `VisualMode` import at top:

```python
from src.infrastructure.ai_client import VisualPart, VisualMode
```

- [ ] **Step 3: Rename `visual_context_text` → `visual_text` + fix conditions**

In `execute_flow()` (around line 334):

```python
    # Before:
        visual_parts, visual_context_text = self._load_visual_assets(observation)
        if not self._supports_vision:

    # After:
        visual_parts, visual_text = self._load_visual_assets(observation)
        if self._visual_mode == VisualMode.TEXT:
```

In the DebateLoop constructor (around line 354):

```python
    # Before:
                visual_context_text=visual_context_text,

    # After:
                visual_text=visual_text,
```

- [ ] **Step 4: Update `_finalize_and_sanitize` parameter name**

In the method signature (around line 462):

```python
    # Before:
                               visual_context_text: str | None,

    # After:
                               visual_text: str | None,
```

In the call to `execute_session_cycle` (around line 490):

```python
    # Before:
                    visual_context_text=visual_context_text,

    # After:
                    visual_text=visual_text,
```

In the call site in `execute_flow` (around line 374):

```python
    # Before:
                visual_context_text,

    # After:
                visual_text,
```

- [ ] **Step 5: Verify tests pass**

```bash
cd /Users/yangjiang/Documents/workspace/crypto && python -m pytest tests/ -x -q 2>&1 | tail -3
```

Expected: 276 passed.

- [ ] **Step 6: Commit**

```bash
git add src/agent/binary_star_orchestrator.py
git commit -m "refactor: switch on VisualMode enum, rename visual_context_text → visual_text"
```

---

### Task 4: Rename in agent layer — debate_loop + session_agent + critic_agent

**Files:**
- Modify: `src/agent/debate_loop.py:18` (`__init__` param), `:29` (store), `:71` (Session call), `:111` (Critic call)
- Modify: `src/agent/session_agent.py:116` (param), `:130-131` (injection)
- Modify: `src/agent/critic_agent.py:101` (param), `:120-121` (injection)

**Interfaces:**
- Consumes: `visual_text` (renamed from `visual_context_text`) from Task 3
- Pure rename — no logic change

- [ ] **Step 1: Rename in debate_loop.py**

In `src/agent/debate_loop.py`, 4 occurrences:

Line 18 — `__init__` parameter:

```python
    # Before:
                 visual_context_text: str | None = None):

    # After:
                 visual_text: str | None = None):
```

Line 29 — store:

```python
    # Before:
        self.visual_context_text = visual_context_text

    # After:
        self.visual_text = visual_text
```

Line 71 — Session call:

```python
    # Before:
                visual_context_text=self.visual_context_text,

    # After:
                visual_text=self.visual_text,
```

Line 111 — Critic call:

```python
    # Before:
                visual_context_text=self.visual_context_text,

    # After:
                visual_text=self.visual_text,
```

- [ ] **Step 2: Rename in session_agent.py**

In `src/agent/session_agent.py`, 2 occurrences:

Line 116 — parameter:

```python
    # Before:
        visual_context_text: Optional[str] = None,

    # After:
        visual_text: Optional[str] = None,
```

Lines 130-131 — injection:

```python
    # Before:
            if visual_context_text:
                prompt = prompt + '\n\n' + visual_context_text

    # After:
            if visual_text:
                prompt = prompt + '\n\n' + visual_text
```

- [ ] **Step 3: Rename in critic_agent.py**

In `src/agent/critic_agent.py`, 2 occurrences:

Line 101 — parameter:

```python
    # Before:
        visual_context_text: Optional[str] = None,

    # After:
        visual_text: Optional[str] = None,
```

Lines 120-121 — injection:

```python
    # Before:
            if visual_context_text:
                prompt = prompt + '\n\n' + visual_context_text

    # After:
            if visual_text:
                prompt = prompt + '\n\n' + visual_text
```

- [ ] **Step 4: Verify tests pass**

```bash
cd /Users/yangjiang/Documents/workspace/crypto && python -m pytest tests/ -x -q 2>&1 | tail -3
```

Expected: 276 passed.

- [ ] **Step 5: Final grep — confirm zero remaining `visual_context_text` references**

```bash
grep -rn "visual_context_text" src/ 2>/dev/null
```

Expected: no output.

- [ ] **Step 6: Final grep — confirm zero remaining `supports_vision` references**

```bash
grep -rn "supports_vision" src/ 2>/dev/null
```

Expected: only `build_messages` internal param name (kept).

- [ ] **Step 7: Commit**

```bash
git add src/agent/debate_loop.py src/agent/session_agent.py src/agent/critic_agent.py
git commit -m "refactor: rename visual_context_text → visual_text"
```

---

### Final Verification

- [ ] **Full test suite:**

```bash
cd /Users/yangjiang/Documents/workspace/crypto && python -m pytest tests/ -v 2>&1 | tail -5
```

Expected: 276 passed.

- [ ] **Quick smoke — import + property check:**

```bash
cd /Users/yangjiang/Documents/workspace/crypto && python -c "
from src.infrastructure.ai_client import VisualMode
from src.infrastructure.ai_factory import AIFactory
from src.infrastructure.ai.gemini_adapter import GeminiAdapter
from src.infrastructure.ai.deepseek_adapter import DeepSeekAdapter
print('Gemini:', GeminiAdapter('').visual_mode)
print('DeepSeek:', DeepSeekAdapter('').visual_mode)
print('NONE:', VisualMode.NONE)
print('TEXT:', VisualMode.TEXT)
print('IMAGE:', VisualMode.IMAGE)
"
```

Expected:
```
Gemini: VisualMode.IMAGE
DeepSeek: VisualMode.TEXT
NONE: VisualMode.NONE
TEXT: VisualMode.TEXT
IMAGE: VisualMode.IMAGE
```
