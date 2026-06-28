# Singularity

[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)

AI-driven crypto quantitative trading engine. Its core innovation is the **Binary Star adversarial protocol**: two LLM agents (Session Analyst proposing trades, Critic Agent auditing them) debate in rounds to converge on zero-entropy trade decisions. A third agent (Evolver) uses forensic audit results to mutate strategy parameters via sandbox-validated evolutionary patches.

A lightweight **Sniper daemon** monitors market topography at 2-minute pulses. Its 14-signal confluence engine only activates the heavyweight Binary Star reasoning engine when signal stacking exceeds a regime-adaptive threshold — saving LLM tokens during quiet markets.

---

## Architecture

```mermaid
graph TD
    CLI["CLI / Dashboard"]

    CLI -->|"sniper"| Daemon["SniperDaemon<br/>2-min pulse loop"]
    CLI -->|"session"| BSO["BinaryStarOrchestrator<br/>adversarial debate wire"]

    Daemon --> Scout["SniperScout<br/>harvest klines, OI, CVD"]
    Scout --> Trigger["SniperTrigger<br/>14-signal confluence"]
    Trigger -->|"score ≥ threshold"| BSO

    BSO --> Observer["MarketObserver<br/>full topography + charts"]
    Observer --> Exchange["Binance<br/>FuturesClient (data) | MarginClient (trade)"]

    BSO --> Debate["DebateLoop<br/>adversarial rounds"]
    Debate --> SA["SessionAgent<br/>Thesis (temp 0.5)"]
    Debate --> CA["CriticAgent<br/>Antithesis (temp 0.1)"]
    BSO --> MFC["MathFactChecker<br/>deterministic verify"]
    SA & CA --> AI["LLM Provider<br/>Gemini | DeepSeek | Qwen"]

    BSO --> Executor["MarginOrderExecutor<br/>OCO + Guardian + trailing stop"]
    Executor --> Exchange

    CLI -->|"audit"| Audit["AuditController<br/>forensic batch audit"]
    Audit --> Observer
    Audit -->|"reports"| Evolver["EvolverAgent<br/>strategy mutation"]
    Evolver -->|"patches"| Config["Config System<br/>strategy + global + symbol overrides"]

    Config -.-> Trigger
    Config -.-> Scout
    Config -.-> Observer
    Config -.-> BSO
    Config -.-> Executor
```

### Layer Descriptions

| Layer | Module | Role |
|-------|--------|------|
| **Entry Points** | `run.py`, `run_*.py` | CLI + standalone scripts; each `run_*.py` is independently invocable |
| **Dashboard** | `src/dashboard/` | FastAPI server, Jinja2 templates, REST API for session/sniper/audit/backtest |
| **Orchestration** | `binary_star_orchestrator.py`, `debate_loop.py` | Wires MarketObserver → DebateLoop → MathFactChecker → SessionAgent → CriticAgent |
| **AI Agents** | `session_agent.py`, `critic_agent.py`, `evolver_agent.py` | LLM agents for trade thesis, adversarial critique, and strategy evolution |
| **Sniper** | `src/sniper/` | Lightweight pulse monitor: Scout harvests market data, Trigger evaluates 14-signal confluence |
| **Trade Execution** | `src/agent/order_executor.py` | MarginOrderExecutor: position cross-referencing, synthetic OCO, Guardian trailing stops |
| **Market Analysis** | `src/analyzer/` | Volume profile, regime detection, math fact-checking, forensic audit assembly, topography |
| **AI Backend** | `src/infrastructure/ai_client.py`, `ai_factory.py`, `ai/` | Provider-agnostic `AbstractAIClient` → Gemini, DeepSeek, Qwen adapters |
| **Exchange** | `src/infrastructure/binance/` | Futures (market data) + Margin (trade execution) clients |
| **Config** | `src/config/` | Frozen dataclasses (sub_configs.py), YAML loaders, symbol-aware resolution + patching |
| **Utilities** | `src/utils/` | Math tools, datetime, evolution patching, fitness evaluation, rate limiting, logging |

---

## The Binary Star Protocol

Every final trade instruction must survive adversarial debate — purifying chaotic market conditions into deterministic low-entropy parameters.

