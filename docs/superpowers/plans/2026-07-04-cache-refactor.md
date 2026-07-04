# Cache Lifecycle Refactor — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move cache lifecycle into adapter (`begin_session`/`end_session`); remove `cache_resource_name` and `visual_parts` from agent/debate layers; unify observation JSON delivery across all models.

**Architecture:** Replace `GeminiCacheManager` + `cache_resource_name` plumbing with adapter-owned `begin_session`/`end_session`. All models send full observation JSON in prompt text. Gemini cache now only holds images + system_instruction + tools. Cache TTL hardcoded in `GeminiAdapter`.

**Tech Stack:** Python 3.13 — zero new dependencies.

## Global Constraints

- Prompt templates (`session.md`, `critic.md`, `binary_star.md`) — ZERO modifications
- `ChartGenerator`, `MarketObserver`, `VisualContextSummarizer` — ZERO modifications
- `global_config.yaml` — delete `context_cache` block only
- `build_messages()` / `_openai_helpers.py` — ZERO modifications
- No backward compatibility needed
- All models send full `observation_json` in prompt text (no placeholder)
- 276 existing tests must pass at every commit

---

### Task 1: Add `begin_session` / `end_session` to adapter interface + GeminiAdapter

**Files:**
- Modify: `src/infrastructure/ai_client.py:87-94` (replace `create_cache`/`delete_cache` with `begin_session`/`end_session`)
- Modify: `src/infrastructure/ai/gemini_adapter.py:156-166` (replace cache hooks with `begin_session`/`end_session` implementation)
- Modify: `src/infrastructure/ai/gemini_adapter.py:40-64` (`generate_content` — use `_active_cache_name`)

**Interfaces:**
- Produces: `AbstractAIClient.begin_session(system_instruction, tools, visual_parts, model) -> None`
- Produces: `AbstractAIClient.end_session() -> None`
- Deletes: `AbstractAIClient.create_cache()`, `AbstractAIClient.delete_cache()`
- Produces: `GeminiAdapter.CACHE_TTL_MINUTES = 10` class constant

- [ ] **Step 1: Replace interface in ai_client.py**

Replace lines 87-94:

```python
    # BEFORE:
    @property
    def supports_context_cache(self) -> bool:
        return False

    # Cache hooks (Gemini only — no-op by default)
    def create_cache(self, **kwargs) -> str | None:
        return None

    def delete_cache(self, name: str) -> bool:
        return False

    # AFTER:
    def begin_session(
        self,
        system_instruction: str | None = None,
        tools: list | None = None,
        visual_parts: list | None = None,
        model: str | None = None,
    ) -> None:
        """Prepare session context. Adapter may create cache, preload, etc."""
        pass

    def end_session(self) -> None:
        """Release session resources (cache, connections, etc.)."""
        pass
```

- [ ] **Step 2: Implement in GeminiAdapter**

Replace `gemini_adapter.py` lines 156-166 (`create_cache`/`delete_cache`) + add after `__init__`:

```python
class GeminiAdapter(AbstractAIClient):
    CACHE_TTL_MINUTES = 10

    def __init__(self, api_key: str, http_timeout: int = 240):
        self._client = genai.Client(
            api_key=api_key,
            http_options={'timeout': http_timeout * 1000},
        )
        self._active_cache_name: str | None = None   # ← NEW

    # ... properties unchanged ...

    def begin_session(self, system_instruction, tools, visual_parts, model):
        """Create context cache: images + system_instruction + tools only.
        
        Observation JSON intentionally excluded — all models send it in prompt text.
        """
        cache_contents: list = []
        for vp in (visual_parts or []):
            cache_contents.append(
                types.Part.from_bytes(data=vp.data, mime_type=vp.mime_type)
            )
        if not cache_contents:
            return  # nothing to cache

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
```

- [ ] **Step 3: Update GeminiAdapter.generate_content to use _active_cache_name**

In `generate_content()`, change:

```python
    # BEFORE:
    gen_config: dict[str, Any] = {"temperature": temperature}
    if tools:
        gen_config["tools"] = self._normalize_tools(tools)
    if response_json:
        gen_config["response_mime_type"] = "application/json"
    if system_instruction is not None:
        gen_config["system_instruction"] = system_instruction

    # AFTER:
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
```

