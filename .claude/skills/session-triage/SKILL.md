---
name: session-triage
description: >
  Batch-scan session JSON files and classify them by trigger cause, debate quality,
  and outcome. Use when the user asks to "triage sessions", "find interesting sessions",
  "scan recent sessions", "which sessions should I review?", "classify my trading sessions",
  "show me the best/worst sessions", "find sessions with debate conflicts", "audit session
  quality", "rank sessions by performance". Also use when the user wants to quickly
  understand what happened across a set of sessions without manually opening each file.
---

# Session Triage — Batch Classification & Discovery

Scan a directory of session JSON files, extract structured dimensions from each,
and rank/classify them to surface the sessions most worth human review.

## Step 1: Collect Session Files

Default scan directory: `data/prod/sessions/`. Accept user overrides for:
- A different directory path
- A symbol filter (`BTCUSDT` only, `XAUTUSDT` only)
- A date range (`--since 2026-06-25`, `--between 2026-06-20 2026-06-28`)
- A limit (`--last 20`)

```bash
# Find all session files, optionally filtered
ls -t data/prod/sessions/*_session_*.json | head -50
```

For each file, extract the symbol and timestamp from the filename:
`{SYMBOL}_session_{YYYYMMDD}_{HHMMSS}.json`

## Step 2: Extract Dimensions from Each Session

Load each session JSON and extract these fields. Use inline Python for batch
processing — reading 50+ files one at a time with Read is too slow.

### Dimension A: Trigger Cause

From `observation.situation_brief.activated_by[]`:

```python
def extract_trigger_cause(session):
    sb = session.get('observation', {}).get('situation_brief', {})
    activated = sb.get('activated_by', [])
    if not activated:
        return {
            'primary_signal': 'unknown',
            'signal_count': 0,
            'confluence_score': sb.get('confluence_score', 0),
            'confluence_direction': sb.get('confluence_direction', 'NEUTRAL'),
            'gate_result': sb.get('gate_result', 'unknown'),
            'regime_note': sb.get('regime_note', ''),
        }
    primary = activated[0]
    return {
        'primary_signal': primary.get('signal', 'unknown'),
        'signal_count': len(activated),
        'all_signals': [s.get('signal') for s in activated],
        'primary_strength': primary.get('strength', 0),
        'primary_confidence': primary.get('confidence', 0),
        'confluence_score': sb.get('confluence_score', 0),
        'confluence_direction': sb.get('confluence_direction', 'NEUTRAL'),
        'gate_result': sb.get('gate_result', 'unknown'),
        'regime_note': sb.get('regime_note', ''),
    }
```

### Dimension B: Debate Quality

From `debate_history[]`:

```python
def extract_debate_quality(session):
    history = session.get('debate_history', [])
    if not history:
        return {'rounds': 0, 'veto_path': 'no_debate', 'converged': False}

    veto_levels = []
    for r in history:
        critic = r.get('critic', {})
        veto = critic.get('veto_level', 'UNKNOWN')
        veto_levels.append(veto)

    # Classify the debate path
    if 'TERMINAL' in veto_levels:
        if veto_levels[-1] == 'PASS':
            path = 'terminal_then_pass'      # Critic vetoed, Session fixed it
        elif len(veto_levels) >= 2 and all(v == 'TERMINAL' for v in veto_levels):
            path = 'double_terminal'          # Both rounds vetoed → forced synthesis
        else:
            path = 'had_terminal'
    elif 'CONSTRUCTIVE' in veto_levels:
        path = 'constructive_resolved' if veto_levels[-1] == 'PASS' else 'constructive_unresolved'
    elif all(v == 'PASS' for v in veto_levels):
        path = 'clean_pass'                   # Single round, no objections
    else:
        path = 'mixed'

    # Detect forced synthesis (debate hit max rounds without convergence)
    final = session.get('final_decision', {})
    critic_impact = final.get('critic_impact', '')
    forced = critic_impact and 'FORCED SYNTHESIS' in str(critic_impact).upper()

    return {
        'rounds': len(history),
        'veto_path': path,
        'veto_levels': veto_levels,
        'forced_synthesis': forced,
        'converged': veto_levels[-1] == 'PASS' if veto_levels else False,
    }
```