```mermaid
sequenceDiagram
    participant MO as MarketObserver
    participant BSO as BinaryStarOrchestrator
    participant CM as CacheManager
    participant DL as DebateLoop
    participant SA as SessionAgent
    participant MFC as MathFactChecker
    participant CA as CriticAgent

    MO->>BSO: observe(symbol) → topography + metrics
    BSO->>CM: create market cache (Truth Bus)
    BSO->>DL: run(observation, symbol)

    loop Debate Rounds (1..max_rounds)
        DL->>SA: planning/refinement (temperature=0.5)
        SA-->>DL: {opinion, confidence, tactical_parameters}
        DL->>MFC: verify(plan, observation)
        MFC-->>DL: {status, rr_ratio, compliance_verdict}
        DL->>CA: evaluate(plan, observation, math_result)
        CA-->>DL: {veto_level: PASS|WEAK|CONSTRUCTIVE|TERMINAL}
        alt PASS or WEAK
            DL-->>BSO: early_exit=True
        else CONSTRUCTIVE or TERMINAL
            DL->>DL: compress history, next round
        end
    end

    opt max_rounds exhausted (no consensus)
        DL->>SA: cold synthesis (temperature=0.3)
        SA-->>DL: synthesized final decision
    end

    DL-->>BSO: {final_decision, debate_history, metadata}
    BSO->>CM: delete market cache
    BSO-->>Session: archive session JSON
```

### Debate Mechanics

1. **Pre-Flight**: MarketObserver harvests klines, OI, liquidations, funding rates. ChartGenerator renders annotated chart images. Regime benchmarks (effective velocity, temporal dilation) are pre-calculated and injected into the observation.

2. **Debate Rounds** (max 2 by default):
   - **Round 1** — SessionAgent proposes a trade blueprint at temperature 0.5 (creative exploration)
   - **MathFactChecker** verifies the geometry deterministically (RR, ATR distances, structural shielding)
   - **CriticAgent** audits the plan at temperature 0.1 (cold logic) against its CRITIC_CODES table
   - **Round 2+** — SessionAgent refines based on critique tags, Critic re-audits
   - **Early Exit** — PASS or WEAK veto terminates the loop immediately

3. **Finalization**: If max_rounds exhausted without consensus, a cold synthesis call (temperature 0.3) processes compressed debate history for hardened output. The result is always run through MathFactChecker one final time to sanitize hallucinated values.

4. **Output**: Structured trade decision with opinion, entry/TP/SL levels, confidence score, and debate history.

### Critic Audit Dimensions (18 Codes)

The CriticAgent applies a structured CRITIC_CODES table. When multiple codes fire, the most severe veto level dominates: **TERMINAL > CONSTRUCTIVE > WEAK > PASS**.

| # | Category | Tag | Veto | What It Checks |
|---|----------|-----|------|----------------|
| 1 | Pristine | `[PRISTINE]` | PASS | SL shielded behind structural anchor AND RR valid |
| 2 | Justified Inaction | `[JUSTIFIED_INACTION]` | PASS | Neutral stance is defensible (prior terminal veto or unsolvable contradiction) |
| 3 | Order Physics | `[ORDER_PHYSICS]` | TERMINAL | Entry on wrong side of current price OR SL on wrong side of entry |
| 4 | Structural Trap | `[STRUCTURAL_TRAP]` | TERMINAL | Entry sits in a volume vacuum zone |
| 5 | Anchor/Shield Failure | `[ANCHOR_VIOLATION]` | TERMINAL | SL not behind structural anchor, or anchor not between entry and SL |
| 6 | Logic Loop | `[PROTOCOL_VIOLATION]` | TERMINAL | Session repeated a failed plan pattern without paradigm shift |
| 7 | Retail Long Squeeze | `[RETAIL_LONG_SQUEEZE]` | TERMINAL | Bearish sentiment + bullish plan at resistance with retail long crowding |
| 8 | Retail Short Squeeze | `[RETAIL_SHORT_SQUEEZE]` | TERMINAL | Bullish sentiment + bearish plan at support with retail short crowding |
| 9 | Math Violation | `[MATH_VIOLATION]` | CONSTRUCTIVE | RR below minimum threshold, or entry-to-SL exceeds POC gravity distance |
| 10 | Inaction Bias | `[INACTION_BIAS]` | CONSTRUCTIVE | Market is squeezable or price extreme — neutral stance may be cowardly |
| 11 | Opportunity Denial | `[OPPORTUNITY_DENIAL]` | CONSTRUCTIVE | Strong directional CVD flow exists without absorption risk |
| 12 | Trend Starvation | `[TREND_STARVATION]` | CONSTRUCTIVE | Clear trend with momentum — neutral is forfeiting alpha |
| 13 | Gravity Exhaustion | `[GRAVITY_EXHAUSTION]` | CONSTRUCTIVE | Trading toward distant POC without momentum backing |
| 14 | Volatility Chop | `[VOLATILITY_CHOP]` | CONSTRUCTIVE | High noise regime — targets should tighten |
| 15 | Flow Violation | `[FLOW_VIOLATION]` | CONSTRUCTIVE | CVD flow opposes trade direction without mitigation |
| 16 | Over-Extension | `[OVER_EXTENSION]` | CONSTRUCTIVE | Projected holding time exceeds regime-adjusted maximum |
| 17 | Liquidity Void | `[LIQUIDITY_VOID]` | CONSTRUCTIVE | SL sits in a liquidity vacuum (near LVN) |
| 18 | Absorption Trap | `[CVD_ABSORPTION]` | WEAK | CVD absorption against trade direction (smart money absorbing opposite flow) |