- [ ] **Step 4: Verify**

```bash
cd /Users/yangjiang/Documents/workspace/crypto && python -m pytest tests/ -x -q 2>&1 | tail -3
```

Expected: 276 passed.

- [ ] **Step 5: Commit**

```bash
git add src/infrastructure/ai_client.py src/infrastructure/ai/gemini_adapter.py
git commit -m "feat: replace cache hooks with begin_session/end_session in adapter"
```

---

### Task 2: Remove `cache_resource_name` from BaseAgent

**Files:**
- Modify: `src/agent/base_agent.py:121-155` (`_call_ai_provider` — remove param, remove cache guard)
- Modify: `src/agent/base_agent.py:220-245` (`_execute_ai_cycle` — remove param, remove pass-through)

**Interfaces:**
- Consumes: `begin_session`/`end_session` from Task 1 (cache is now adapter-internal)
- Produces: `_call_ai_provider(contents, temperature, agent_name, tools, system_instruction)` (no cache param)
- Produces: `_execute_ai_cycle(payload, temperature, agent_name, tools, system_instruction)` (no cache param)

- [ ] **Step 1: Simplify `_call_ai_provider`**

```python
    # BEFORE:
    def _call_ai_provider(
        self, contents: list[Any], temperature: float, agent_name: str,
        cache_resource_name: str | None, tools: list[Any] | None,
        system_instruction: str | None,
    ) -> AIResponse:
        ...
        use_json_mode = not tools and not cache_resource_name
        ...
        response: AIResponse = retryer(
            self.client.generate_content,
            model=self.model, contents=contents,
            system_instruction=system_instruction if not cache_resource_name else None,
            tools=tools if not cache_resource_name else None,
            temperature=temperature,
            response_json=use_json_mode,
            http_timeout=self.api_timeout,
        )

    # AFTER:
    def _call_ai_provider(
        self, contents: list[Any], temperature: float, agent_name: str,
        tools: list[Any] | None, system_instruction: str | None,
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
        use_json_mode = not tools

        if self.congestion_controller:
            self.congestion_controller.pace(agent_name=agent_name)

        response: AIResponse = retryer(
            self.client.generate_content,
            model=self.model, contents=contents,
            system_instruction=system_instruction,
            tools=tools,
            temperature=temperature,
            response_json=use_json_mode,
            http_timeout=self.api_timeout,
        )
```

- [ ] **Step 2: Simplify `_execute_ai_cycle`**

```python
    # BEFORE:
    def _execute_ai_cycle(
        self, payload: str | list[Any], temperature: float | None = None,
        agent_name: str = "Agent",
        cache_resource_name: str | None = None,
        tools: list[Any] | None = None,
        system_instruction: str | None = None,
    ) -> dict[str, Any]:
        ...
        response = self._call_ai_provider(
            contents, temp, agent_name,
            cache_resource_name, tools, system_instruction,
        )

    # AFTER:
    def _execute_ai_cycle(
        self, payload: str | list[Any], temperature: float | None = None,
        agent_name: str = "Agent",
        tools: list[Any] | None = None,
        system_instruction: str | None = None,
    ) -> dict[str, Any]:
        ...
        response = self._call_ai_provider(
            contents, temp, agent_name,
            tools, system_instruction,
        )
```

Remove `cache_resource_name` from the docstring and method body.

- [ ] **Step 3: Verify**

```bash
cd /Users/yangjiang/Documents/workspace/crypto && python -m pytest tests/ -x -q 2>&1 | tail -3
```

Expected: 276 passed.

- [ ] **Step 4: Commit**

```bash
git add src/agent/base_agent.py
git commit -m "refactor: remove cache_resource_name from BaseAgent"
```

---

### Task 3: Clean up SessionAgent + CriticAgent

**Files:**
- Modify: `src/agent/session_agent.py:106-148` (`execute_session_cycle` — remove `cache_resource_name`, remove `visual_parts`, simplify payload)
- Modify: `src/agent/session_agent.py:150-182` (`_build_prompt` — remove `cache_resource_name` param, remove placeholder branch)
- Modify: `src/agent/critic_agent.py:91-138` (`evaluate` — remove `cache_resource_name`, remove `visual_parts`, simplify payload)
- Modify: `src/agent/critic_agent.py:140-180` (`_build_context` — remove `cache_resource_name` param, remove placeholder branch)

