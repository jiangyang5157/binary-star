# Modular Refactor + Dashboard Backend — Design Spec

**Date:** 2026-06-20  
**Status:** Approved  
**Goal:** Refactor the Singularity crypto trading engine for better decoupling, cleaner code structure, and richer HTML dashboards, while preserving all existing strategy logic.

---

## Target Architecture

```
┌─────────────────────────────────────────────────────────┐
│  Entry Points (run_session, run_sniper, run_evolution)  │
├─────────────────────────────────────────────────────────┤
│  Dashboard (FastAPI server, HTML templates, JSON API)    │  ← NEW
├─────────────────────────────────────────────────────────┤
│  Orchestration (DebateLoop, MathFactCheck, CacheMgr)     │  ← DECOMPOSED
├─────────────────────────────────────────────────────────┤
│  Agents (SessionAgent, CriticAgent via AbstractAIClient) │  ← DECOUPLED
├────────────────────┬────────────────────────────────────┤
│  AI Infrastructure │  Market Analysis                   │
│  AbstractAIClient  │  MarketObserver, VolumeProfile      │
│  Gemini/DeepSeek/  │  MarketRegime, LiquidationRadar     │
│  Qwen/Ollama       │                                    │
├────────────────────┴────────────────────────────────────┤
│  Data Layer (AbstractExchangeClient, Binance, Models)    │
├─────────────────────────────────────────────────────────┤
│  Config (unchanged YAML keys, cleaner code access)       │
└─────────────────────────────────────────────────────────┘
```

---

## Phase 1: AI Backend Decoupling

**Problem:** BaseAgent is tightly coupled to Google Gemini SDK (`genai.Client`, `types.Part`, `types.FunctionCall`). Non-Gemini adapters (DeepSeek, Qwen, Ollama) must construct fake Gemini-mock objects to satisfy the interface.

**Solution:** Introduce `AbstractAIClient` — an interface mirroring the pattern already used by `AbstractExchangeClient`.

### New interface (`src/infrastructure/ai_client.py`)

```python
@dataclass
class AIResponse:
    text: str
    tool_calls: list[dict] | None
    usage: dict

class AbstractAIClient(ABC):
    @abstractmethod
    def generate_content(self, model: str, contents: list, *,
        system_instruction: str = None,
        tools: list = None,
        temperature: float = 0.5,
        response_json: bool = False
    ) -> AIResponse: ...

    @property
    @abstractmethod
    def supports_context_cache(self) -> bool: ...
```

### Changes

- **`GeminiAdapter`** — new class wrapping `genai.Client`, returns `AIResponse`
- **`DeepSeekAdapter`** — simplified; drops ~80 lines of mock objects, implements interface directly
- **`QwenAdapter`** — same cleanup
- **`OllamaAdapter`** — same cleanup
- **`BaseAgent._execute_ai_cycle()`** — refactored to use `AbstractAIClient`; tool calls use plain dicts
- **`AIFactory`** — now returns `AbstractAIClient`
- **Re-home:** Move adapters to `src/infrastructure/ai/` sub-package

### Risk: Low
Behavior is preserved. Adapting existing adapters to a cleaner contract.

---

## Phase 2: Config Consolidation

**Problem:** SessionConfig (45 fields), CriticConfig (48 fields), MarketObserverConfig (50+ fields). ~30 fields duplicated between SessionConfig and CriticConfig. `from_dict()` methods are 100+ lines of repetitive extraction. Adding a parameter touches 5+ places.

**Solution:** Group into logical sub-config dataclasses while preserving all YAML keys and prompt template variables.

### Sub-configs

- **`RegimeConfig`** — trend thresholds, volatility ratios, squeeze params (~12 fields)
- **`TemporalConfig`** — time dilation factors and weights (~10 fields)
- **`RiskConfig`** — RR minimums, ATR buffers, structural armor (~8 fields)
- **`SentimentConfig`** — CVD, funding, OI thresholds (~6 fields)
- **`AuditConfig`** — MAE thresholds, missed opportunity params (~4 fields)
- **`VisualConfig`** — chart colors, DPI, layout weights (~15 fields)

### Changes

- **`SessionConfig`** — composed of `RegimeConfig`, `TemporalConfig`, `RiskConfig`, `SentimentConfig`, plus session-unique fields
- **`CriticConfig`** — composed of `RegimeConfig`, `TemporalConfig`, `RiskConfig`, `SentimentConfig`, plus critic-unique fields
- **`MarketObserverConfig`** — composed of sub-configs plus observer-unique fields
- **New `src/config/` package** — sub-config dataclasses, `from_yaml()` loader functions
- **YAML keys unchanged.** Prompt template variables unchanged.
- **Config files relocated:** `config/prompts/` for `.md` files (path update in `global_config.yaml` only)

### Risk: Low-Medium
Logic unchanged. Config loading is the highest-risk area — verify with integration tests against actual YAML files.

---

## Phase 3: Orchestrator Decomposition

