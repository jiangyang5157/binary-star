---
name: comprehensive-code-audit
description: Use when the user asks for a thorough project audit covering logic errors, prompt issues, system bugs, sniper order-management risks, code vulnerabilities, and edge-case test coverage. Also use when the user wants a comprehensive codebase health report saved to docs/.
---

# Comprehensive Code Audit

## Overview

Run a structured multi-dimensional audit of the entire codebase. Dispatch parallel subagents across six audit dimensions, then synthesize findings into a single dated markdown report in `docs/`.

## Core Principle

**Every finding must cite a specific file path and line number.** No vague claims. No "consider reviewing X" without pointing to exactly what's wrong and why.

## Audit Dimensions

The audit runs six dimensions in parallel:

### D1: Logic Errors
Scan for:
- Off-by-one errors in array slicing, window calculations, index lookups
- Inverted boolean conditions (>= vs >, <= vs <)
- Missing `await` on async calls
- Division-by-zero risks (unchecked denominators in math_utils, volume_profile, liquidation_estimator)
- Incorrect sign handling in P&L, position sizing, or fee calculations
- Dataframe column/index misalignment in market_observer, topography_engine
- Mutable default arguments in function signatures
- Race conditions in SniperDaemon pulse loops (shared state between scout→trigger→guardian phases)
- Infinite loops with no exit condition or timeout

### D2: Prompt Engineering Problems
Scan all files under `config/prompts/` and any inline prompt strings in `src/agent/`:
- Contradictory instructions (e.g., "be aggressive" + "prioritize safety")
- Missing constraints that allow degenerate outputs
- Token-inefficient verbosity (dead words that don't improve agent behavior)
- Ambiguous action verbs ("consider", "maybe", "if appropriate") without decision criteria
- Missing output format specification (agents may return unparseable JSON)
- Hallucination-prone claims about system capabilities
- Prompt injection vulnerabilities (user-controlled data interpolated unescaped into prompts)
- Missing few-shot examples where the task is underspecified
- Over-constrained prompts that prevent correct behavior in edge cases

### D3: System Bugs
Scan for:
- Uncaught exceptions in non-critical paths that can cascade into critical failures
- Improper resource cleanup (open file handles, unclosed HTTP sessions, websocket leaks)
- Incorrect config key lookups (KeyError risks when config sections are optional)
- Timezone/datetime handling bugs (naive vs aware datetime mixing)
- Floating-point comparison without tolerance
- Singleton/module-level mutable state that leaks between sessions
- Import circular dependency risks
- Logging that masks errors (bare `except:` or `except Exception:` with no log)

### D4: Sniper Order Management & Risk Bugs
Deep-dive into `src/sniper/` and `src/agent/order_executor.py`:
- **Guardian OCO lifecycle**: Verify OCO orders are never left stale after position changes. Check that cancel-then-replace is atomic from the exchange's perspective.
- **Trailing stop migration**: Verify trailing stop price only moves in the favorable direction. Check for reversal bugs.
- **Emergency market-close fallback**: Verify it triggers on ALL failure paths (network error, API error, timeout, malformed response). No naked positions.
- **Position size validation**: Check for integer overflow, precision truncation, min-notional violations before order submission.
- **Confluence engine scoring**: Verify signal weights sum correctly. Check for NaN propagation through the 14-signal stack.
- **Pre-trigger gate**: Verify `max_price_to_structure_atr` correctly blocks untradeable setups. Check boundary conditions (price exactly at HVN).
- **Adaptive cooldown**: Verify decay half-lives are applied correctly. Check for cooldown bypass paths.
- **Cross-symbol contamination**: Verify state isolation between BTC and XAUT SniperScout instances.
- **Rate limiter interaction**: Check that CongestionController doesn't silently drop critical order operations.

### D5: Code Vulnerabilities
Scan for:
- Hardcoded secrets, API keys, or tokens (even in comments)
- SQL/command injection risks in dashboard or script parameters
- Pickle deserialization of untrusted data
- `eval()` or `exec()` with any variable input
- Missing authentication checks on dashboard API endpoints
- Insecure file path handling (path traversal in export_session, sandbox scripts)
- Dependency vulnerabilities (check requirements.txt / pyproject.toml for known CVEs)
- WebSocket security (origin validation, rate limiting on dashboard)

### D6: Edge-Case Test Coverage
Analyze `tests/` against `src/`:
- **Coverage gap analysis**: Which src/ modules have 0 tests?
- **Boundary tests**: Are edge cases tested for critical math functions? (zero, negative, NaN, Inf, min/max bounds)
- **Error-path tests**: Are exception handlers exercised? Mock failure injection coverage.
- **Concurrency tests**: Any test that exercises the Sniper pulse loop with interleaved phases?
- **State machine tests**: Binary Star debate rounds — are all terminal states (PASS, WEAK, max_rounds) covered?
- **Config edge cases**: Missing config sections, malformed YAML, symbol override edge cases
- **Exchange API error simulation**: Order rejection, partial fill, network timeout — are these tested?

## Execution Workflow

### Phase 1: Parallel Audit (6 subagents)

Dispatch all six dimension agents simultaneously. Each agent receives:
- The dimension's specific audit checklist (above)
- Instructions to return findings as structured markdown with file:line citations
- A limit of 15 findings per dimension (prioritize severity)

### Phase 2: Synthesis

Combine all findings into a single report. The synthesis agent:
- Removes duplicates (same bug found by multiple dimensions)
- Sorts by severity: CRITICAL > HIGH > MEDIUM > LOW
- Adds a severity justification for each finding
- Produces an executive summary with counts by severity

### Phase 3: Write Report

Write the final report to `docs/audit_report_YYYYMMDD_HHMMSS.md` with this structure:

```markdown
# Comprehensive Audit Report — <timestamp>

## Executive Summary
- Total findings: N
- CRITICAL: N | HIGH: N | MEDIUM: N | LOW: N

## CRITICAL Findings
### [D#] Title
- **File**: path:line
- **Severity**: CRITICAL
- **Description**: ...
- **Impact**: ...
- **Recommendation**: ...

[... repeat for all severities ...]

## Coverage Summary
| Module | Test Files | Functions Tested | Edge Cases Covered |
|--------|-----------|-----------------|-------------------|

## Appendix: Full Finding Index
```

## What NOT to Do

- Do NOT modify any source code during the audit
- Do NOT run commands that modify state (no git operations, no pip install)
- Do NOT guess — if uncertain about a finding, mark it as LOW severity and note the uncertainty
- Do NOT skip a dimension because "it's probably fine"
- Do NOT produce findings without file:line citations
