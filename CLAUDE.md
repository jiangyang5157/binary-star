# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Tests
python -m pytest tests/ -v
python -m pytest tests/ --cov=src --cov-report=term-missing

# Install
pip install -e .
pip install -e ".[dev]"

# ── CLI (run.py) ──  --symbol uses prefix format (BTC, XAUT); quote = USDT
python run.py session -p data/prod --symbol BTC                       # Live analysis
python run.py session -p data/prod --symbol BTC -ts 2026-06-01T12:34:00Z  # Historical
python run.py session --start T-15d --end T-1d --samples 14 --symbol BTC -p data/backtest/v26.6.24_r14

python run.py sniper -p data/prod --symbol BTC,XAUT                   # Observe only
python run.py sniper -p data/prod --symbol BTC,XAUT --llm             # + AI on trigger
python run.py sniper -p data/prod --symbol BTC,XAUT --trade [balance] # + AI + trade

python run.py audit -p data/prod
python run.py audit -p data/backtest --file data/backtest/.../BTCUSDT_session_....json

python run.py evolution -p data/prod --symbol BTC --samples 100
python run.py patch -f data/prod/evolution/proposals/BTCUSDT_evolution_....json [--symbol XAUT]

python -m src.dashboard.server --host 0.0.0.0 --port 8080 -p data/prod

# ── Scripts ──
python scripts/calculate_qty.py -b 1000 -f data/prod/sessions/XAUTUSDT_session_....json
python scripts/clean_neutral_sessions.py -p data/prod --symbol BTC,XAUT
python scripts/market_recon.py --symbol BTC -p data/prod
python scripts/render_email_html.py -p data/test -f data/prod/sessions/BTCUSDT_session_....json
python scripts/export_session.py -p data/test -f data/prod/audits/BTCUSDT_audit_....json
python scripts/check_margin_state.py
python scripts/sandbox_offline.py -p data/prod --symbol BTC --samples 20
python scripts/sandbox_online.py -p data/prod --symbol BTC
python scripts/diagnostic_models.py
```

## Architecture

**Singularity** — AI-driven crypto quantitative trading engine. Core innovation: **Binary Star adversarial protocol** — Session Analyst proposes trades, Critic Agent audits them, debating in rounds to converge on zero-entropy decisions. A third agent (Evolver) mutates strategy parameters from audit results.

### Layer stack

```
Entry Points (run.py + standalone run_*.py)
  → Dashboard (src/dashboard/)           FastAPI + Jinja2 templates, API routers, SessionRenderer (HTML email)
  → Sniper (src/sniper/)                 SniperScout, SniperTrigger + ConfluenceEngine (14-signal stack)
  → Orchestration (src/agent/)           DebateLoop, BinaryStarOrchestrator, BinaryStarConfig
  → Agents (src/agent/)                  SessionAgent, CriticAgent, EvolverAgent, EvolverSandbox
  → Trade Execution (src/agent/)         MarginOrderExecutor (order lifecycle + Guardian)
  → AI Backend (src/infrastructure/)     AbstractAIClient + AIFactory; adapters in ai/ (Gemini, DeepSeek, Qwen)
  → Exchange (src/infrastructure/)       AbstractExchangeClient → Binance (binance/client.py, margin_client.py), models (exchange/models.py)
  → Notifications (src/infrastructure/)  SessionNotifier, EmailDispatcher, AlertEmailTemplate
  → Market Analysis (src/analyzer/)      MarketObserver, VolumeProfile, MarketRegime, LiquidationEstimator,
                                         MathFactChecker, AuditAssembler, AuditController, ChartVisualRenderer,
                                         TopographyEngine, SniperSampler
  → Config (src/config/)                 Sub-config dataclasses, YAML loaders, symbol resolver
  → Utilities (src/utils/)               CongestionController, FitnessEvaluator,
                                         ConfigPatcher + PromptDistiller, exceptions, math tools