**Interfaces:**
- Consumes: `BaseAgent` without cache from Task 2
- Produces: `execute_session_cycle(..., visual_text=None, tools=None, system_instruction=None)` (no cache, no visual_parts)
- Produces: `evaluate(..., visual_text=None, tools=None, system_instruction=None)` (no cache, no visual_parts)

- [ ] **Step 1: Simplify session_agent.execute_session_cycle**

```python
    def execute_session_cycle(
        self,
        observation: Optional[Dict[str, Any]],
        symbol: str,
        temperature: float,
        agent_name: str,
        debate_history: Optional[List[Dict[str, Any]]] = None,
        tools: Optional[List[Any]] = None,
        visual_text: Optional[str] = None,
        system_instruction: Optional[str] = None
    ) -> Dict[str, Any]:
        """Core execution logic for a session reasoning step."""
        logger.info(f"[{symbol}] agent {agent_name} starting")
        try:
            prompt = self._build_prompt(
                observation=observation,
                debate_history=debate_history,
            )

            if visual_text:
                prompt = prompt + '\n\n' + visual_text

            return self._execute_ai_cycle(
                payload=[prompt],
                temperature=temperature,
                agent_name=agent_name,
                tools=tools,
                system_instruction=system_instruction
            )
        except Exception as e:
            logger.error(f"[{symbol}] agent {agent_name} failed | error={e}")
            raise
```

- [ ] **Step 2: Simplify session_agent._build_prompt**

```python
    def _build_prompt(
        self,
        observation: Optional[Dict[str, Any]],
        debate_history: Optional[List[Dict[str, Any]]] = None,
    ) -> str:
        """Internal logic for constructing the multimodal reasoning context."""
        if observation:
            observation_json = json.dumps(observation, indent=2, ensure_ascii=False)
        else:
            raise ValueError("Session: Reasoning attempted without market telemetry.")
        # ... rest unchanged ...
```

Delete `cache_resource_name` parameter and `if cache_resource_name: ... [placeholder]` branch.

- [ ] **Step 3: Simplify critic_agent.evaluate**

```python
    def evaluate(
        self,
        observation: Optional[Dict[str, Any]],
        last_plan: Dict[str, Any],
        symbol: str,
        debate_history: Optional[List[Dict[str, Any]]] = None,
        math_fact_check: Optional[Dict[str, Any]] = None,
        tools: Optional[List[Any]] = None,
        visual_text: Optional[str] = None,
        system_instruction: Optional[str] = None
    ) -> Dict[str, Any]:
        """Evaluates the proposed plan against physical market topography."""
        logger.info(f"[{symbol}] auditing proposal")
        try:
            context = self._build_context(
                observation, last_plan,
                debate_history=debate_history,
                math_fact_check=math_fact_check,
            )
            prompt = self._prepare_prompt(self.config.instruction_path, **context)

            if visual_text:
                prompt = prompt + '\n\n' + visual_text

            return self._execute_ai_cycle(
                payload=[prompt],
                temperature=self.config.model_temperature,
                agent_name="Critic_Evaluation",
                tools=tools,
                system_instruction=system_instruction,
            )
        except Exception as e:
            logger.error(f"[{symbol}] evaluation failed | error={e}")
            raise
```

- [ ] **Step 4: Simplify critic_agent._build_context**

```python
    def _build_context(
        self,
        observation: Optional[Dict[str, Any]],
        last_plan: Dict[str, Any],
        debate_history: Optional[List[Dict[str, Any]]] = None,
        math_fact_check: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Internal logic for constructing the adversarial audit context."""
        if observation:
            observation_json = json.dumps(observation, indent=2, ensure_ascii=False)
        else:
            raise ValueError("Critic: Audit attempted without baseline telemetry.")
        # ... rest unchanged ...
```

Delete `cache_resource_name` parameter and placeholder branch.

- [ ] **Step 5: Verify**

