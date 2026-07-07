---
name: sniper-debug
description: >
  Trace why the Sniper did or did not trigger, and audit signal health across
  symbols over a time window. Use when the user asks: "why did sniper trigger
  here?", "why didn't it trigger?", "debug this signal", "what happened at 2pm
  yesterday?", "trace the confluence", "check the cooldown state", "why was this
  session fired?", "analyze the trigger log", "compare signals across symbols",
  "audit signal quality", "sniper health check", "how is the sniper doing?".
  Also use when the user reports unexpected sniper behavior (missed entries,
  false triggers, suspicious signal patterns) or wants a broad health check
  across all watched symbols.
---

# Sniper Debug — Signal Trace & Multi-Symbol Audit

Two modes. The user almost always wants **Mode B** unless they name a specific
session file or a narrow time point.

## Implicit Parameters (extract from user's words)

The skill takes no formal arguments. Extract these from what the user says:

| Parameter | How to extract | Default |
|-----------|---------------|---------|
| **Time window** | "昨天", "last 3 hours", "since restart", "10:00-16:00" | Since last sniper restart |
| **Symbol(s)** | "XAUTUSDT", "BTCUSDT", "all", or omit | All symbols in log |
| **Mode** | Session file path → Mode A; everything else → Mode B | Mode B |

If ambiguous, ask: "All symbols or a specific one? What time window?"

| Mode | When to use | Output |
|------|------------|--------|
| **A — Single Trace** | Specific session file, "why did X fire at Y time?" | Pulse-by-pulse reconstruction |
| **B — Multi-Symbol Audit** | "How is the sniper doing?", time-window comparison, signal health | Signal health table + anomaly report |

⚠️ **Timezone**: Sniper log timestamps are in the **machine's local timezone**.
Session filenames and `observed_at` fields are **UTC**. Always convert before
comparing. Check the machine timezone first:

```bash
date +%Z  # e.g., NZST = UTC+12
```

---

# Mode A — Single Trace Forensics

Trace through one trigger event: which signals fired, confluence score, gate
result, and root cause.

## A1. Locate the data

```bash
grep '\[trigger\].*\[SYMBOL\]' data/prod/sniper.log | grep -E 'SIGNAL DIAG|WAKE'
```

Narrow with `sed -n '/<start>/,/<end>/p'` for large logs. If the log doesn't
go back far enough, fall back to the session JSON's `observation.situation_brief`.

## A2. Parse SIGNAL DIAG lines

Each detector produces either `F:0.XX` (fired, strength) or `R:<reason>`
(rejected). Parse with inline Python — see `references/log_parsing.md`.

## A3. Reconstruct the trigger decision

For the target pulse(s):
1. Which signals fired and at what strength?
2. What was the effective threshold? (regime × modifier from config)
3. Did confluence pass? (directional stacking + noise cancellation)
4. Was cooldown active? Any break condition met?
5. Did the pre-AI gate pass?

## A4. Cross-reference with session JSON

Compare `situation_brief.activated_by` with your reconstruction. Discrepancies
between what the sniper logged and what the session records are findings.
Remember: session `observed_at` is UTC — convert to local time before comparing
with log timestamps.

## A5. Output (Mode A)

```markdown
# Sniper Trace: {SYMBOL} @ {TIME}

## Signal Activation
| Pulse | Signal | Status | Strength | Direction |
|-------|--------|--------|----------|-----------|

## Confluence
| Bullish | Bearish | Raw | Noise | Final | Threshold | Pass? |
|---------|---------|-----|-------|-------|-----------|-------|

## Cooldown & Gate
- Last trigger: {time or "none"}
- Cooldown: {active/inactive} ({N} min remaining)
- Gate: {PASS/FAIL: reason}

## Root Cause
[One paragraph: why the trigger did or didn't fire.]
```

---

# Mode B — Multi-Symbol Audit (DEFAULT)

Analyze all watched symbols over a time window. Produce:

1. **Signal health table** — per signal, per symbol, with threshold gaps
2. **Anomaly scan** — suspicious patterns, cooldown violations, bugs
3. **Sniper feedback** — what's working, what needs attention

## B1. Determine scope and timezone

Ask for the time window if not specified. Default: since last sniper restart
(or last 24 hours if log is long-running).

**Determine the machine timezone first** — it affects all timestamp comparisons:

```bash
date +%Z
```

Identify watched symbols:

```bash
grep 'SIGNAL DIAG' data/prod/sniper.log | \
  sed -n 's/.*\[\([A-Z]*\)\] SIGNAL DIAG.*/\1/p' | sort -u
```

## B2. Extract signal data AND rejection reasons

For each symbol, parse all SIGNAL DIAG lines in the window. For each signal:

- **FIRED count**, strength distribution (min, max, avg)
- **REJECTED count**
- **Rejection reason breakdown** — collect the unique `R:reason` strings and
  count how often each appears. This tells you WHY a signal isn't firing.

Use inline Python — the parsing logic is in `references/log_parsing.md`.

## B3. Read config thresholds for each signal

Read the relevant config files to understand what thresholds each signal is
measured against. Key files:

- `config/global_config.yaml` → `sniper.signal_stack.thresholds` — per-signal
  strength thresholds, confidence weights
- `config/strategy_config.yaml` → `regime_parameters` — VII, squeeze, volume,
  CVD thresholds

For each signal, identify the config key and its current value. Example
extraction:

```bash
grep -A20 'signal_stack' config/global_config.yaml
grep -A5 'cvd_intensity_threshold\|squeeze_threshold\|volatility_baseline' config/strategy_config.yaml
```

## B4. Build the Signal Health table

Combining log data (B2) with config thresholds (B3), produce a single table
that shows both **what happened** and **how close/far it was from triggering**:

| Signal | Symbol | Fired | Rejected | Fire Rate | Avg Str | Threshold (config key) | Threshold Gap |
|--------|--------|-------|----------|-----------|---------|------------------------|---------------|
| vol_surge | XAUTUSDT | 0 | 140 | 0% | — | `vii > 1.25 AND vpr > 1.5` | VII avg=1.18 (gap: -0.07), VPR avg=0.11 (gap: -1.39) |
| pos_ext | XAUTUSDT | 0 | 140 | 0% | — | `ls∉[0.6,1.5] OR \|fund\|>0.0005 OR oi>0.01` | all metrics in normal range |
| cvd_momentum | BTCUSDT | 30 | 110 | 21.4% | 0.21 | `cvd_intensity_threshold: 0.10` | avg strength 0.21 (2.1× threshold) |
| squeeze | BTCUSDT | 0 | 140 | 0% | — | `sf < 0.75` (×0.75 multiplier) | sf range=[1.0, 2.2] (gap: +0.25 above threshold) |
| cvd_divergence | BTCUSDT | 0 | 140 | 0% | — | `needs prev CVD + div gap` | 280/282 pulses: `no-prev/div-low` |

**Threshold Gap column**: For fired signals, show how the avg strength compares
to the threshold. For rejected signals, extract the actual metric values from
the rejection reasons and show the gap to the threshold. This tells the user
whether a "dead" signal is truly dead or just slightly below the bar.

### How to extract threshold gaps from rejection reasons

The rejection reason strings contain the actual values. Examples:

| Rejection reason | Extraction |
|-----------------|------------|
| `vii<=1.25\|vpr<=1.5` | VII ≤ 1.25 AND VPR ≤ 1.5 → both must exceed for fire. Get actual VII/VPR from the log line's metrics. |
| `sf=1.031>=0.750` | sf=1.031, threshold=0.750. Signal requires sf < threshold (squeeze = compression). Gap = 1.031 - 0.750 = +0.281. |
| `ls<=1.5&ls>=0.6&\|fund\|<=0.0005&oi<0.01` | All 4 conditions are true (metrics inside normal bands). Signal needs at least one to break. |
| `no-cluster-in-range` | No liquidation cluster within configured ATR radius. |
| `no-prev/div-low` | No previous CVD reading, or divergence magnitude too small. |

Parse these programmatically — extract numeric values where present, compute
the gap to threshold.

## B5. Signal Evaluations

For each signal, write a one-line assessment. Use these heuristics:

| Red flag | What it means |
|----------|---------------|
| Fire rate < 5% AND threshold gap large | Signal is far from triggering — expected in this market, not a bug |
| Fire rate < 5% AND threshold gap small | Signal is near the edge — small threshold tweak could activate it |
| Fire rate = 0% AND reason is "no data" (e.g. no-cluster, no-prev) | Signal depends on rare events — may be inherently sparse |
| Fire rate > 50% with low avg strength | May be firing on noise — check if it discriminates |
| Always fires alone (never part of multi-signal wake) | Low conviction — sniper may ignore it |
| Only fires on one symbol | Symbol-specific bias — verify calibration |