### MathFactChecker: Deterministic Verification

A pure-Python engine that validates AI-generated coordinates before any exchange action:

| Check | Method | What It Verifies |
|-------|--------|-----------------|
| **RR Ratio** | `calculate_risk_reward()` | `abs(tp - entry) / abs(entry - sl)` ≥ regime-adjusted minimum |
| **ATR Normalization** | `calculate_atr_metrics()` | SL/TP distances in ATR units; SL must be within `poc_gravity_atr_distance` (3.5 ATR) |
| **Structural Shielding** | `calculate_structural_proximity()` | SL must be anchored behind POC, VAH/VAL, or HVN with buffer ≥ `structural_buffer_atr` (0.84 ATR) |
| **Holding Time** | `project_holding_time()` | Flight time × temporal dilation; used for entry expiry and time-based stops |

Regime-adaptive minimum RR:
| Regime | Min RR | Notes |
|--------|--------|-------|
| Trending | 1.12 | Higher bar — trend has inertia, demand better payout |
| Ranging | 1.00 | Standard — noise is symmetric |
| Chaos | 0.65 (discounted) | Survival mode — allow low-RR plans, tight stops |

---

## Sniper System

The Sniper is a lightweight daemon that monitors market topography at 2-minute pulses. It only activates the heavyweight Binary Star reasoning engine when signal confluence exceeds a regime-adaptive threshold — saving LLM tokens during quiet markets.

### Signal Stack (14 Detectors × 5 Categories)

| # | Signal | Category | Weight | Half-Life | Description |
|---|--------|----------|--------|-----------|-------------|
| 1 | `cvd_momentum` | FLOW | 0.65 | 6 min | CVD intensity exceeds threshold, growing vs previous pulse |
| 2 | `cvd_divergence` | FLOW | 0.70 | 4 min | Price-CVD divergence: smart money vs retail direction mismatch |
| 3 | `cvd_absorption` | FLOW | 0.65 | 10 min | Extreme CVD with flat price — iceberg absorption detected |
| 4 | `taker_imbalance` | FLOW | 0.60 | 4 min | Taker buy/sell ratio derived from CVD intensity (>0.60 ratio) |
| 5 | `volatility_surge` | ENERGY | 0.55 | 20 min | VII > baseline + volume surge — breakout energy (no inherent direction) |
| 6 | `squeeze` | ENERGY | 0.75 | 20 min | BB squeeze below threshold — compressed spring, breakout precursor |
| 7 | `boundary_test` | STRUCTURAL | 0.50 | 10 min | Price within 0.70 ATR of VAH/VAL with volume participation |
| 8 | `poc_gravity` | STRUCTURAL | 0.55 | 10 min | Price within 0.50 ATR of POC — mean-reversion magnet |
| 9 | `liquidation_hunt` | STRUCTURAL | 0.60 | 10 min | Price within 0.40 ATR of liquidation cluster — sweep incoming |
| 10 | `trend_pullback` | STRUCTURAL | 0.75 | 10 min | Price pulling back to HVN in strong trend (intensity ≥ 0.35) |
| 11 | `retail_extreme` | POSITIONING | 0.42 | 60 min | LS ratio >1.5 or <0.6, or funding extreme — contrarian |
| 12 | `oi_divergence` | POSITIONING | 0.70 | 15 min | OI and price moving opposite directions — positioning reversal signal |
| 13 | `oi_surge` | POSITIONING | 0.55 | 20 min | OI and price moving same direction — trend continuation |
| 14 | `leader_sync` | CROSS_SYMBOL | 0.40 | 8 min | Correlated leader symbol triggered — boost follower signals |

### Confluence Engine

Signals stack directionally using **1 − ∏(1 − sᵢ · wᵢ)**, with noise cancellation via cross-direction product (`noise_factor = 1 − bullish × bearish`). Single signals below 0.15 strength are ignored. Regime-adaptive thresholds:

| Regime | Modifier | Effective Threshold | Rationale |
|--------|----------|--------------------|-----------|
| `squeeze` | 0.75 | 0.26 | Lowest — compression is breakout precursor, position early |
| `trending` | 0.85 | 0.30 | Trend has inertia — lower bar for high-conviction signals |
| `ranging` | 1.00 | 0.35 | Neutral — noise is symmetric, no bias |
| `chaos` | 1.50 | 0.53 | Near-lockout — only emergency override (strength ≥ 0.80) breaks through |

### Pulse Flow