### Dimension C: Outcome Quality

From `final_decision`:

```python
def extract_outcome(session):
    fd = session.get('final_decision', {})
    tp = fd.get('tactical_parameters', {})
    return {
        'opinion': fd.get('opinion', 'NEUTRAL'),
        'confidence': fd.get('confidence_score', 0),
        'rr_ratio': tp.get('rr_ratio', 0),
        'entry': tp.get('entry', 0),
        'stop_loss': tp.get('stop_loss', 0),
        'take_profit': tp.get('take_profit', 0),
        'projected_holding_hours': tp.get('projected_holding_hours', 0),
        'projected_waiting_hours': tp.get('projected_waiting_hours', 0),
    }
```

### Dimension D: Market Context

From `observation.quantitative_metrics`:

```python
def extract_market_context(session):
    qm = session.get('observation', {}).get('quantitative_metrics', {})
    regime = qm.get('market_regime', {})
    pd = qm.get('price_dynamics', {})
    ss = qm.get('sentiment_signals', {})

    # Classify regime from metrics
    vii = pd.get('volatility_intensity_index', 0)
    sf = regime.get('squeeze_factor', 1)
    trend = abs(regime.get('trend_intensity', 0))
    if vii > 2.2:    regime_class = 'chaos'
    elif sf < 1.0:   regime_class = 'squeeze'
    elif trend > 0.35: regime_class = 'trending'
    else:            regime_class = 'ranging'

    return {
        'regime_class': regime_class,
        'squeeze_factor': sf,
        'trend_intensity': regime.get('trend_intensity', 0),
        'vii': vii,
        'vpr': regime.get('volume_participation_ratio', 0),
        'current_price': pd.get('current_price', 0),
        'atr_macro': pd.get('atr_macro', 0),
        'cvd_intensity': ss.get('cvd_intensity_ratio', 0),
        'oi_delta_macro': ss.get('oi_delta_macro', 0),
    }
```

## Step 3: Score and Classify

Compute these scores for ranking. Each is a 0–100 scale (higher = more
interesting/worthy of review).

### Interestingness Score

```python
def score_interestingness(trigger, debate, outcome, market):
    score = 0

    # HIGH interest: debate had conflict
    if debate['veto_path'] in ('terminal_then_pass', 'double_terminal', 'constructive_unresolved'):
        score += 30
    elif debate['veto_path'] == 'constructive_resolved':
        score += 15

    # HIGH interest: forced synthesis (debate couldn't converge)
    if debate['forced_synthesis']:
        score += 25

    # HIGH interest: trigger-AI disagreement
    # (trigger said go but AI said NEUTRAL, or vice versa with low confidence)
    if outcome['opinion'] == 'NEUTRAL':
        if trigger['confluence_score'] > 0.30:
            score += 20   # trigger fired but AI found nothing
    elif outcome['confidence'] < 50:
        score += 15       # AI went directional but was very unsure

    # MEDIUM interest: extreme confluence
    if trigger['confluence_score'] >= 0.50:
        score += 10
    elif trigger['confluence_score'] >= 0.40:
        score += 5

    # MEDIUM interest: high confidence
    if outcome['confidence'] >= 85:
        score += 10

    # MEDIUM interest: extreme regime
    if market['regime_class'] == 'chaos':
        score += 15
    elif market['regime_class'] == 'squeeze':
        score += 10

    # LOW interest penalty: clean single-pass, moderate everything
    if debate['veto_path'] == 'clean_pass' and debate['rounds'] == 1:
        if outcome['confidence'] < 80:
            score -= 10   # unremarkable

    # Signal diversity: multiple signals more interesting than single
    if trigger['signal_count'] >= 3:
        score += 10

    return max(0, min(100, score))
```