## B6. Anomaly Scan

Check for these patterns:

1. **Dead with small gap**: fire rate = 0% but gap to threshold < 10%. Signal
   is one small market move away from activating — not a bug, but worth noting.
2. **Cooldown violation**: two `[trigger] WAKE` lines for the same symbol less
   than 10 min apart without a `cooldown reset` between them. Note: multiple
   wakes clustering around the same session time is normal (debate latency).
   Only flag if the gap is clearly below the configured cooldown.
3. **Gate fail spike**: gate fail > 50% on a symbol — pre-AI gate is blocking
   most triggers.
4. **Directional lock**: all wakes in one direction with 5+ wakes. Could be
   market trend or signal bias.
5. **Confluence cliff**: avg confluence within 0.05 of threshold — signals
   barely scraping through.

## B7. Sniper Feedback

Three short paragraphs:

1. **What's working well** — discriminating signals, well-calibrated thresholds
2. **What needs attention** — signals that are too strict/loose, anomalies
3. **Suggested changes** — concrete and actionable, with config keys

No speculation without log evidence.

## B8. Output (Mode B)

```markdown
# Sniper Audit: {TIME_WINDOW} ({TIMEZONE})

## 1. Signal Health
[Table from B4 — signal health with threshold gaps]

## 2. Signal Evaluations
[One-line per signal from B5]

## 3. Anomalies
[Findings from B6, or "None detected."]

## 4. Sniper Feedback
[Three paragraphs from B7]
```

---

# Shared Reference

## Log Format Reference

Sniper log uses **local machine time**. Session files and `observed_at` use **UTC**.

### SIGNAL DIAG
```
HH:MM:SS.sss INF [trigger] [SYMBOL] SIGNAL DIAG |
  cvd=<float> | cvd_momentum=<F:strength(path)|R:reason> |
  cvd_divergence=<F:strength|R:reason> |
  cvd_absorption=<F:strength|R:reason> |
  trade_sz=<float>/n=<int> | large_trade=<F:strength(z=N)|R:warmup(N/5)|R:reason> |
  vii=<float>,vpr=<float> | vol_surge=<F:strength|R:reason> |
  squeeze=<F:strength|R:reason> |
  price=<float>,atr=<float> |
  boundary_test=<F:strength|R:reason> |
  liq_hunt=<F:strength|R:reason> |
  ls=<float>,fund=<float>,oi_d=<float> | pos_ext=<F:strength|R:reason>
```

9 signals: `cvd_momentum`, `cvd_divergence`, `cvd_absorption`, `large_trade`,
`volatility_surge` (`vol_surge` in log), `squeeze`, `boundary_test`,
`liquidation_hunt` (`liq_hunt`), `positioning_extreme` (`pos_ext`).

### WAKE (two distinct lines — don't confuse them)

```
# Trigger-engine WAKE — has confluence, gate, regime:
HH:MM:SS.sss INF [trigger] [SYMBOL] WAKE |
  dir=<BULLISH|BEARISH> | confluence=<0.XX> |
  fresh=<N> | memory=<N> |
  active=['signal',...] | gate=<PASS|FAIL> | regime=<name>

# Daemon WAKE UP — simpler, used for session correlation:
HH:MM:SS.sss INF [SniperDaemon] 🔫 [SYMBOL] WAKE UP |
  dir=<BULLISH|BEARISH> | confluence=<0.XX> |
  signals=['signal',...]
```

When counting "wakes", decide whether you want trigger-level (the engine's
decision) or daemon-level (what actually reached the executor). Usually the
trigger WAKE is more useful for signal analysis.

## Reference Files

- `src/sniper/trigger.py` — signal detectors, ConfluenceEngine, gate, cooldown.
- `src/sniper/scout.py` — market metrics harvesting.
- `config/global_config.yaml` → `sniper.signal_stack` — thresholds, weights,
  cooldown, regime modifiers.
- `config/strategy_config.yaml` → `regime_parameters` — VII/squeeze/trend
  thresholds, CVD intensity, volume participation.
- `data/prod/sniper.log` — SIGNAL DIAG and WAKE lines (local time).
- `data/prod/sessions/` — session JSONs (UTC timestamps).
- `references/log_parsing.md` — reusable Python parser for log lines.