**Problem:** `BinaryStarOrchestrator` is 727 lines. `__init__` constructs 10+ dependencies inline. `execute_flow()` is ~280 lines containing debate loop, context caching, math fact-checking, visual extraction, debate compression, and result packaging.

**Solution:** Extract three focused components.

### New components

- **`DebateLoop`** (`src/agent/debate_loop.py`) — runs the round-by-round adversarial cycle; owns `_compress_debate_history()` and `_evaluate_critic_fast_pass()`
- **`MathFactChecker`** (`src/analyzer/math_fact_checker.py`) — owns `_assemble_math_fact_check()` and regime scalar injection; pure deterministic math
- **`BinaryStarOrchestrator`** — reduced to construction coordination and a short `execute_flow()` sequence (~50 lines)

### Public API preserved

`BinaryStarOrchestrator.execute_flow(observation, symbol)` keeps the same signature and return type. `run_session.py` requires no changes.

### Risk: Medium
Core system logic is moving. Mitigations:
- Write integration tests for `DebateLoop` before extracting
- Move logic method-by-method, running tests after each move
- `execute_flow()` signature stays identical

---

## Phase 4: Dashboard Module

**Problem:** Current presentation is limited to single-session HTML emails and a basic ledger table. The user wants richer, better-looking HTML dashboards with a path toward a real-time web UI.

**Solution:** New `src/dashboard/` package with a FastAPI server that reads existing session/audit JSON files and renders rich HTML.

### Structure

```
src/dashboard/
  ├── __init__.py
  ├── server.py          # FastAPI app, route definitions
  ├── templates/
  │   ├── base.html       # Shared layout, dark theme
  │   ├── session.html    # Single session view
  │   ├── ledger.html     # Multi-session ledger
  │   └── index.html      # Session browser
  ├── static/
  │   └── dashboard.css   # Dark theme (#0d1117)
  └── api/
      ├── sessions.py     # /api/sessions — list, filter
      └── ledger.py       # /api/sessions/{id} — detail
```

### Views

- **Index** — date-ordered session list, filter by symbol/date, outcome badges
- **Session** — decision summary card, debate round accordion, embedded chart images, math fact-check table
- **Ledger** — sortable P&L table, MAE/MFE mini-bars, filter by outcome

### Design decisions

- Read-only over existing JSON files — no new data format
- Stateless HTTP only for now; `/api/` layer designed for future WebSocket/SSE relay
- Dark theme matching existing chart aesthetic (`#0d1117` background)
- `python -m src.dashboard.server` starts on `localhost:8080`
- `--path` flag to choose between `data/prod/` and `data/backtest/`
- New dependency: `fastapi` + `uvicorn` in `requirements.txt`
- Chart images served from existing files — no image regeneration

### Risk: Low
Purely additive. Read-only. No existing code paths modified.

---

## Phase 5: Test Reorganization

**Problem:** Tests are flat under `tests/`. Some test mocks rather than behavior. Tests aren't organized by scope.

**Solution:** Restructure into unit/integration/system layers.

### New structure

```
tests/
  ├── conftest.py
  ├── mock_factory.py
  ├── unit/
  │   ├── test_math_utils.py
  │   ├── test_json_utils.py
  │   ├── test_pipeline_utils.py
  │   ├── test_evolution_utils.py
  │   ├── test_config.py           # NEW
  │   └── test_datetime_utils.py   # if written
  ├── integration/
  │   ├── test_ai_client.py        # NEW
  │   ├── test_debate_loop.py      # NEW
  │   ├── test_market_regime.py
  │   └── test_calculate_qty.py
  └── system/
      ├── test_binary_star.py
      ├── test_adapters.py
      └── test_order_executor.py
```

### Test quality review

Each existing test evaluated against: "does this catch a real regression or document real behavior?" Tests that only test mocks or are too shallow to catch regressions will be dropped or rewritten.

### Risk: Low
Tests are safety net, not production code.

---

## Safety Boundaries (Read-Only)

These assets are treated as system logic and will not be modified:

- `config/strategy_config.yaml` — all keys, values, and structure preserved
- `config/global_config.yaml` — all keys and values preserved (one path update for prompt relocation)
- `src/agent/prompts/*.md` — content preserved; files may move to `config/prompts/`
- `MarketObserver`, `VolumeProfileAnalyzer`, `MarketRegimeAnalyzer`, `LiquidationRadar` — logic preserved
- `run_evolution.py`, `run_patch.py`, `run_audit.py` — no changes
- `SniperScout`, `SniperTrigger`, `SniperDaemon` — no changes
- `OrderExecutor`, `MarginOrderExecutor` — no changes

---

## Execution Order & Dependencies

```
Phase 1 (AI Decoupling) ──► Phase 2 (Config) ──► Phase 3 (Orchestrator) ──► Phase 4 (Dashboard)
                                                                              Phase 5 (Tests) runs in parallel
```

Each phase produces a working, tested system. No big-bang merge.

---

## Risk Thresholds

- **Low risk** — auto-proceed
- **Low-Medium risk** — auto-proceed with tests
- **Medium risk** — implement with integration tests before/after; flag if behavior diverges
- **Medium+ and above** — pause and ask
