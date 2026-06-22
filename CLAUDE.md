# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Run all tests (90 tests in unit/integration/system structure)
python -m pytest tests/ -v

# Run a single test file
python -m pytest tests/unit/test_math_utils.py -v

# Run tests with coverage
python -m pytest tests/ --cov=src --cov-report=term-missing

# Install from pyproject.toml
pip install -e .
pip install -e ".[dev]"

# Start the dashboard server (http://localhost:8080)
python -m src.dashboard.server
python -m src.dashboard.server -p data/prod --port 8080

# ── Unified CLI (run.py) ─────────────────────────────────────────────

# Live analysis
python run.py session

# Single historical snapshot
python run.py session -ts 2026-01-24T15:42:00Z

# Backtest (sampled historical points)
python run.py session --start T-30d --end T-2d --samples 14 --sampling-mode sniper

# Real-time monitoring daemon
python run.py sniper --trigger --email
python run.py sniper --trigger --email --trade

# Forensic audit
python run.py audit -p data/prod
python run.py audit -p data/backtest --file <session_file>.json

# Strategy meta-evolution
python run.py evolution -p data/backtest --samples 20

# Apply evolution patch
python run.py patch -f <evolution_file>.json
```

## Architecture

This is **Singularity** — an AI-driven crypto quantitative trading engine. Its core innovation is the **Binary Star adversarial protocol**: two LLM agents (Session Analyst proposing trades, Critic Agent auditing them) debate in rounds to converge on zero-entropy trade decisions. A third agent (Evolver) uses audit results to mutate strategy parameters.

### Layer stack

```
Entry Points (run.py + standalone run_*.py)
  → Dashboard (src/dashboard/)           FastAPI + Jinja2 templates, API routers, static assets
  → Orchestration (src/agent/)           DebateLoop, BinaryStarOrchestrator, BinaryStarConfig
  → Agents (src/agent/)                  SessionAgent, CriticAgent, EvolverAgent, EvolverSandbox
  → AI Backend (src/infrastructure/)     AbstractAIClient + AIFactory at root; adapters in ai/ (Gemini, DeepSeek, Qwen)
  → Exchange (src/infrastructure/)       AbstractExchangeClient → Binance (binance/), models (exchange/models.py)
  → Notifications (src/infrastructure/)  EmailNotifier
  → Market Analysis (src/analyzer/)      MarketObserver, VolumeProfile, MarketRegime, LiquidationRadar,
                                         MathFactChecker, AuditAssembler, AuditController, ChartGenerator,
                                         TopographyEngine, SimulationSampler
  → Config (src/config/)                 Sub-config dataclasses + YAML loaders
```

### AI backend (key design pattern)

`AbstractAIClient` (in `src/infrastructure/ai_client.py`) is the contract — mirrors the `AbstractExchangeClient` pattern for LLM providers. All agents depend on the interface, not any SDK. `AIFactory.create_client()` (in `src/infrastructure/ai_factory.py`) returns the right adapter based on `global_config.yaml` → `llm.active_provider`.

- **`src/infrastructure/ai/`** — adapter implementations only: `GeminiAdapter`, `DeepSeekAdapter`, `QwenAdapter`, plus `_openai_helpers.py`.
- **`OpenAICompatibleAdapter`** — shared base class for DeepSeek and Qwen. Adding a new OpenAI-compatible provider is a ~10-line subclass.
- **`VisualPart`** — provider-agnostic multimodal content type (defined in `ai_client.py`). The orchestrator and agents use this; only `GeminiAdapter` and `GeminiCacheManager` convert to Gemini-native `types.Part`.
- **`GeminiAdapter`** — the only adapter that touches `google.genai` types. Exposes `.raw_client` for cache operations. Only Gemini supports context caching (`supports_context_cache = True`).

### Adversarial debate flow

1. `MarketObserver.observe()` collects klines, OI, liquidations, CVD → `observation` dict
2. `BinaryStarOrchestrator.execute_flow()`:
   - Injects regime benchmarks into observation
   - Optionally creates Gemini context cache (Truth Bus)
   - `DebateLoop.run()` alternates: SessionAgent proposes → MathFactChecker verifies → CriticAgent audits → repeat until PASS/TERMINAL or `max_rounds`
   - Final synthesis at cold temperature, sanitized against math truth
3. Result archived as JSON in `<data_root>/sessions/`

### Config system

- `config/strategy_config.yaml` — trading parameters, regime thresholds, analysis windows
- `config/global_config.yaml` — system settings, LLM provider config, visuals, sniper
- `config/visual_config.yaml` — chart appearance, color themes, visual rendering options
- `config/prompts/*.md` — LLM system prompts: `session.md`, `critic.md`, `evolver.md`, `binary_star.md` (sensitive system logic)
- `src/config/sub_configs.py` — `RegimeConfig`, `TemporalConfig`, `RiskConfig`, `AuditConfig`, `VisualConfig` (frozen dataclasses)
- `src/config/loader.py` — builds sub-configs from YAML dicts
- `src/agent/binary_star_orchestrator.py` — `BinaryStarConfig.from_dicts()` factory consolidates all config resolution
- `src/analyzer/market_observer.py` — `ObserverTopographyConfig`, `ObserverRadarConfig`, `ObserverVisualConfig` group the 67 original flat fields

### Error handling

- `src/utils/exceptions.py` — domain exception hierarchy: `SingularityError` (base) → `AgentInferenceError` (agent failures: `EmptyModelResponseError`, `MalformedJSONError`, `MaxIterationsError`, `AIProviderError`), `DataIntegrityError`, `ConfigurationError`
- `BaseAgent._execute_ai_cycle()` raises typed exceptions instead of returning error dicts

### Key invariants

- **`BinaryStarOrchestrator.execute_flow(observation, symbol)`** — public signature must not change
- **`GeminiCacheManager`** (`src/infrastructure/gemini/cache_manager.py`) requires `GeminiAdapter` (only Gemini supports context caching); guarded by `self.enable_context_cache` check
- **`run_evolution.py`** (and `run.py evolution`) must use `AIFactory.create_client()`, not raw SDK clients
- Non-Gemini adapters return `False` for `supports_context_cache`
- **`MathTools`** (`src/utils/math_utils.py`) — tool function declarations via `get_tool_declarations()` must stay in sync with actual implementations
- `VisualPart` is the only multimodal type in the orchestrator/agent layer — `google.genai.types` is isolated to `GeminiAdapter` and `GeminiCacheManager`
