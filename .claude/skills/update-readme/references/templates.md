# README Section Templates

Use these as rough guides, not fill-in-the-blank forms. Each section should be
**as short as possible while still accurate**. Prefer the fewest words that
convey the architecture.

---

## Architecture & Layer Stack

**Format**: Two `graph LR` mermaid diagrams (split by concern) + one layer table

**Scan**: `src/` directory tree, `src/agent/`, `src/sniper/`, `src/analyzer/`, `src/infrastructure/`

**Template**:
```markdown
## Architecture

Two complementary flows — separated to keep diagrams clean.

### Signal Pipeline

[Mermaid: entry → daemon → scout → trigger → orchestrator → debate → execution]

### Evolution Loop

[Mermaid: orchestrator → sessions → audit → evolver → patches → config]

### Layer Descriptions

| Layer | Module | Role |
|-------|--------|------|
| ... | ... | ... |
```

**Rules**:
- Split into 2 diagrams minimum — never try to fit everything into one
- Layer table: one row per layer, one module per row (use the most representative module, not all)

---

## Binary Star Protocol

**Format**: Mermaid sequence diagram + audit dimensions table

**Scan**: `src/agent/binary_star_orchestrator.py`, `src/agent/debate_loop.py`, `src/agent/critic_agent.py`, `src/analyzer/math_fact_checker.py`

**Template**:
```markdown
## Binary Star Protocol

[One-paragraph overview: what it is, why it exists. 2-3 sentences max.]

[Mermaid sequence diagram: participants → loop → decision]

### Audit Dimensions

| Dimension | Check |
|-----------|-------|
| [NAME] | One-line description |
```

---

## Sniper System

**Format**: Three concise sections — signal table, pulse flow diagram, one Guardian table

**Scan**: `src/sniper/trigger.py`, `src/sniper/scout.py`, `src/agent/order_executor.py`, `config/global_config.yaml`

**Template**:
```markdown
## Sniper System

[One-paragraph overview. 2-3 sentences.]

### Signal Stack

| Category | Signal | Direction | Weight |
|----------|--------|-----------|--------|
| FLOW | cvd_momentum | BULLISH/BEARISH | 0.65 |
| ... | ... | ... | ... |

[13 signals across 5 categories. Read from `config/global_config.yaml` `signal_stack.weights`.]

### Pulse Flow

[Mermaid flowchart: 2-min pulse → Guardian → Trigger → Session → Trade Gate]

### Guardian

| State | Guardian Action |
|-------|----------------|
| Entry pending | Check timeout |
| Filled, no OCO | Place OCO |
| Protected | Exit ladder progress check + sl_lock |
```

---

## Commands & Scripts

**Format**: Grouped code blocks with inline comments

**Scan**: `run.py` (argparse), `run_*.py`, `scripts/*.py`

**Template**:
```markdown
## Commands

```bash
# ── Sessions ────────────────────────────────────────────
python run.py session --symbol BTC -p data/prod    # Live trading session
python run.py session --symbol XAUT -p data/prod --historical 2026-01-01  # Historical

# ── Sniper ──────────────────────────────────────────────
python run.py sniper --symbol BTC,XAUT -p data/prod --trade 640  # Live monitoring
...

# ── Audit & Evolution ───────────────────────────────────
python run.py audit -p data/prod
python run.py evolve -p data/prod --population 8
...

# ── Dashboard ───────────────────────────────────────────
python run.py dashboard -p data/prod
```
```

**Rules**:
- Only list commands that actually exist — parse argparse, never guess
- Group by category: Sessions, Sniper, Audit & Evolution, Dashboard, Utilities
- One inline comment per command is enough

---

## AI Providers

**Format**: One comparison table + one config block

**Scan**: `src/infrastructure/ai/*.py`, `config/global_config.yaml`

**Template**:
```markdown
## AI Providers

| Provider | Model | Vision | Cost |
|----------|-------|--------|------|
| DeepSeek | deepseek-v4-pro | — | $ |
| Gemini | gemini-3.5-flash | Yes | $$$ |

### Config

```yaml
llm:
  active_provider: "deepseek"
  agents:
    session:
      temperature: 0.5
      reasoning_effort: "high"
    critic:
      temperature: 0.1
      reasoning_effort: null
```
```

---

## Config System

**Format**: Directory tree + one mermaid resolution diagram

**Scan**: `config/` directory, `src/config/`

**Template**:
```markdown
## Config System

```
config/
├── global_config.yaml      # Guardian, sniper, LLM, binary star
├── strategy_config.yaml    # Regime detection, temporal physics
├── symbol_config.yaml      # Per-symbol precision overrides
└── prompts/                # AI role prompts
```

[Simple mermaid: base config → symbol overrides → merge → final config]
```

---

## Key Invariants

**Format**: Compact bullet list. 5-8 items max.

**Scan**: CLAUDE.md, critical module docstrings

**Template**:
```markdown
## Key Invariants

- **Invariant** (`file.py`): one-line description
```

**Rules**:
- Only list invariants a developer could violate
- Skip implementation details
- Keep to 8 items maximum

---

## Installation & Setup

**Format**: 3 steps with code blocks

**Template**:
```markdown
## Installation

### Prerequisites
- Python 3.12+
- Provider API key

### Setup
```bash
git clone <repo> && cd crypto
pip install -e .
cp .env.example .env  # add your API key
```
```

**Rules**: Read Python version from `pyproject.toml`. Keep to 3 steps.