```bash
cd /Users/yangjiang/Documents/workspace/crypto && python -m pytest tests/ -x -q 2>&1 | tail -3
```

Expected: 276 passed.

- [ ] **Step 6: Commit**

```bash
git add src/agent/session_agent.py src/agent/critic_agent.py
git commit -m "refactor: remove cache_resource_name + visual_parts from SessionAgent and CriticAgent"
```

---

### Task 4: Clean up DebateLoop

**Files:**
- Modify: `src/agent/debate_loop.py:14-29` (`__init__` — remove `cache_resource_name`, remove `visual_parts`)
- Modify: `src/agent/debate_loop.py:62-73` (Session call — remove `cache_resource_name`, `visual_parts`)
- Modify: `src/agent/debate_loop.py:102-113` (Critic call — remove `cache_resource_name`, `visual_parts`)

**Interfaces:**
- Consumes: Cleaned SessionAgent/CriticAgent from Task 3
- Produces: `DebateLoop(..., tools, visual_text, shared_instruction, ...)` (no cache, no visual_parts)

- [ ] **Step 1: Update `__init__`**

```python
    def __init__(self, session_agent, critic_agent, math_checker: MathFactChecker,
                 max_rounds: int,
                 tools: list, shared_instruction: str,
                 session_config, critic_config,
                 visual_text: str | None = None):
        self.session_agent = session_agent
        self.critic_agent = critic_agent
        self.math_checker = math_checker
        self.max_rounds = max_rounds
        self.tools = tools
        self.shared_instruction = shared_instruction
        self.session_config = session_config
        self.critic_config = critic_config
        self.visual_text = visual_text
```

Remove: `cache_resource_name`, `visual_parts` from params and `self.cache_resource_name`, `self.visual_parts` from body.

- [ ] **Step 2: Update Session call in `run()`**

```python
    last_plan = self.session_agent.execute_session_cycle(
        observation=observation,
        symbol=symbol,
        temperature=self.session_config.model_temperature,
        agent_name=f"Session_Planning_R{current_round}",
        tools=self.tools,
        debate_history=compressed_history,
        visual_text=self.visual_text,
        system_instruction=self.shared_instruction,
    )
```

Remove `cache_resource_name=self.cache_resource_name` and `visual_parts=self.visual_parts`.

- [ ] **Step 3: Update Critic call in `run()`**

```python
    critic_results = self.critic_agent.evaluate(
        observation=observation,
        last_plan=last_plan,
        symbol=symbol,
        debate_history=compressed_history,
        math_fact_check=math_fact_check,
        tools=None,
        visual_text=self.visual_text,
        system_instruction=self.shared_instruction,
    )
```

Remove `cache_resource_name=self.cache_resource_name` and `visual_parts=self.visual_parts`.

- [ ] **Step 4: Verify**

```bash
cd /Users/yangjiang/Documents/workspace/crypto && python -m pytest tests/ -x -q 2>&1 | tail -3
```

Expected: 276 passed.

- [ ] **Step 5: Commit**

```bash
git add src/agent/debate_loop.py
git commit -m "refactor: remove cache_resource_name + visual_parts from DebateLoop"
```

---

### Task 5: Rewrite orchestrator lifecycle

**Files:**
- Modify: `src/agent/binary_star_orchestrator.py:8` (remove `GeminiCacheManager` import)
- Modify: `src/agent/binary_star_orchestrator.py:51-53` (remove `enable_context_cache`, `cache_expiration_minutes` from `BinaryStarConfig`)
- Modify: `src/agent/binary_star_orchestrator.py:89-92` (remove cache config parsing in `from_dicts`)
- Modify: `src/agent/binary_star_orchestrator.py:142-143` (remove cache fields from config construction)
- Modify: `src/agent/binary_star_orchestrator.py:228-229` (remove `self.enable_context_cache`, `self.cache_expiration_minutes`)
- Modify: `src/agent/binary_star_orchestrator.py:286-300` (remove `cache_manager` creation)
- Modify: `src/agent/binary_star_orchestrator.py:320-401` (`execute_flow` — replace `_prepare_agent_tools` + try/finally with `begin_session`/`end_session`)
- Modify: `src/agent/binary_star_orchestrator.py:445-469` (delete `_prepare_agent_tools`)
- Modify: `src/agent/binary_star_orchestrator.py:471-510` (`_finalize_and_sanitize` — remove `cache_resource_name`, `visual_parts` params)