```mermaid
graph TD
    PULSE["⏰ 2-min Pulse"] --> H["① Heartbeat<br/>write .sniper_alive.json"]
    H --> G["② Guardian Check<br/>per-symbol position protection"]
    G --> S["③ Scout<br/>harvest: klines, OI, CVD, liquidations"]
    S --> T["④ Trigger Evaluation<br/>13 detectors → memory merge → confluence → cooldown → gate"]
    T --> LS["⑤ Leader Sync<br/>leader trigger → boost correlated followers"]
    LS --> AI{"⑥ Any symbol<br/>triggered?"}
    AI -->|"yes"| SESSION["⑦ AI Session<br/>Binary Star debate → trade execution"]
    AI -->|"no"| SLEEP["Sleep 2 min"]
    SESSION --> SLEEP
    SLEEP --> PULSE
```

### Pre-AI Gate (Deterministic Filters)

Before spending LLM tokens, four hard checks validate tradability:

| Gate | Check | Rejects |
|------|-------|---------|
| **Entry Feasibility** | Distance to nearest HVN ≤ `max_price_to_structure_atr` (4.0 ATR) | Plans too far from structural support |
| **Directional Sanity** | Counter-trend trades require CVD confirmation | Fading strong trends without flow backing |
| **Chaos Survival** | Directional momentum signals blocked in chaos unless squeeze/absorption present | Momentum-based entries in chaotic markets |
| **RR Feasibility** | Minimum price distance exists for valid RR setup | Trades where stop distance makes RR impossible |

### Adaptive Cooldown

After a trigger, cooldown prevents spam. Duration adapts to regime:

| Regime | Cooldown | Break Conditions |
|--------|----------|-----------------|
| `trending` | 25 min | 3+ stacked signals, or strength > last × 1.8 |
| `ranging` | 45 min | Same break conditions |
| `squeeze` | 25 min | Same break conditions |
| `chaos` | 60 min | Emergency override only (strength ≥ 0.80) |

Absolute minimum gap between triggers: **10 minutes**.

### Leader Sync (Cross-Symbol Cascade)

When a leader symbol triggers, its correlated followers get a signal boost:
- **ETHUSDT**: correlation 0.75, boost factor 0.30
- **XAUTUSDT**: correlation 0.40, boost factor 0.30

Followers only trigger if the boosted confluence exceeds their regime threshold.

### Guardian: Position Protection

Every pulse cycle, Guardian checks and protects open positions — no AI involvement:

| State | Action |
|-------|--------|
| **Flat, no trade state** | No-op |
| **Entry pending, not expired** | Wait (elapsed < projected_waiting_hours) |
| **Entry expired** | Cancel entry order, clear trade state |
| **Position filled, unprotected** | Check SL not already breached → place synthetic OCO (TP limit + SL limit). If price already crossed SL: emergency market close |
| **Position filled, protected** | Proceed to trailing stop migration check |
| **SL breached** | Emergency market close |
| **Position flat (was filled)** | Cancel all orders, clear state |

### Trailing Stop Migration (3-Tier)

When profit exceeds ATR-based thresholds, Guardian progressively migrates the stop-loss:

| Tier | Profit (ATR) | SL Position | Rationale |
|------|-------------|-------------|-----------|
| Level 1 | ≥ 1.5 ATR | SL → entry (breakeven) | Lock in safety |
| Level 2 | ≥ 2.5 ATR | SL → entry ± 0.5 ATR | Capture partial profit |
| Level 3 | ≥ 4.0 ATR | SL → entry ± 1.5 ATR | Trail aggressively |

**Migration is forward-only**: target_level must be strictly > current_level. Monotonicity (`0 < l1 < l2 < l3`, `0 < o2 < o3`) is validated at init.

**Time Stop** (ATR-adaptive): Holding limit adjusts to volatility changes. If `current ATR > entry ATR` (rising vol), the limit compresses proportionally. Formula: `max_hold = (projected_holding_hours / atr_ratio) × time_stop_multiplier` (1.5).

### Position × Opinion Cross-Reference

`sync_with_opinion()` resolves new AI opinions against existing positions:

| Current Position | AI Opinion | Action |
|-------------------|------------|--------|
| Flat | NEUTRAL | No action |
| Flat | BULLISH/BEARISH | Cancel stale orders → place new LIMIT entry |
| LONG/SHORT | Same direction | Optimize: merge TP (max of both), tighten SL, replace OCO |
| LONG | BEARISH (has SL) | **Pivot-Preserve**: align TP to entry, keep original SL, place new SHORT LIMIT entry |
| LONG | BEARISH (no SL) | **Force Close**: market close, cancel all orders, place new SHORT LIMIT entry |
| SHORT | BULLISH (has SL) | **Pivot-Preserve**: align TP to entry, keep original SL, place new LONG LIMIT entry |
| SHORT | BULLISH (no SL) | **Force Close**: market close, cancel all orders, place new LONG LIMIT entry |

### Order Lifecycle