### Quality Flags

Classify each session with one or more flags:

| Flag | Condition |
|------|-----------|
| `⭐ TOP_PICK` | Interestingness ≥ 70 |
| `🔥 HIGH_CONVICTION` | Confidence ≥ 85 AND debate clean_pass |
| `⚡ QUICK_KILL` | Single round, PASS, confidence ≥ 80 |
| `🤝 HARD_WON` | TERMINAL → PASS or forced synthesis |
| `🚫 AI_OVERRIDE` | Trigger fired but AI said NEUTRAL |
| `💀 DOUBLE_VETO` | Both rounds TERMINAL |
| `📉 LOW_RR` | RR ratio < 1.2 |
| `📈 HIGH_RR` | RR ratio > 2.5 |
| `🌪️ CHAOS_TRADE` | Regime = chaos, opinion ≠ NEUTRAL |
| `🔧 SINGLE_SIGNAL` | Only 1 signal activated |
| `🎯 MULTI_SIGNAL` | 3+ signals activated |

## Step 4: Produce the Triage Report

```markdown
# Session Triage Report
**Directory:** {path}
**Filter:** {symbol/date range applied}
**Sessions scanned:** {N}

## Summary

| Metric | Value |
|--------|-------|
| Total sessions | {N} |
| BULLISH / BEARISH / NEUTRAL | {counts} |
| Avg confidence | {mean}% |
| Debate: clean_pass / had_conflict / forced_synth | {counts} |
| Avg confluence score | {mean} |
| Regime distribution | {counts by regime} |
| Top signal (most common trigger) | {signal_name} ({count}) |

## 🔥 Top Picks (sorted by interestingness)

[Table of top 5–10 sessions by interestingness score, with key columns:]
| # | Session | Score | Trigger | Debate | Opinion | Conf | RR | Flag |
|---|---------|-------|---------|--------|---------|------|----|------|

## By Trigger Signal

[Group sessions by primary signal. Show count and avg confidence per signal type.]

## By Debate Pattern

[Group by veto_path. Show how many sessions had conflict vs clean passes.]

## Regime Breakdown

[Cross-tabulate: regime × opinion. Which regimes produce the most trades? Which
produce the most NEUTRAL opinions?]

## Sessions Requiring Review

[List any sessions with concerning patterns:]
- DOUBLE_VETO sessions (debate failed to converge → forced synthesis)
- CHAOS_TRADE sessions (trading in chaos — highest risk)
- LOW_RR sessions (RR < 1.2 — thin edge)
- AI_OVERRIDE sessions (trigger fired, AI disagreed)
- Sessions with RR > 3.0 (suspiciously good — possible data artifact)

## Full Session Table

[Complete sortable table of all sessions with all extracted dimensions.]
| File | Time | Signal | Regime | Rounds | Veto Path | Opinion | Conf | RR | Score | Flags |
|------|------|--------|--------|--------|-----------|---------|------|----|-------|-------|
```

## Step 5: Offer Deep Dives

After presenting the triage report, offer to deep-dive into specific sessions:

- "Want me to run a full trace on session #3?" → invokes sniper-debug
- "Should I run the forensic audit on the DOUBLE_VETO sessions?"
- "Want me to compare the two highest-scoring sessions side by side?"

## Reference Files

- `data/prod/sessions/` — session JSON archives (default scan directory).
- `src/agent/binary_star_orchestrator.py` — how sessions are produced, debate
  flow, version hashing.
- `src/sniper/trigger.py` — signal definitions, confluence engine, gate logic
  (for understanding trigger causes).
- `src/analyzer/audit_controller.py` — existing batch audit logic (this skill
  is complementary: triage is for discovery, audit is for forensic depth).
- `config/global_config.yaml` → `signal_stack.weights` — signal confidence
  values used for interpreting trigger quality.
