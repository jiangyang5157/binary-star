# README Section Templates

Use these as rough guides, not fill-in-the-blank forms. Each section should be
**as short as possible while still accurate**. Prefer the fewest words that
convey the architecture.

---

## Opening (CRITICAL — first thing the reader sees)

**Format**: One paragraph, no heading. Goes right after the title + badges.

**Template**:
```markdown
# BinaryStar

[badges]

What if two LLMs debated your trade before it hit the market? **Binary Star**
pits a Planner against a Critic, with Math Tools (deterministic computation)
anchoring both to physical reality. The debate converges in at most two rounds;
if they can't agree and the Critic's last verdict is TERMINAL, the system
aborts to NEUTRAL rather than forcing a broken trade.
```

**Rules**:
- Lead with the HOOK — Binary Star debate, not a feature list
- Skip jargon: no "multi-agent protocol," no "adversarial framework," no "quantitative engine"
- Write like you're explaining it to a sharp engineer, not pitching investors
- One short paragraph. If it's two, cut one.

---

## Binary Star Protocol (HERO — most detailed section)

**Format**: Mermaid sequence diagram + veto table

**Scan**: `src/agent/binary_star_orchestrator.py`, `src/agent/debate_loop.py`, `src/agent/critic_agent.py`

**Template**:
```markdown
## Binary Star Protocol

[One sentence: three agents — Planner proposes, Critic audits, Math Tools verifies.]

[Mermaid sequence diagram: Orchestrator → Planner → Math Tools → Critic, loop 2 rounds, PASS early exit]

### Veto Levels

| Veto | Effect |
|------|--------|
| **PASS** | Plan is sound — early exit, no further rounds |
| **WEAK** | Minor concern — early exit, plan accepted as-is |
| **CONSTRUCTIVE** | Fixable flaws — feedback loop, Planner refines |
| **TERMINAL** | Fatal — structurally invalid. If unresolved at max rounds, forces NEUTRAL |

A deterministic 0–100 survival score is computed in Python after the debate —
evaluating 13 dimensions across topographical armor, regime & gravity, and
temporal & sentiment. Two LLM backends (DeepSeek, Gemini) power the debate
via a shared config.

[Note: AI providers and confidence scoring are mentioned inline — no separate
sections needed.]
```

**Rules**:
- This is the HERO section. Everything else exists to serve it.
- Veto table: 3 rows max
- Fold AI provider mention + confidence scoring INTO this section naturally
- Do NOT create separate "AI Providers" or "Confidence Scoring" sections
- Do NOT list code files or line numbers

---

## Architecture

**Format**: One `graph LR` mermaid diagram

**Scan**: `src/` top-level packages only (depth 1)

**Template**:
```markdown
## Architecture

[One diagram: Sniper triggers → Binary Star debates → Order Executor acts → Evolution feeds back]

[No layer table. No text. One diagram tells the whole story.]
```

**Rules**:
- ONE diagram only
- Zero crossing lines
- No prose — the diagram and its labels are self-explanatory

---

## Sniper (MINIMAL)

**Format**: One paragraph

**Scan**: `src/sniper/trigger.py` (count signals)

**Template**:
```markdown
## Sniper

A local signal stack ({signal count from code} signals, 5 categories) monitors the market at
2-minute pulses. A regime-adaptive confluence engine decides when to
activate Binary Star. Its sole job is timing — it does not trade.
```

**Rules**:
- Do NOT list signals, weights, thresholds, or cooldown details
- One paragraph only

---

## Order Management (MINIMAL)

**Format**: One table

**Template**:
```markdown
## Order Management

| Phase | Mechanism |
|-------|-----------|
| Entry | OTOCO — atomic limit entry with nested TP/SL |
| Protection | Guardian OCO — every position wrapped in TP + SL |
| Profit-taking | 2-phase exit ladder — breakeven (rr_target from config) → trailing partial TP + TP-relative trailing |
| Stop migration | Dynamic trailing SL as ladder levels fire |
```

**Rules**:
- ONE table. No prose.
- No code paths, no config values beyond what's in the table.

---

## Evolution (MINIMAL)

**Format**: One paragraph

**Template**:
```markdown
## Evolution

An offline sandbox evaluates strategy variants against historical sessions.
Winners produce config patches that feed back into Binary Star.
```

**Rules**:
- One paragraph. Two sentences max.
- No population/generations details

---

## Installation

**Format**: One code block

**Template**:
```markdown
## Installation

```bash
pip install -e .
cp .env.example .env  # add your provider API key
```
```

**Rules**:
- Two lines only. No git clone, no Python version, no prerequisites list.
- The `.env.example` hint is the only configuration instruction needed.

---

## Commands (placed LAST)

**Format**: Grouped code blocks — exactly 5 groups

**Scan**: `run.py` (argparse), `scripts/*.py`

**Template**:
```markdown
## Commands

```bash
# ── Sessions ────────────────────────────────────────────
python run.py session --symbol XAUT

# ── Sniper ──────────────────────────────────────────────
python run.py sniper --symbol XAUT,BTC --llm --trade 500

# ── Backtest ────────────────────────────────────────────
python run.py backtest-run --symbol XAUTUSDT --start 2025-01-01 --samples 100

# ── Audit & Evolution ───────────────────────────────────
python run.py audit --symbol XAUT -p data/prod
python run.py evolution --symbol XAUT --samples 50 -p data/prod
python run.py patch -f proposals/evolution.json --symbol XAUT
```
```

**Rules**:
- EXACTLY 4 groups: Sessions, Sniper, Backtest, Audit & Evolution
- One representative command per group (two for Audit & Evolution, including `patch`)
- One inline comment per command
- No "Utilities" section, no scripts
- This section goes LAST
