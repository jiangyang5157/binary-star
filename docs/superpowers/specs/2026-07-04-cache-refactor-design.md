# Cache Lifecycle Refactor — Design Spec

**Date:** 2026-07-04
**Status:** Approved
**Scope:** Move cache lifecycle into adapter; remove `cache_resource_name` and `visual_parts` from agent/debate layers; unify observation JSON delivery.

---

## 1. Problem

1. **`cache_resource_name` penetrates 6 layers** — config → orchestrator → DebateLoop → SessionAgent/CriticAgent → BaseAgent → API call. For DeepSeek/Qwen it's always `None`, yet every method signature carries it.

2. **`visual_parts` passes through agents** — images are loaded by orchestrator, threaded through debate loop and agents, only consumed right before the API call. For non-vision models they're always empty.

3. **Cache TTL lives in config** — `context_cache.enable` and `expiration_minutes` are Gemini-specific tunables that should be adapter-internal constants, mirroring the `visual_mode` pattern.

4. **Observation JSON is duplicated** — Gemini puts it in cache + placeholder in prompt; DeepSeek puts it in prompt. Two mechanisms for the same content.

5. **`GeminiCacheManager` is an unnecessary indirection** — it wraps `genai.Client.caches` with trivial methods. The adapter can call cache APIs directly.

## 2. Solution

### 2.1 Design Principle

```
orchestrator:     统一生命周期接口，零差异化判断
adapter:          所有差异化在内部消化
agent/debate:     零 cache/visual mode 知识
```

### 2.2 New adapter interface

```python
class AbstractAIClient(ABC):
    def begin_session(
        self,
        system_instruction: str | None,
        tools: list | None,
        visual_parts: list | None,
        model: str,
    ) -> None:
        """Prepare session context. Adapter may create cache, preload, etc."""
        pass

    def end_session(self) -> None:
        """Release session resources (cache, connections, etc.)."""
        pass
```

### 2.3 GeminiAdapter

```python
class GeminiAdapter(AbstractAIClient):
    CACHE_TTL_MINUTES = 10

    def __init__(self, ...):
        ...
        self._active_cache_name: str | None = None

    def begin_session(self, system_instruction, tools, visual_parts, model):
        """Create context cache with images + system_instruction + tools.
        
        Observation JSON is intentionally EXCLUDED — it goes in prompt text
        like all other models.
        """
        cache_contents = []
        for vp in (visual_parts or []):
            cache_contents.append(
                types.Part.from_bytes(data=vp.data, mime_type=vp.mime_type)
            )

        cache = self._client.caches.create(
            model=model,
            config=types.CreateCachedContentConfig(
                contents=cache_contents,
                system_instruction=system_instruction,
                tools=self._normalize_tools(tools) if tools else None,
            ),
            ttl=f'{self.CACHE_TTL_MINUTES}m',
        )
        self._active_cache_name = cache.name

    def end_session(self):
        if self._active_cache_name:
            try:
                self._client.caches.delete(name=self._active_cache_name)
            except Exception as e:
                logger.warning(f"cache delete failed: {e}")
            self._active_cache_name = None

    def generate_content(self, model, contents, *, system_instruction=None,
                         tools=None, temperature=0.5, response_json=False,
                         http_timeout=None):
        gen_config: dict[str, Any] = {"temperature": temperature}

        if self._active_cache_name:
            gen_config["cached_content"] = self._active_cache_name
        else:
            if tools:
                gen_config["tools"] = self._normalize_tools(tools)
            if system_instruction is not None:
                gen_config["system_instruction"] = system_instruction

        if response_json:
            gen_config["response_mime_type"] = "application/json"

        gemini_contents = self._to_gemini_contents(contents)
        response = self._client.models.generate_content(
            model=model, contents=gemini_contents, config=gen_config,
        )
        return self._to_ai_response(response)
```

### 2.4 DeepSeekAdapter / QwenAdapter

`begin_session()` and `end_session()` inherit default no-op from `AbstractAIClient`. No changes needed.

## 3. Unified Observation JSON

ALL models send the full `observation_json` in prompt text. No more placeholder.

```python
# session_agent._build_prompt — BEFORE:
if cache_resource_name:
    observation_json = "[CONTEXT_PROVIDED_VIA_GEMINI_CACHE]"
elif observation:
    observation_json = json.dumps(observation, indent=2, ensure_ascii=False)

# AFTER:
observation_json = json.dumps(observation, indent=2, ensure_ascii=False) if observation else ""
```

Same change in `critic_agent._build_context`.

## 4. Unified Agent Prompt Injection

`visual_parts` no longer flows through agents. `visual_text` stays (for TEXT mode models).