```mermaid
stateDiagram-v2
    [*] --> IDLE

    IDLE --> ENTRY_PENDING: AI opinion<br/>place LIMIT order
    ENTRY_PENDING --> IDLE: timeout<br/>(elapsed > projected_waiting)

    ENTRY_PENDING --> IN_POSITION: fill confirmed

    IN_POSITION --> EMERGENCY_CLOSE: SL breached<br/>before OCO placed
    IN_POSITION --> PROTECTED: OCO placed<br/>(TP limit + SL limit)

    PROTECTED --> TRAILING_L1: profit ≥ 1.5 ATR<br/>SL → breakeven
    PROTECTED --> TRAILING_L2: profit ≥ 2.5 ATR<br/>SL → entry + 0.5 ATR
    PROTECTED --> TRAILING_L3: profit ≥ 4.0 ATR<br/>SL → entry + 1.5 ATR

    TRAILING_L1 --> TRAILING_L2: profit ≥ 2.5 ATR
    TRAILING_L2 --> TRAILING_L3: profit ≥ 4.0 ATR

    PROTECTED --> IDLE: TP hit | SL hit | time stop
    TRAILING_L1 --> IDLE: TP hit | SL hit | time stop
    TRAILING_L2 --> IDLE: TP hit | SL hit | time stop
    TRAILING_L3 --> IDLE: TP hit | SL hit | time stop

    PROTECTED --> EMERGENCY_CLOSE: OCO re-place failed
    TRAILING_L1 --> EMERGENCY_CLOSE: OCO re-place failed
    TRAILING_L2 --> EMERGENCY_CLOSE: OCO re-place failed
    TRAILING_L3 --> EMERGENCY_CLOSE: OCO re-place failed

    EMERGENCY_CLOSE --> IDLE: market close executed<br/>state cleared
```

---

## AI Providers

`AbstractAIClient` defines the provider-agnostic contract. `AIFactory.create_client()` resolves the active provider from `global_config.yaml` → `llm.active_provider`.

| Provider | Adapter | Default Model | Vision | Context Cache | Reasoning Content | Notes |
|----------|---------|---------------|--------|---------------|-------------------|-------|
| **DeepSeek** | `deepseek_adapter.py` | `deepseek-v4-pro` | No | No | Yes | OpenAI-compatible; `reasoning_content` extracted from responses |
| **Gemini** | `gemini_adapter.py` | `gemini-3.5-flash` | Yes | Yes | No | Context cache (Truth Bus) for multi-turn debate efficiency |
| **Qwen** | `qwen_adapter.py` | `qwen3.7-max` | Configurable | No | Yes | OpenAI-compatible; set `supports_vision: true` for VL models |

### Provider-Agnostic Data Types

```python
@dataclass
class AIResponse:
    text: str
    tool_calls: list[ToolCall] | None
    usage: UsageMetadata | None
    reasoning_content: str | None  # DeepSeek/Qwen thinking models

@dataclass
class VisualPart:           # Provider-agnostic image/chart
    mime_type: str
    data: bytes
    label: str | None
```

### Agent Temperature Strategy

| Role | Temperature | Purpose |
|------|------------|---------|
| SessionAgent (planning rounds) | 0.5 | Creative hypothesis generation |
| SessionAgent (cold synthesis) | 0.3 | Hardened logic, final structural hardening |
| CriticAgent (all rounds) | 0.1 | Cold deterministic audit |
| EvolverAgent | 0.0 | Pure deterministic evolution |

### Current Settings (`global_config.yaml`)

- **Active Provider**: `deepseek` (model: `deepseek-v4-pro`)
- **API Timeout**: 180s
- **Max Tool Iterations**: 5
- **Retry**: 3 attempts, exponential backoff (5s → 40s)
- **Circuit Breaker**: 3 consecutive failures → halt session cycle

---

## Config System

### File Tree

```
config/
├── global_config.yaml       # LLM providers, binary_star, sniper, guardian, trade_management
├── strategy_config.yaml     # Regime detection, temporal physics, audit thresholds, topography
├── symbol_config.yaml       # Per-symbol trade params + overrides (BTC, ETH, XAUT)
├── visual_config.yaml       # Chart rendering colors, DPI
├── auth/                    # Exchange API credentials
└── prompts/
    ├── binary_star.md       # Shared system instruction (Truth Bus, Logic Macros)
    ├── session.md           # SessionAgent role prompt (heuristics, Shield Law, repair patterns)
    ├── critic.md            # CriticAgent role prompt (CRITIC_CODES table, Neutrality Paradox)
    └── evolver.md           # EvolverAgent role prompt (mutation patterns, fitness interpretation)
```

### Resolution Order

```mermaid
graph TD
    Base["strategy_config.yaml<br/>regime + temporal + audit"] --> Merge["deep merge"]
    Global["global_config.yaml<br/>llm + binary_star + sniper + guardian"] --> Merge
    Symbol["symbol_config.yaml<br/>per-symbol overrides"] --> Resolve["resolve_config()"]
    Merge --> Resolve
    Resolve --> Final["Final resolved config<br/>(frozen dataclasses)"]
```

