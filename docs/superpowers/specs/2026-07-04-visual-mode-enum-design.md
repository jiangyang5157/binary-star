# Visual Mode Enum + Route Unification — Design Spec

**Date:** 2026-07-04
**Status:** Approved
**Scope:** Replace `supports_vision: bool` with `VisualMode` enum; rename `visual_context_text` → `visual_text`; simplify orchestrator routing.

---

## 1. Problem

After the previous cleanup (removing dead `supports_vision` config), one inconsistency remains:

1. **`supports_vision: bool` conflates two decisions** — "can the model see images" (capability) and "how do we deliver visual context" (behavior). No way to express "skip visual context entirely."

2. **Variable name `visual_context_text` is verbose** — the context already makes it clear this is visual.

3. **Orchestrator still knows too much** — it checks `self._supports_vision` and branches on model-specific behavior rather than asking the adapter.

## 2. Solution

### 2.1 `VisualMode` enum

```python
# src/infrastructure/ai_client.py

from enum import Enum

class VisualMode(Enum):
    NONE = "none"   # skip visual context (save tokens)
    TEXT = "text"   # inject .md text summary into prompt
    IMAGE = "image" # attach .png images as VisualPart
```

Replaces `supports_vision: bool` on `AbstractAIClient`:

```python
# Before:
@property
def supports_vision(self) -> bool:
    return False

# After:
@property
def visual_mode(self) -> VisualMode:
    return VisualMode.NONE
```

### 2.2 Adapter declarations

Each adapter hardcodes its mode — no config involved:

| Adapter | `visual_mode` | Rationale |
|---------|--------------|-----------|
| `AbstractAIClient` | `NONE` | Default — no visual capability |
| `GeminiAdapter` | `IMAGE` | Native image support + context cache |
| `DeepSeekAdapter` | `TEXT` | Text-only, uses `.md` summaries |
| `QwenAdapter` | `TEXT` | Text-only (unless vl model, future) |

### 2.3 Variable rename

`visual_context_text` → `visual_text` across all 4 files (orchestrator, debate_loop, session_agent, critic_agent). Pure rename, zero logic change.

## 3. Code Changes

### 3.1 Files modified

| # | File | Change |
|---|------|--------|
| 1 | `src/infrastructure/ai_client.py` | Add `VisualMode` enum; rename property `supports_vision` → `visual_mode`; return `VisualMode.NONE` |
| 2 | `src/infrastructure/ai/gemini_adapter.py` | Rename property `supports_vision` → `visual_mode`; return `VisualMode.IMAGE` |
| 3 | `src/infrastructure/ai/deepseek_adapter.py` | Add `visual_mode` property → `VisualMode.TEXT` |
| 4 | `src/infrastructure/ai/qwen_adapter.py` | Add `visual_mode` property → `VisualMode.TEXT` |
| 5 | `src/infrastructure/ai/_openai_helpers.py` | `self.supports_vision` → `self.visual_mode == VisualMode.IMAGE` |
| 6 | `src/agent/binary_star_orchestrator.py` | `_supports_vision` → `switch visual_mode`; rename `visual_context_text` → `visual_text` |
| 7 | `src/agent/debate_loop.py` | Rename `visual_context_text` → `visual_text` |
| 8 | `src/agent/session_agent.py` | Rename `visual_context_text` → `visual_text` |
| 9 | `src/agent/critic_agent.py` | Rename `visual_context_text` → `visual_text` |

### 3.2 Files NOT modified

- `visual_context_summarizer.py` — unrelated
- `market_observer.py` — unrelated
- `chart_generator.py` — unrelated
- `clean_orphan_artifacts.py` — unrelated
- `build_messages()` — internal `supports_vision` param renamed to `supports_image`, logic unchanged
- All prompt templates — zero modifications
- `global_config.yaml` — zero modifications (dead config already removed)
- `cache_manager.py` — zero modifications (cache refactor is future work)

### 3.3 Orchestrator routing (after)

```python
def _load_visual_assets(self, observation: Dict[str, Any]) -> tuple[List[VisualPart], str | None]:
    vc = observation.get('visual_context', {})
    mode = self.client.visual_mode

    match mode:
        case VisualMode.IMAGE:
            parts = []
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
            text_blocks = []
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

### 3.4 Prompt injection (after)

```python
# session_agent.py / critic_agent.py

if visual_text:                          # was: visual_context_text
    prompt = prompt + '\n\n' + visual_text
```

### 3.5 `build_messages()` adapter change

```python
# _openai_helpers.py

# Before:
supports_vision=self.supports_vision

# After:
supports_vision=(self.visual_mode == VisualMode.IMAGE)
```

The internal `build_messages(supports_vision=...)` parameter keeps its name — it still means "should I base64-encode images." Only the source of truth changes from `self._supports_vision` (dead instance var) to `self.visual_mode` (property enum).

### 3.6 Report path correction

```python
# binary_star_orchestrator.py

# Before:
if not self._supports_vision:

# After:
if self.client.visual_mode == VisualMode.TEXT:
```

Path correction logic unchanged — only the condition changes.

## 4. Self-Review

### 4.1 Placeholder scan
- No TBDs, TODOs, or incomplete sections.

### 4.2 Internal consistency
- `VisualMode` enum used in: adapter properties, orchestrator routing, `build_messages()` parameter.
- `visual_text` variable name consistent across orchestrator → debate_loop → session_agent → critic_agent.
- Default `NONE` ensures no existing code accidentally sends visual context.

### 4.3 Scope check
- Single subsystem: type-level refactor + rename. No decomposition needed.
- Future work explicitly deferred: cache refactor (move cache lifecycle into adapter).

### 4.4 Ambiguity check
- `VisualMode.TEXT` path: reads `.md` files, returns text string. Clear.
- `VisualMode.IMAGE` path: reads `.png` files, returns VisualPart list. Clear.
- `VisualMode.NONE` path: returns `[], None`. Clear.
- `build_messages()` param remains `supports_vision: bool` — minor naming mismatch with the new enum but acceptable since it's an internal function detail.