```python
# session_agent.execute_session_cycle — AFTER:
def execute_session_cycle(self, observation, symbol, temperature, agent_name,
                          debate_history=None, tools=None,
                          visual_text=None, system_instruction=None):
    prompt = self._build_prompt(observation, debate_history)

    if visual_text:
        prompt = prompt + '\n\n' + visual_text

    return self._execute_ai_cycle(
        payload=[prompt],
        temperature=temperature,
        agent_name=agent_name,
        tools=tools,
        system_instruction=system_instruction,
    )
```

Same simplification in `critic_agent.evaluate`.

## 5. BaseAgent Simplification

Remove `cache_resource_name` from `_call_ai_provider` and `_execute_ai_cycle`.

```python
# _call_ai_provider — AFTER:
def _call_ai_provider(self, contents, temperature, agent_name,
                      tools, system_instruction):
    use_json_mode = not tools
    ...
    response = self.client.generate_content(
        model=self.model,
        contents=contents,
        system_instruction=system_instruction,
        tools=tools,
        temperature=temperature,
        response_json=use_json_mode,
        http_timeout=self.api_timeout,
    )
```

## 6. Orchestrator Lifecycle

```python
# execute_flow — key section:
visual_parts, visual_text = self._load_visual_assets(observation)

# Path correction for TEXT mode
if self._visual_mode == VisualMode.TEXT:
    vc = observation.get('visual_context', {})
    vc['macro_snapshot'] = vc.get('macro_snapshot_summary', vc.get('macro_snapshot', ''))
    vc['micro_snapshot'] = vc.get('micro_snapshot_summary', vc.get('micro_snapshot', ''))

# Session begin — adapter manages cache internally
tool_declarations = MathTools.get_tool_declarations()
self.client.begin_session(
    system_instruction=self.shared_instruction,
    tools=tool_declarations,
    visual_parts=visual_parts,
    model=self.shared_model,
)

try:
    self.debate_loop = DebateLoop(
        session_agent=self.session_agent,
        critic_agent=self.critic_agent,
        math_checker=self.math_checker,
        max_rounds=self.max_rounds,
        tools=tool_declarations,
        visual_text=visual_text,
        shared_instruction=self.shared_instruction,
        session_config=self.session_config,
        critic_config=self.critic_config,
    )
    debate_result = self.debate_loop.run(observation, symbol, progress_callback=progress_callback)

    final_decision = self._finalize_and_sanitize(
        debate_result, observation, symbol,
        tools=tool_declarations,
        visual_text=visual_text,
        progress_callback=progress_callback,
    )
finally:
    self.client.end_session()
```

## 7. Config Cleanup

```yaml
# global_config.yaml — DELETE:
#   context_cache:
#     enable: true
#     expiration_minutes: 10
```

`BinaryStarConfig` removes `enable_context_cache` and `cache_expiration_minutes` fields.

## 8. Deletion Summary

| Delete | File |
|--------|------|
| `GeminiCacheManager` (entire file) | `src/infrastructure/gemini/cache_manager.py` |
| `cache_resource_name` param (~15 occurrences) | `debate_loop.py`, `session_agent.py`, `critic_agent.py`, `base_agent.py` |
| `visual_parts` param from agents (~6 occurrences) | `session_agent.py`, `critic_agent.py` |
| `_prepare_agent_tools()` method | `binary_star_orchestrator.py` |
| `_cleanup_cache()` method | `binary_star_orchestrator.py` |
| `enable_context_cache` (config + code) | `global_config.yaml`, `BinaryStarConfig`, orchestrator |
| `cache_expiration_minutes` (config + code) | `global_config.yaml`, `BinaryStarConfig` |
| `create_cache()` / `delete_cache()` hooks | `ai_client.py`, `gemini_adapter.py` |
| `supports_context_cache` property | `ai_client.py`, `gemini_adapter.py`, `_openai_helpers.py` |
| `cache_manager` field + import | `binary_star_orchestrator.py` |

## 9. Self-Review

### 9.1 Placeholder scan
- No TBDs, TODOs, or incomplete sections.

### 9.2 Internal consistency
- `begin_session` / `end_session` paired in try/finally.
- `visual_parts` consumed once in `begin_session`, never stored in orchestrator after.
- `visual_text` stays in agent layer (prompt injection) — orthogonal to cache.
- `cache_resource_name` does not appear anywhere after refactor.
- `_active_cache_name` is GeminiAdapter-internal, never exposed.

### 9.3 Scope check
- Single subsystem: cache lifecycle relocation. ~12 files modified, 1 file deleted.

### 9.4 Ambiguity check
- `begin_session` is called BEFORE `DebateLoop` construction — if `begin_session` fails (e.g., network error), should we abort the entire session? Answer: yes. Cache creation failure means Gemini won't have cached context; the orchestrator should let the exception propagate and fail the cycle.
- `end_session` is in `finally` — ensures cleanup even on debate failure.
- Tools passed to `begin_session` must be in Gemini format (`types.Tool`). `MathTools.get_tool_declarations()` returns dicts. `GeminiAdapter._normalize_tools()` already handles this conversion.