**Interfaces:**
- Consumes: `begin_session`/`end_session` from Task 1, cleaned DebateLoop from Task 4
- Deletes: `gemini.cache_manager` import, `_prepare_agent_tools()`, `_cleanup_cache()`

- [ ] **Step 1: Remove cache from BinaryStarConfig**

Delete lines 51-53:
```python
    # ── Context cache ───────────────────────────────────────────────
    enable_context_cache: bool
    cache_expiration_minutes: int
```

Delete lines 89-92 in `from_dicts`:
```python
        # Context cache
        cache_cfg = provider_cfg.get("context_cache", {})
        enable_context_cache = bool(cache_cfg.get("enable", False))
        cache_expiration_minutes = int(cache_cfg.get("expiration_minutes", 10))
```

Delete lines 142-143 in config construction:
```python
            enable_context_cache=enable_context_cache,
            cache_expiration_minutes=cache_expiration_minutes,
```

- [ ] **Step 2: Remove orchestrator cache fields**

Delete lines 228-229:
```python
        self.enable_context_cache = bs_config.enable_context_cache
        self.cache_expiration_minutes = bs_config.cache_expiration_minutes
```

Delete lines 286-300 (cache manager creation block):
```python
        if self.enable_context_cache and self.client.supports_context_cache:
            self.cache_manager = GeminiCacheManager(
                adapter=self.client,
                congestion_controller=self.congestion_controller,
            )
        else:
            if self.enable_context_cache and not self.client.supports_context_cache:
                logger.info("non-Gemini provider detected, forcing enable_context_cache=False")
            self.cache_manager = None
```

Remove `from src.infrastructure.gemini.cache_manager import GeminiCacheManager` (line 8).

- [ ] **Step 3: Replace execute_flow cache logic**

Replace `execute_flow()` lines 329-401:

```python
        visual_parts, visual_text = self._load_visual_assets(observation)

        # Correct report visual_context paths for TEXT mode
        if self._visual_mode == VisualMode.TEXT:
            vc = observation.get('visual_context', {})
            vc['macro_snapshot'] = vc.get('macro_snapshot_summary', vc.get('macro_snapshot', ''))
            vc['micro_snapshot'] = vc.get('micro_snapshot_summary', vc.get('micro_snapshot', ''))

        tool_declarations = MathTools.get_tool_declarations()

        # Session begin — adapter manages cache internally
        self.client.begin_session(
            system_instruction=self.shared_instruction,
            tools=tool_declarations,
            visual_parts=visual_parts,
            model=self.shared_model,
        )

        try:
            # Debate Loop
            if progress_callback:
                progress_callback(stage=2, activity="Preparing AI context…")

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
            debate_result = self.debate_loop.run(observation, symbol,
                                                   progress_callback=progress_callback)

            # Finalize
            if progress_callback:
                progress_callback(stage=4, activity="Synthesizing decision…")

            final_decision = self._finalize_and_sanitize(
                debate_result, observation, symbol,
                tools=tool_declarations,
                visual_text=visual_text,
                progress_callback=progress_callback,
            )

            # Package
            project_root = resolve_project_root()
            config_path = os.path.join(project_root, 'config', 'strategy_config.yaml')
            return {
                "final_decision": final_decision,
                "debate_history": debate_result["debate_history"],
                "observation": observation,
                "metadata": {
                    "config_snapshot": self.config,
                    "version_control": {
                        "project_version": get_project_version(),
                        "git_commit": get_git_commit(),
                        "session_hash": get_file_hash(self.session_agent.config.instruction_path),
                        "critic_hash": get_file_hash(self.critic_agent.config.instruction_path),
                        "binary_star_hash": get_file_hash(self.bs_instruction_path),
                        "config_hash": get_file_hash(config_path)
                    }
                }
            }

        except Exception as e:
            logger.error(f"Binary Star flow failed | error={e}", exc_info=True)
            raise
        finally:
            self.client.end_session()
```

