# Token Consumption Analysis — v26.7.13

> Source: `data/prod/session.log`
> Generated: 2026-07-17
> Project version: 26.7.13

## Overview

- **Sessions analyzed**: 16 (19 cycle begins, 1 flow failure, 3 with no token entries)
- **Total LLM API calls**: 128
- **Total tokens consumed**: 2,543,644
- **Composition**: 2,188,559 input (86%) + 355,085 output (14%)

---

## Per LLM API Call

One call = one agent invocation including all tool-use iterations.

| Metric | Tokens |
|--------|--------|
| **Avg** | **19,872** |
| Median | 19,886 |
| P25 | 17,226 |
| P75 | 22,112 |
| StdDev | 3,414 |
| Min | 13,192 |
| Max | 28,343 |

---

## Per Agent Step

Sum of all API calls within a single planning/audit/synthesis step.

| Step | Avg Tokens | Calls/Step | Median | Range |
|------|-----------|-----------|--------|-------|
| R1 Planning | **54,161** | 2.9 | 38,816 | 19,302 – 125,141 |
| Critic Audit | **36,376** | 2.1 | 32,766 | 13,270 – 73,921 |
| R2 Planning | **91,612** | 4.1 | 92,459 | 20,320 – 152,712 |
| Synthesis | **61,386** | 2.6 | 53,238 | 21,772 – 96,620 |

R2 is ~70% more expensive than R1 due to carrying full debate history + critic feedback in context.

---

## Per Session

| Metric | All (n=16) | 1-Round PASS/WEAK (n=7) | 2-Round CONSTRUCTIVE (n=9) |
|--------|-----------|------------------------|---------------------------|
| **Avg** | **158,978** | **71,355** | **227,129** |
| Median | 136,299 | 51,347 | 240,908 |
| Min | 35,741 | 35,741 | 86,314 |
| Max | 341,392 | 127,825 | 341,392 |

- **44%** of sessions exit at R1 (PASS or WEAK), costing ~71K tokens
- **56%** go to R2 (CONSTRUCTIVE → refine), costing ~227K tokens
- 2-round sessions cost **3.2×** more than 1-round

---

## Cost Estimate (DeepSeek v4 Pro)

Pricing: ~$0.28/M input, ~$1.10/M output.

| Item | Cost |
|------|------|
| **Total (16 sessions)** | **$1.00** |
| **Avg per session** | **$0.063** |
| 1-round avg | $0.028 |
| 2-round avg | $0.090 |
| R1 Planning | $0.023/session |
| Critic Audit | $0.012/session |
| R2 Planning | $0.035/occurrence |
| Synthesis | $0.025/occurrence |

---

## Session Flow Types

Typical call sequences observed:

```
1-round (PASS/WEAK):     R1 → R1 → C                    (~51K tokens)
1-round (multi-call R1): R1 → R1 → R1 → R1 → R1 → C     (~120K tokens)
2-round:                 R1 → R1 → C → R2 → R2 → C       (~145K tokens)
2-round + Synthesis:     R1 → C → R2 → C → S → S         (~241K tokens)
2-round (heavy):         R1 → R1 → C → R2 → R2 → C → S   (~330K tokens)
```

Flow type depends on:
- How many tool calls Session Agent makes to converge on a plan
- Whether Critic gives CONSTRUCTIVE (→ R2) or PASS/WEAK (→ exit)
- Whether Session_Synthesis is triggered for final decision assembly

---

## Key Takeaways

1. **Extremely cheap**: ~$0.06 per debate session. Even 100 sessions/day ≈ $6.
2. **R2 is the dominant cost**: It carries full debate history and costs ~70% more than R1.
3. **Early exit saves 3×**: 44% of sessions PASS/WEAK at R1, avoiding R2 entirely.
4. **Input dominates**: 86% of tokens are input (prompt context). Reducing prompt size has more impact than limiting output.
5. **Critic is the cheapest step**: Most stable token consumption, purely audit with minimal tool use.