**Rule**: Symbol overrides win on conflict. Resolution deep-copies via `copy.deepcopy()` — original config is never mutated.

### Sub-Config Dataclasses (Frozen)

| Dataclass | Source Section | Key Fields | Count |
|-----------|---------------|------------|-------|
| `RegimeConfig` | `regime_parameters` | trend thresholds, volatility ratios, squeeze, CVD, imbalance, structural buffers | 25 |
| `TemporalConfig` | `temporal_parameters` | velocity floor, regime-specific dilation factors + weights | 9 |
| `RiskConfig` | `regime_parameters.risk` | min RR (trending/ranging), chaos discount, max holding hours, stop buffers | 9 |
| `AuditConfig` | `audit_review` | MAE thresholds (pinpoint/standard/luck), missed opportunity | 4 |
| `VisualConfig` | `visual_config.yaml` | render DPI, up/down/POC/VAH/VAL colors | 8 |

### Per-Symbol Overrides

```yaml
# symbol_config.yaml
XAUTUSDT:
  precision_qty: 3
  precision_price: 1
  min_order_qty: 0.01
  sl_slippage_buffer: 1.0
  overrides:
    regime_parameters:
      trend:
        trend_intensity_min_expansion: 0.08    # Lower than default 0.12 (XAUT volatility)
      structural:
        breakout_frontrun_atr: 0.2             # Tightened from 0.24
    sniper:
      probes:
        cvd_divergence_tick_delta: 0.18         # Lower than default 0.25 (weaker signals)
      signal_stack:
        gate:
          max_price_to_structure_atr: 2.0       # Lower than default 4.0 (XAUT ATR ~26)
```

---

## Installation & Setup

```bash
# Clone
git clone <repo-url> && cd crypto

# Virtual environment
python -m venv venv && source venv/bin/activate

# Install
pip install -e .

# Configure
cp .env.example .env
# Edit .env — set at least one API key:
#   DEEPSEEK_API_KEY=sk-...
#   GEMINI_API_KEY=...
#   QWEN_API_KEY=...

# Set active provider in config/global_config.yaml → llm.active_provider

# Exchange credentials in config/auth/ (Binance API key + secret)

# Verify setup
python run.py --version
```

---

## Commands

All commands support both `python run.py <command>` (unified CLI) and direct `python run_<module>.py` invocation. The `run_*.py` scripts are independent entry points — they do not import `run.py`.

A `singularity` console command is also available after `pip install -e .`:

```bash
singularity session --symbol BTC -p data/prod
singularity sniper --symbol BTC,ETH --llm -p data/prod
```

### Session

Run a single Binary Star analysis cycle with live market data.

```bash
# Via unified CLI
python run.py session --symbol BTC -p data/prod

# Via standalone script
python run_session.py --symbol BTC

# With status file for dashboard polling
python run.py session --symbol BTC --write_status -p data/prod
```

| Flag | Required | Default | Description |
|------|----------|---------|-------------|
| `--symbol` | Yes | — | Trading pair prefix (`BTC`, `ETH`, `XAUT`) |
| `-p` / `--path` | No | `data/prod` | Data root directory |
| `--write_status` | No | `false` | Write progress to `.session_run_status.json` |

### Sniper

Run the real-time monitoring daemon. 2-min pulse → signal evaluation → AI session only on trigger.

```bash
# Observe-only (signals logged, no LLM spend)
python run.py sniper --symbol BTC,ETH,XAUT -p data/prod

# Enable AI sessions on trigger
python run.py sniper --symbol BTC,ETH,XAUT --llm -p data/prod

# Enable automated trading (implies --llm)
python run.py sniper --symbol BTC,ETH,XAUT --trade -p data/prod

# With manual balance override
python run.py sniper --symbol BTC,ETH,XAUT --trade 1000 -p data/prod
```

| Flag | Required | Default | Description |
|------|----------|---------|-------------|
| `--symbol` | Yes | — | Trading pair prefix(es), CSV for multiple |
| `--llm` | No | `false` | Enable AI session dispatch on trigger |
| `--trade` | No | `false` | Enable automated margin trading (implies `--llm`). Optional float value = manual balance USDT |
| `-p` / `--path` | No | `data/prod` | Data root directory |

### Backtest

Run session cycles against historical timestamps. Three mutually exclusive modes:

```bash
# Dashboard mode (reads timestamps from .backtest_status.json)
python run.py backtest-run --symbol BTCUSDT --write-status -p data/prod

# Single historical point
python run.py backtest-run --symbol BTCUSDT --timestamp "2026-06-15T14:00:00Z" -p data/prod

# Batch range with sniper-based sampling
python run.py backtest-run --symbol BTCUSDT --start T-30d --samples 20 -p data/prod

# Batch with custom end date
python run.py backtest-run --symbol BTCUSDT --start 2026-01-01 --end 2026-06-01 --samples 50 -p data/prod
```

