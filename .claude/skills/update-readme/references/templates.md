# README Section Templates

Each section below shows the preferred format, the source files to scan,
and how to structure the generated content.

---

## Architecture & Layer Stack

**Format**: Mermaid flowchart + compact layer descriptions

**Source files**: `src/` directory listing, key class docstrings

**Template**:
```markdown
## Architecture

[Mermaid flowchart showing entry points → orchestration → agents → analysis → infrastructure.
Use subgraphs to group related modules. Each node should be a concise label.]

### Layer Stack

| Layer | Module(s) | Role |
|:------|:----------|:-----|
| Entry Points | `run.py`, `run_*.py` | CLI + daemon entry points |
| Dashboard | `src/dashboard/` | FastAPI web UI |
| ... | ... | ... |
```

**How to build the diagram**:
1. `ls src/*/` to get top-level packages
2. For each package, `ls src/<pkg>/` to get modules
3. Read each module's docstring or class definitions for its role
4. Trace imports to understand inter-package dependencies
5. Build the mermaid flowchart with subgraphs per layer

---

## Binary Star Protocol

**Format**: Mermaid sequence diagram + audit dimensions table

**Source files**:
- `src/agent/binary_star_orchestrator.py` — `execute_flow()`
- `src/agent/debate_loop.py` — `run()`
- `src/agent/session_agent.py` — role
- `src/agent/critic_agent.py` — role
- `src/analyzer/math_fact_checker.py` — verification

**Template**:
```markdown
## The Binary Star Protocol

[One-paragraph overview: what it is, why it exists]

### Debate Flow

[Mermaid sequence diagram:
MarketObserver → BinaryStarOrchestrator → SessionAgent → MathFactChecker → CriticAgent → (loop back or exit)]

### Audit Dimensions

| Dimension | Identifier | Logic |
|:---|:---|:---|
| ... | `[DIMENSION]` | One-line description |
```

**How to extract audit dimensions**:
1. Search for `[A-Z_]+` patterns in `critic_agent.py` and `math_fact_checker.py`
2. Each dimension should have a clear identifier and one-sentence logic description
3. If dimensions are defined in a data structure (enum, dict), extract from there

---

## Sniper System

**Format**: Mermaid state diagram + signal table + pulse flow + Guardian tables

**Source files**:
- `src/sniper/trigger.py` — signal types, categories, thresholds, ConfluenceEngine
- `src/sniper/scout.py` — market data harvesting
- `src/agent/order_executor.py` — Guardian, sync_with_opinion, trailing stops
- `config/strategy_config.yaml` — sniper parameters

**Template**:
```markdown
## Sniper Trading System

[One-paragraph overview]

### Signal Stack

| Category | Signal | Direction | Detection |
|----------|--------|-----------|-----------|
| FLOW | CVD Momentum | ... | ... |
| ENERGY | Volatility Surge | ... | ... |
| STRUCTURAL | Boundary Test | ... | ... |
| POSITIONING | Retail Extreme | ... | ... |
| CROSS-SYMBOL | Leader Sync | ... | ... |

### Pulse Flow

[Mermaid flowchart: 2-min pulse → Guardian → Trigger → AI Session → Trade Gate → sync_with_opinion]

### Order Lifecycle

[Mermaid state diagram: Flat → EntryPending → InPosition → Protected → (trailing) → Closed]

### Guardian Protection

| Condition | Action |
|-----------|--------|
| ... | ... |

### Trailing Stop Tiers

| Tier | Trigger | Action |
|------|---------|--------|
| L1 | Profit >= X ATR | SL → entry |
| ... | ... | ... |

### Position Cross-Reference

| Current State | AI Opinion | Action |
|:---|:---|:---|
| FLAT | BULLISH/BEARISH | ... |
| LONG | BULLISH | Merge + tighten |
| ... | ... | ... |
```

**How to extract parameters**:
1. Read `config/strategy_config.yaml` for:
   - `sniper.signal_stack.trigger_threshold`
   - `sniper.signal_stack.emergency_threshold`
   - `sniper.signal_stack.cooldown.*`
   - `sniper.signal_stack.gate.*`
   - `guardian.trailing_profit_atr_level_*`
   - `guardian.time_stop_multiplier`
   - `risk_per_trade`
2. Use the **actual values** from config, never hardcode

**How to extract signal types**:
1. Search `src/sniper/trigger.py` for signal name constants, enums, or class attributes
2. Group by category (FLOW, ENERGY, STRUCTURAL, POSITIONING, CROSS-SYMBOL)
3. For each signal: capture direction logic and detection criteria