- [ ] **Step 4: Delete `_prepare_agent_tools` + `_cleanup_cache`**

Delete lines 445-469 (`_prepare_agent_tools`) and lines 519-525 (`_cleanup_cache`).

- [ ] **Step 5: Simplify `_finalize_and_sanitize`**

Remove `cache_resource_name` and `visual_parts` from signature and from `execute_session_cycle` call:

```python
    def _finalize_and_sanitize(self, debate_result: dict, observation: dict,
                               symbol: str,
                               tools: list,
                               visual_text: str | None,
                               progress_callback=None) -> dict:
        ...
        final_decision = self.session_agent.execute_session_cycle(
            observation=observation,
            symbol=symbol,
            temperature=self.critic_config.model_temperature,
            agent_name="Session_Synthesis",
            tools=tools,
            debate_history=self.debate_loop._compress_debate_history(debate_history),
            visual_text=visual_text,
            system_instruction=self.shared_instruction,
        )
```

- [ ] **Step 6: Verify**

```bash
cd /Users/yangjiang/Documents/workspace/crypto && python -m pytest tests/ -x -q 2>&1 | tail -3
```

Expected: 276 passed.

- [ ] **Step 7: Commit**

```bash
git add src/agent/binary_star_orchestrator.py
git commit -m "refactor: replace cache manager with adapter begin_session/end_session"
```

---

### Task 6: Delete GeminiCacheManager + config cleanup

**Files:**
- Delete: `src/infrastructure/gemini/cache_manager.py`
- Modify: `config/global_config.yaml` (delete `context_cache` block)
- Modify: `src/infrastructure/ai_client.py` (remove `supports_context_cache` property)
- Modify: `src/infrastructure/ai/gemini_adapter.py` (remove `supports_context_cache` property)
- Modify: `src/infrastructure/ai/_openai_helpers.py` (remove `supports_context_cache` property)

**Interfaces:**
- Deletes: `GeminiCacheManager` class
- Deletes: `context_cache` config section
- Deletes: `supports_context_cache` property from all adapters

- [ ] **Step 1: Delete GeminiCacheManager**

```bash
rm src/infrastructure/gemini/cache_manager.py
```

- [ ] **Step 2: Delete context_cache from config**

```yaml
# Before (lines 29-31):
#     context_cache:
#       enable: true
#       expiration_minutes: 10

# After: delete these 3 lines
```

- [ ] **Step 3: Remove `supports_context_cache` property**

Delete from `ai_client.py`:
```python
    @property
    def supports_context_cache(self) -> bool:
        return False
```

Delete from `gemini_adapter.py`:
```python
    @property
    def supports_context_cache(self) -> bool:
        return True
```

Delete from `_openai_helpers.py`:
```python
    @property
    def supports_context_cache(self) -> bool:
        return False
```

- [ ] **Step 4: Verify zero grep hits**

```bash
grep -rn "supports_context_cache\|enable_context_cache\|cache_expiration_minutes\|cache_resource_name\|GeminiCacheManager" src/ config/ 2>/dev/null
```

Expected: no output.

- [ ] **Step 5: Verify tests pass**

```bash
cd /Users/yangjiang/Documents/workspace/crypto && python -m pytest tests/ -x -q 2>&1 | tail -3
```

Expected: 276 passed.

- [ ] **Step 6: Commit**

```bash
git add -u src/infrastructure/gemini/cache_manager.py config/global_config.yaml src/infrastructure/ai_client.py src/infrastructure/ai/gemini_adapter.py src/infrastructure/ai/_openai_helpers.py
git commit -m "refactor: delete GeminiCacheManager, context_cache config, supports_context_cache"
```

---

### Final Verification

- [ ] **Full test suite:**

```bash
cd /Users/yangjiang/Documents/workspace/crypto && python -m pytest tests/ -v 2>&1 | tail -5
```

- [ ] **Stale reference sweep:**

```bash
grep -rn "cache_resource_name\|visual_parts\|cache_manager\|create_cache\|delete_cache\|enable_context_cache\|cache_expiration_minutes\|supports_context_cache\|CONTEXT_PROVIDED_VIA" src/ config/ 2>/dev/null
```

Expected: no output.