| Flag | Required | Default | Description |
|------|----------|---------|-------------|
| `--symbol` | Yes | — | Trading pair (e.g. `BTCUSDT`) |
| `--write-status` | Mode A | — | Dashboard mode: read timestamps from `.backtest_status.json` |
| `--timestamp` / `-ts` | Mode B | — | Single ISO-8601 timestamp |
| `--start` | Mode C | — | Start date (`YYYY-MM-DD` or `T-30d`) |
| `--end` | No | `now` | End date for batch range |
| `--samples` | With `--start` | — | Number of historical samples |
| `-p` / `--path` | No | `data/prod` | Data root directory |

### Audit

Forensic audit on completed sessions. Batch mode (all sessions in directory) or single file. Parallel execution via `ProcessPoolExecutor`.

```bash
# Audit a single session file
python run.py audit -f data/prod/sessions/BTCUSDT_20260615_140000.json -p data/prod

# Batch audit all sessions for a symbol
python run.py audit --symbol BTC -p data/prod

# Force re-audit (bypass dedup + maturity checks)
python run.py audit --symbol BTC --force -p data/prod
```

| Flag | Required | Default | Description |
|------|----------|---------|-------------|
| `-f` / `--file` | No | — | Path to a specific session JSON |
| `--symbol` | No | — | Filter batch by symbol prefix |
| `--force` | No | `false` | Bypass deduplication and maturity checks |
| `-p` / `--path` | **Yes** | — | Data root directory |

### Evolution

Meta-evolution cycle: ingest audit reports → AI proposes mutations → sandbox validates → generates proposal JSON.

```bash
python run.py evolution --symbol BTC --samples 10 -p data/prod
```

| Flag | Required | Default | Description |
|------|----------|---------|-------------|
| `--symbol` | Yes | — | Trading pair prefix |
| `--samples` | Yes | — | Number of audit reports to ingest |
| `-p` / `--path` | **Yes** | — | Data root directory |

### Patch

Apply a validated evolution proposal to config files and prompt templates.

```bash
# Patch strategy_config.yaml (no symbol — base config)
python run.py patch -f data/prod/evolution/proposals/BTCUSDT_evolution_20260615.json

# Patch symbol_config.yaml overrides for a specific symbol
python run.py patch -f proposal.json --symbol XAUT
```

| Flag | Required | Default | Description |
|------|----------|---------|-------------|
| `-f` / `--file` | Yes | — | Path to validated evolution proposal JSON |
| `--symbol` | No | — | Target symbol for symbol_config.yaml override patching |

### Dashboard

Start the FastAPI dashboard server for visualizing sessions, audits, and backtest results.

```bash
# Start dashboard (default port 8080)
python src/dashboard/server.py -p data/prod

# Custom port and host
python src/dashboard/server.py -p data/prod --port 3000 --host 0.0.0.0

# Production data root
python src/dashboard/server.py -p data/v26.6.28
```

| Flag | Required | Default | Description |
|------|----------|---------|-------------|
| `-p` / `--data-root` | **Yes** | — | Data directory root (e.g. `data/prod`, `data/v26.6.28`) |
| `--port` | No | `8080` | Server port |
| `--host` | No | `127.0.0.1` | Server bind address |

The server also respects the `SINGULARITY_DATA_ROOT` environment variable:

```bash
export SINGULARITY_DATA_ROOT=data/prod
python src/dashboard/server.py
```

**Pages**: `/performance` (dashboard), `/live` (live sessions), `/development` (dev tools), `/sessions/{filename}` (session detail), `/audits/{filename}` (audit detail).

### Utility Scripts

| Script | Usage | Description |
|--------|-------|-------------|
| `scripts/calculate_qty.py` | `-f session.json -b 1000` | Position size calculator: equity × risk% ÷ (entry − SL) |
| `scripts/check_margin_state.py` | `--symbol BTC` | Inspect current Binance margin account state |
| `scripts/clean_neutral_sessions.py` | `-p data/prod [--symbol BTC] [--dry-run]` | Batch-delete NEUTRAL session files from data directory |
| `scripts/export_session.py` | `-f audit.json -p data/prod` | Extract original session from forensic audit report |
| `scripts/market_recon.py` | `--symbol BTC [-ts ISO] [--email] -p data/prod` | Standalone market topography snapshot (POC, VAH, VAL, ATR) |
| `scripts/render_email_html.py` | `-f session.json -p data/prod [--open]` | Render session result as email-safe HTML |
| `scripts/sandbox_offline.py` | `-f sandbox.json -p data/prod` | Offline sandbox: replay audit with patch, no live API calls |
| `scripts/sandbox_online.py` | `-f proposal.json -p data/prod` | Online sandbox: full Binary Star replay with live AI validation |

---

## Key Invariants

These are hard constraints enforced at runtime — violations trigger aborts or emergency closes, not warnings.

