# README Section Templates

Use these as rough guides, not fill-in-the-blank forms. Each section should be
**as short as possible while still accurate**. Prefer the fewest words that
convey the architecture.

---

## Binary Star Protocol (HERO — most detailed section)

**Format**: Mermaid sequence diagram + audit dimensions table + agent roles table

**Scan**: `src/agent/binary_star_orchestrator.py`, `src/agent/debate_loop.py`, `src/agent/session_agent.py`, `src/agent/critic_agent.py`, `src/analyzer/math_fact_checker.py`

**Template**:
```markdown
## Binary Star Protocol

[One-paragraph overview: multi-agent debate system. Planner proposes a trade,
Critic audits it across 7 dimensions, Math Auditor verifies physics (RR,
betweenness, ATR). Debate converges when Critic passes or forced synthesis
after max rounds. 2-3 sentences.]

### Debate Flow

[Sequence diagram: Planner → Critic → Math Auditor, loop until converge/limit]

### Agent Roles

| Agent | Role | Model |
|-------|------|-------|
| Planner | Generates trade plan with tactical parameters | deepseek-v4-pro |
| Critic | Audits against 7 dimensions, issues veto | deepseek-v4-pro |
| Math Auditor | Verifies RR, betweenness, ATR volatility | (tool-call) |

### Audit Dimensions

| Dimension | Check |
|-----------|-------|
| [NAME] | One-line description |
```

**Rules**:
- This is the HERO section — give it the most detail. The reader should understand how the debate works after reading this.
- Show agent collaboration clearly in the sequence diagram
- Keep audit dimensions table to 5-8 rows max
- Do NOT list code files or line numbers

---

## Architecture

**Format**: One `graph LR` mermaid diagram — clean system boundaries

**Scan**: `src/` top-level packages only (depth 1)

**Template**:
```markdown
## Architecture

[One diagram showing: Sniper triggers → Binary Star debates → Order Executor acts → Evolution feeds back]

[No layer table. No code paths. One diagram tells the whole story.]
```

**Rules**:
- ONE diagram only. If it needs two, the scope is wrong.
- Show system boundaries, not modules
- Zero crossing lines
- No text beyond the diagram caption

---

## Sniper (MINIMAL)

**Format**: One paragraph

**Scan**: `src/sniper/trigger.py` (count signals), `config/global_config.yaml` (thresholds)

**Template**:
```markdown
## Sniper

A local signal stack monitors 13 market signals across 5 categories (flow,
energy, structural, positioning, cross-symbol). A regime-adaptive confluence
engine determines when market conditions warrant activation. Its sole purpose
is providing high-quality entry timing for the Binary Star debate system.
```

**Rules**:
- Do NOT list individual signals
- Do NOT show signal weights or thresholds
- Do NOT include the pulse flow diagram
- One paragraph only. If it needs more, it's too long.

---

## Order Management (MINIMAL)

**Format**: One table

**Scan**: `src/agent/order_executor.py` (confirm guardian phases exist)

**Template**:
```markdown
## Order Management

| Phase | Mechanism |
|-------|-----------|
| Entry | OTOCO (atomic entry + nested TP/SL) |
| Protection | Guardian OCO — every position wrapped in TP+SL |
| Profit-taking | 3-level exit ladder — partial closes at 44/64/84% TP progress |
| Stop migration | Dynamic trailing SL — locks in profit as ladder levels fire |
```

**Rules**:
- ONE table only. No prose needed.
- Do NOT describe code paths or function names
- Do NOT include margin/risk/sizing details

---

## Evolution (MINIMAL)

**Format**: One paragraph

**Template**:
```markdown
## Evolution

A sandboxed strategy evolution loop runs offline, evaluating candidate
configurations against historical sessions. Successful variants produce
config patches — updated strategy logic and parameter overrides — that
feed back into Binary Star's decision framework.
```

**Rules**:
- One paragraph only
- Do NOT describe population size, generations, or fitness metrics
- Do NOT mention file paths or class names

---

## AI Providers

**Format**: One comparison table + one config block

**Scan**: `src/infrastructure/ai_factory.py`, adapters in `src/infrastructure/ai/`, `config/global_config.yaml`

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

**Scan**: `config/` directory

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

## Commands & Scripts (placed LAST)

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

# ── Dashboard ───────────────────────────────────────────
python run.py dashboard -p data/prod
```
```

**Rules**:
- Only list commands that actually exist — parse argparse, never guess
- Group by category: Sessions, Sniper, Dashboard, Utilities
- One inline comment per command
- This section goes LAST after everything else

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