```

### AI backend

`AbstractAIClient` (`src/infrastructure/ai_client.py`) — contract for LLM providers. `AIFactory.create_client()` returns the right adapter from `global_config.yaml` → `llm.active_provider`. All agents depend on the interface, not any SDK.

- **`OpenAICompatibleAdapter`** (`src/infrastructure/ai/_openai_helpers.py`) — shared base for DeepSeek and Qwen. Adding a new OpenAI-compatible provider is a ~10-line subclass.
- **`GeminiAdapter`** (`src/infrastructure/ai/gemini_adapter.py`) — only adapter touching `google.genai` types. Only Gemini supports context caching (`supports_context_cache = True`).
- **`VisualPart`** — provider-agnostic multimodal type. Isolated from `google.genai.types` except inside `GeminiAdapter` and `GeminiCacheManager`.
- All entry points (`run.py`, `run_evolution.py`, `run_sniper.py`) must use `AIFactory.create_client()`, not raw SDK clients.

### Sniper + Guardian

Two-phase monitoring automaton. Entry point: `run.py sniper` (`SniperDaemon`).

- **Phase 1 — Scout + Trigger**: `SniperScout` harvests market data every 2 minutes. `SniperTrigger.evaluate()` runs the **ConfluenceEngine** over 14 signals across 5 categories (FLOW, ENERGY, STRUCTURAL, POSITIONING, CROSS-SYMBOL). Pre-trigger gate (`sniper.signal_stack.gate`) filters untradeable setups, notably `max_price_to_structure_atr` (independent of strategy-layer `max_entry_distance_atr`).
- **Phase 2 — AI Reasoning**: Binary Star debate (`run.py session`) generates trade blueprint on-demand.
- **Guardian** (`src/agent/order_executor.py` → `MarginOrderExecutor`): Runs EVERY pulse regardless of trigger. Protects positions with synthetic OCO, progressive trailing stops, adaptive time-stops, and emergency market-close fallback.

### Adversarial debate flow

1. `MarketObserver.observe()` collects klines, OI, liquidations, CVD → `observation` dict
2. `BinaryStarOrchestrator.execute_flow()`: injects regime benchmarks, optionally creates Gemini context cache (Truth Bus), then `DebateLoop.run()` alternates SessionAgent → MathFactChecker → CriticAgent → repeat until PASS/WEAK or `max_rounds`. Cold synthesis if max rounds reached without consensus.
3. Result archived as JSON in `<data_root>/sessions/`

### Config system

```
config/
├── strategy_config.yaml    # trading params, regime thresholds (evolvable)
├── global_config.yaml      # system, llm, binary_star, sniper, guardian, sandbox
├── visual_config.yaml      # chart appearance
├── symbol_config.yaml      # per-instrument precision + overrides (NOT evolved)
├── prompts/                # binary_star.md, session.md, critic.md, evolver.md
└── auth/users.json         # dashboard access control
```

- `src/config/sub_configs.py` — `RegimeConfig`, `TemporalConfig`, `RiskConfig`, `AuditConfig`, `VisualConfig`
- `src/config/symbol_resolver.py` — `resolve_config()`, `patch_config()`, `validate_symbol_configs()`
- **Resolution order**: base config + `symbol_config.yaml → <SYMBOL>.overrides` → deep-merge. Symbol overrides win.
- **Evolution patching**: `--symbol XAUT` patches symbol overrides first, then falls back to `strategy_config.yaml`. `symbol_config.yaml` is never evolved.

### Error handling

- `src/utils/exceptions.py` — `SingularityError` (base) → `AgentInferenceError` (`EmptyModelResponseError`, `MalformedJSONError`, `MaxIterationsError`, `AIProviderError`), `DataIntegrityError`, `ConfigurationError`
- `BaseAgent._execute_ai_cycle()` raises typed exceptions instead of returning error dicts

### Key invariants

- **`BinaryStarOrchestrator.execute_flow(observation, symbol)`** — public signature must not change
- **`GeminiCacheManager`** requires `GeminiAdapter`; gated by `enable_context_cache`
- **`run_evolution.py`** and **`run_sniper.py`** must use `AIFactory.create_client()`, not raw SDK clients
- **`get_tool_declarations()`** (`src/utils/math_utils.py`) — LLM function schemas must stay in sync with `_MathToolsNamespace`
- **`VisualPart`** is the only multimodal type in orchestrator/agent layer — `google.genai.types` isolated to `GeminiAdapter` + `GeminiCacheManager`
- **`MarginOrderExecutor`** — `sync_with_opinion()` and Guardian must never leave a position naked; emergency market-close is universal fallback
- **`CongestionController`** (`src/utils/rate_limiter.py`) — all exchange calls must go through rate limiting