### Guardian: Position Protection

- **Never Naked Position** — the core invariant. Between cancelling old OCO orders and placing new ones, the position is briefly naked. If any re-place step fails (pivot-preserve, same-direction optimize, or trailing stop migration), Guardian performs an emergency market close. The `_EMERGENCY_CLOSED_SENTINEL = -1` signals the SniperDaemon that the position was force-closed.

- **Emergency Close Paths** — enforced in `MarginOrderExecutor`:

  | Trigger | Location | Recovery |
  |---------|----------|----------|
  | SL already breached on Guardian pulse | `guardian_check` → `execute_market_close` | Clear trade state |
  | Position has no TP/SL prices | `guardian_check` → `execute_market_close` | Clear trade state |
  | OCO placement fails (first protect) | `guardian_check` → `execute_market_close` | Clear trade state |
  | OCO re-place fails (pivot-preserve) | `sync_with_opinion` → `execute_market_close` | Place new entry |
  | OCO re-place fails (same-direction) | `_optimize_same_direction` → `execute_market_close` | Return sentinel `-1` |
  | OCO re-place fails (trailing stop) | `_migrate_trailing_stop` → `execute_market_close` | Clear trade state |
  | Position vanishes during migration | `_migrate_trailing_stop` → `execute_market_close` | Clear trade state |

- **Forward-Only SL Migration**: Trailing stop only migrates forward — `target_level > current_level` enforced. SL never moves backward.

- **Monotonic Trailing Stop Levels**: `_get_guardian_config()` validates `0 < l1 < l2 < l3` and `0 < o2 < o3` at init. Misconfigured levels raise `ConfigurationError`.

- **Orientation Conflict Detection**: Guardian verifies reality's net_qty direction matches intent (LONG/SHORT). Mismatch is logged and protection is skipped — the position is not force-closed.

### Session & Lifecycle

- **Symbol Whitelist**: `MarginOrderExecutor._get_trade_config()` raises `KeyError` if the symbol lacks `precision_qty` in `symbol_config.yaml`. No trade can execute for unconfigured symbols.

- **Entry Expiry**: Guardian cancels entry orders when `elapsed_hours > projected_waiting_hours`. Expired entries clear trade state.

- **Time Stop** (ATR-adaptive): Positions held beyond `(projected_holding_hours / atr_ratio) × time_stop_multiplier` (1.5) are market-closed. `atr_ratio = current_ATR / entry_ATR` — a 2× ATR increase halves the allowed holding time.

- **Circuit Breaker**: `SessionEngine` halts after `llm.max_consecutive_failures` (default: 3) consecutive cycle failures in live mode. Raises `RuntimeError` and sends an alert email. Historical/simulation mode is exempt.

- **Config Immutability**: `resolve_config()` deep-copies via `copy.deepcopy()` — never mutates the original dict. Sub-config dataclasses (`RegimeConfig`, `RiskConfig`, `TemporalConfig`, `AuditConfig`, `VisualConfig`) are `frozen=True`.

### Math & Signal Integrity

- **Non-finite Price Rejection**: `MathFactChecker` rejects `NaN`, `Inf`, `-Inf`, and non-positive values in tactical parameters before any exchange-facing action.

- **Tactical Parameters Completeness**: `MathFactChecker` requires `entry`, `stop_loss`, and `take_profit` keys — returns `VERIFICATION_FAILURE` if missing.

- **Structural Shielding**: Stop-loss must be anchored behind at least one structural level (POC, VAH/VAL, HVN). Enforced by `MathFactChecker` → `compliance_verdict.sl_is_shielded`. Buffer: `structural_buffer_atr` = 0.84 ATR.

- **Chaos Survival**: Directional momentum signals (`cvd_momentum`, `volatility_surge`) are blocked by the Pre-AI Gate in chaos regime unless accompanied by squeeze or absorption signals. Confluence threshold scales by 1.50×.

- **Regime-Gated RR**: Minimum RR adapts to market regime — trending uses `min_rr_trending` (1.12), ranging uses `min_rr_ranging` (1.0). Chaos applies `chaos_rr_discount` (35%) to allow low-RR survival plans.

- **Adaptive Cooldown**: Sniper cannot re-trigger within the cooldown window unless emergency override (single signal strength ≥ 0.80) or stacked break (3+ fresh signals, or strength > last trigger × 1.8). Absolute minimum gap between any two triggers: 10 minutes.

---

## Development

```bash
# Run full test suite
python -m pytest tests/ -v

# Run specific test file
python -m pytest tests/unit/test_sniper_daemon.py -v

# Run with coverage
python -m pytest tests/ --cov=src --cov-report=term-missing
```

**Test suite**: 166 tests across unit, integration, system, and analyzer layers. All tests use mocked external dependencies (exchange clients, AI adapters). Live API tests are skipped unless real API keys are configured.