**How to extract Guardian logic**:
1. Read `_guardian_check()` method body
2. Extract each condition → action pair from the if/else branches
3. Read `_migrate_trailing_stop()` for tier definitions
4. Read `sync_with_opinion()` for position cross-reference logic

---

## Commands & Scripts

**Format**: Grouped code blocks with comments

**Source files**:
- `run.py` — argparser definitions
- `run_*.py` — standalone entry points
- `scripts/*.py` — utility scripts

**Template**:
```markdown
## Commands

All entry points consolidated under `run.py`.

```bash
# ── Category Name ──────────────────────────────────────────
python run.py <subcommand> [args]    # Description
python run.py <subcommand> [args]    # Description (variant)

# ── Another Category ───────────────────────────────────────
python run.py <subcommand> [args]    # Description
```

### Utility Scripts

```bash
python scripts/<name>.py [args]      # Description
```

### Tests

```bash
python -m pytest tests/ -v
python -m pytest tests/ --cov=src --cov-report=term-missing
```
```

**How to extract commands**:
1. Parse `run.py`: find all `_add_*_parser()` functions → extract subcommand name, arguments, help text
2. Parse each `run_*.py`: find `argparse` definitions → extract standalone usage
3. List `scripts/*.py`: for each, check `if __name__ == "__main__"` block or argparse for usage
4. For each command, write the most common invocation with required args
5. Add inline comments for variants (historical, backtest, etc.)
6. Group by category: Sessions, Sniper, Audit & Evolution, Dashboard, Utilities

**Rules**:
- Only list commands that actually exist and run
- Use actual argument names from argparse (not guesses)
- Include `-p` / `--path` where required
- Mark optional args with brackets in comments, not in the command itself

---

## AI Providers

**Format**: Comparison table + setup code blocks

**Source files**:
- `src/infrastructure/ai_client.py` — interface
- `src/infrastructure/ai_factory.py` — provider registry
- `src/infrastructure/ai/*.py` — adapters
- `config/global_config.yaml` — current settings

**Template**:
```markdown
## AI Providers

[One-sentence overview of the AI backend architecture]

| Provider | Adapter | Vision | Context Cache | Cost |
|----------|---------|--------|---------------|------|
| Gemini | ... | Yes | Yes | $$$ |
| DeepSeek | ... | — | — | $ |
| Qwen | ... | Yes | — | $ |

### Provider Setup

[YAML code block showing config for each provider]
```

**How to determine capabilities**:
1. For each adapter class, check:
   - `supports_vision` or presence of image handling methods
   - `supports_context_cache` or presence of cache methods
   - Model names from the adapter's `_get_model_name()` or equivalent
2. Read `global_config.yaml` for current default provider and settings
3. Cost tier is subjective: Gemini=$$$, DeepSeek/DeepSeek=$ (infer from model size/pricing)

---

## Config System

**Format**: Directory tree + mermaid resolution flowchart

**Source files**:
- `config/` directory listing
- `src/config/sub_configs.py`
- `src/config/symbol_resolver.py`
- `src/config/loader.py`

**Template**:
```markdown
## Config System

```
config/
├── strategy_config.yaml    # role
├── global_config.yaml      # role
├── ...
└── prompts/                # role
```

[Mermaid flowchart: base config → symbol overrides → deep merge → final config]

[Brief explanation of resolution order and evolution patching]
```

---

## Key Invariants

**Format**: Compact bullet list

**Source files**:
- CLAUDE.md — documented invariants
- Critical module docstrings
- `src/utils/exceptions.py`

**Template**:
```markdown
## Key Invariants

- **Invariant name** (`file.py`): description
- ...
```

**How to extract**:
1. Read CLAUDE.md "Key invariants" section
2. Search for comments/docstrings containing "must", "invariant", "never", "always"
3. Focus on architectural contracts, not implementation details
4. Each invariant should be actionable — something a developer could violate

---

## Installation & Setup

**Format**: Code blocks + numbered steps

**Source files**:
- `pyproject.toml` or `setup.py` — dependencies
- `.env.example` or documentation — API keys
- `config/global_config.yaml` — provider setup

**Template**:
```markdown
## Installation

### Prerequisites
- Python 3.12+
- API key for at least one supported LLM provider

### Setup
```bash
git clone <repo-url> && cd crypto
pip install -e .
pip install -e ".[dev]"
```

### Configuration
1. Create `.env` file with API key
2. Edit `config/global_config.yaml` to set active provider
3. Review `config/strategy_config.yaml` for trading parameters
```

**Rules**:
- Check actual Python version requirement from `pyproject.toml`
- Verify `.env.example` exists; if not, mention the expected keys
- Keep setup steps minimal — 3 steps max
