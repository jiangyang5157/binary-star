---
name: order-management-audit
description: Run a forensic audit on the order management and execution system. Use when the user wants to review order execution logic, audit MarginOrderExecutor or SniperDaemon guardian behavior, check OCO lifecycle risks, verify pivot/preserve/force-close scenarios, assess exit-ladder and sl_lock correctness, evaluate restart/recovery edge cases, find order-management bugs, or assess risk of naked-position windows. Triggers on: "order management review", "execution audit", "guardian audit", "check order executor", "review sniper trade logic", "audit OCO handling", "position management risk", "trailing stop review", "exit ladder audit". Always use when the user asks about the safety or correctness of the trade execution pipeline.
compatibility: Requires read access to src/agent/order_executor.py, src/infrastructure/binance/margin_client.py, run_sniper.py (guardian section), config/global_config.yaml (guardian section), and tests/system/test_order_executor.py.
---

# Order Management Audit

## Overview

Run a structured, multi-dimensional audit of the order management and execution pipeline. The audit traces through the full lifecycle — from AI opinion to entry, through Guardian protection, exit ladder, sl_lock, and eventual exit — checking every branch, every failure path, and every edge case.

**Default mode**: read-only analysis producing a structured report. **--fix mode**: also applies verified fixes (after review).

## Parameters

The user may pass these flags (parse from their message):
- `--fix`: After presenting findings, apply fixes for confirmed bugs. Each fix is shown as a diff for user approval before applying.
- `--symbol <BTC|XAUT>`: Focus the audit on a specific symbol's configuration path. Affects which precision/qty/buffer values are checked.
- `--dimension <name>`: Run only one audit dimension (e.g., `oco-lifecycle`, `pivot`, `exit-ladder`). Without this, run all.

If no flags: run all dimensions, report-only.

## Audit Dimensions

Run these in parallel for efficiency. Each dimension spawns a subagent that reads the relevant source files and produces findings with file:line citations.

### D1: OCO Lifecycle — Synthetic OCO Correctness

**Source files**: `src/agent/order_executor.py`, `src/infrastructure/binance/margin_client.py`

Trace every path where OCO orders are placed, cancelled, or replaced:

1. **Cancel-Place Gap (Naked Window)**
   - In `_optimize_same_direction()` line 438: cancel_all → re-verify position → place_oco. What if price moves through SL during this window?
   - In `_try_exit_ladder()` line 693: cancel_all → partial_close → re-verify → place_oco. Three API calls with position exposed between them.
   - In `_apply_sl_lock()` line 805: cancel_all → re-verify → place_oco. Same exposure.
   - Measure: for each site, estimate the wall-clock duration of the naked window. Flag any site missing the re-verify step.

2. **Emergency Close Completeness**
   - Every `place_oco_order` call that returns False must trigger `execute_market_close`. Audit every call site:
     - `_optimize_same_direction()` (line ~504)
     - `guardian_check()` Case 3 (line ~298)
     - `guardian_check()` Case 4 qty re-align (line ~349)
     - `_try_exit_ladder()` (line ~740)
     - `_apply_sl_lock()` (line ~830)
     - `find_level_and_sync_sl()` (line ~678)
   - For each: verify the emergency close itself is checked for failure (`if not self.client.execute_market_close`), and that the caller correctly handles the failure (retry next pulse vs. clear state vs. sentinel).

3. **OCO Qty Re-alignment (Case 4)**
   - The qty mismatch detection (line ~332) compares `oco_sl_qty` to `abs(net_qty)`.
   - Check: does it correctly handle partial fills? (SL partially executed but remaining qty > 0)
   - Check: the re-align re-reads TP/SL from active orders. If both TP and SL orders exist, this works. What if only one leg remains? (line ~369 logs critical but does NOT emergency close — is this correct?)

4. **SL Slippage Buffer Direction**
   - Verify `buffered_sl` calculation is directionally correct at every call site:
     - LONG (SELL exit): `sl - buffer` (trigger > limit, limit below trigger for sell) — correct.
     - SHORT (BUY exit): `sl + buffer` (trigger < limit, limit above trigger for buy) — correct.
   - Audit every call site for copy-paste errors (e.g., SHORT buffer applied to LONG).

### D2: Pivot Logic — Direction Changes While Holding

**Source file**: `src/agent/order_executor.py` (sync_with_opinion, lines 64-136)

**Current behavior**: Pivots are **blocked**. When the AI opinion opposes an existing position (Scenario A), the bot returns `None` and takes zero action — no force close, no new entry, no OCO manipulation. The Guardian continues protecting the existing position.

1. **Pivot Block Correctness**
   - Verify `sync_with_opinion` Scenario A (line 114-124): `current_direction != opinion_direction` → log warning, return None.
   - The existing position is left under Guardian protection. Is this always safe?
   - Risk: if the AI is right about the pivot (e.g., trend reversal), the bot will ride the position into a loss until Guardian's SL is hit. The bot relies on the original SL to limit damage.
   - Trade-off: blocking pivots prevents the bot from interfering with manual positions or restart-gap reconstruction. The cost is delayed reaction to genuine trend reversals.

2. **Scenario B: Same-Direction Optimization**
   - When `current_direction == opinion_direction` (Scenario B), the bot optimizes TP/SL: greedy TP (widest), tightest SL (most protective).
   - `_optimize_same_direction()` (line 438-520): cancels old OCO → re-verifies position → places new OCO for full net_qty.
   - Audit: the cancel-before-place creates a naked window. On OCO placement failure → emergency market close.
   - Check: `best_tp` and `best_sl` comparison logic is directionally correct (lines 464-478).

3. **Scenario C: FLAT → New Entry**
   - No position exists → clears stale orders → places LIMIT entry (line 103-108).
   - Audit: qty calculation uses `_calculate_target_qty` — verify risk-per-trade and precision rounding.
   - Check: what if `cancel_all_symbol_orders` fails? Code returns None (aborts). Position remains flat — safe.

4. **Safety Gates**
   - NEUTRAL opinions → immediate return (line 71-73). No order action.
   - Symbol whitelist check (line ~77): unconfigured symbols rejected before any API calls.
   - Config validation (line 86-94): missing/corrupt config → abort before touching exchange.
   - `_EMERGENCY_CLOSED_SENTINEL` (-1) from Scenario B signals daemon to clear trade_state without cooldown reset.

### D3: Guardian Pulse Cycle — Protection State Machine

**Source file**: `src/agent/order_executor.py` (guardian_check, lines 142-432)

1. **Intent Check (STEP 1)**
   - Empty trade_state + no position → early return. Correct.
   - Empty trade_state + position WITH OCO → reconstruct (line 187-205). 
   - Check: reconstruction only sets direction, tp_price, sl_price. It does NOT set `entry_filled_at`, `projected_holding_hours`, or `entry_atr`. Does downstream code (exit ladder, sl_lock) require these? (Answer: exit ladder uses avg_entry from exchange API, sl_lock uses avg_entry + (tp - avg_entry) * sl_lock — neither needs those fields. OK.)
   - Empty trade_state + position WITHOUT OCO → returns without action (line ~231). This means an unprotected position after restart is NOT protected until the next AI session! Is this intentional? (It's a trade-off: the daemon doesn't know the AI's intended TP/SL, so it can't place protection. But it means the position runs naked until the next trigger.)

2. **Case 1: No Position — Entry Pending/Expired**
   - Entry timeout check (line ~218): uses `projected_waiting_hours`. What if this field is missing from trade_state? (Defaults to 24.0 — reasonable.)
   - Expired entry: cancel_order → return {}. What if cancel fails? (Order may already be filled — cancel returns True for unknown orders. OK.)
   - Flat with entry_filled_at: cancel_all → return {}. This clears trade state. Good.

3. **Case 2: Direction Sanity Check**
   - Compares intent direction vs actual net_qty sign (line 237-253).
   - Throttles logging via `_last_conflict_key` to avoid spam. Good.
   - On conflict: cancels all orders via `cancel_all_symbol_orders()`. This removes any wrong-side OCO protection.
   - But: does NOT clear trade_state — returns it unchanged. Since `trade_state["direction"]` still disagrees with the actual position sign, Case 2 will fire again on the next pulse (looping). The position stays naked until external intervention (manual close) or until the trade_state is cleared elsewhere.
   - Audit question: should Case 2 clear trade_state so that Case 3 (unprotected position) can emergency-close on the next pulse? Currently the direction mismatch creates a persistent loop.

4. **Case 3: Position Without OCO — Emergency or Place**
   - Missing TP/SL in trade_state → emergency close (line 262-267).
   - SL breached check (line 269-287): uses current ticker price. What if ticker is stale or zero?
   - Normal case: place OCO. Stale entry order cancelled first. Good.
   - Check: `entry_filled_at` is set to now() even if the position was entered hours ago (line 313-314). This timestamp is used nowhere downstream — harmless but confusing.

5. **Case 4: Protected Position — Partial TP + Trailing**
   - Covered in detail in D4 below.

### D4: Exit Ladder + sl_lock — Sequential Correctness

**Source file**: `src/agent/order_executor.py` (_try_partial_tp: line 693, _migrate_dynamic_sl: line 805, Case 4 trailing dispatch: line 413-432)

1. **Level Loop Correctness**
   - `_try_partial_tp` loops `for i in range(start_level, len(levels))`, stopping at first unmet threshold (`break` at ~728).
   - This is sequential: L1 must fire before L2, etc. Correct and intentional.
   - Check: after each partial close, the remaining qty is **not** re-read from the exchange — it is computed deterministically as `abs(live_net_qty) - tp_qty`. If the deterministic remainder drops below min_qty, the remaining OCO may be for a dust amount. Is there a min-notional check?

2. **SL Migration Direction**
   - `_migrate_dynamic_sl()`: LONG → `max(current_sl, price - N*ATR)`, SHORT → `min(current_sl, price + N*ATR)`.
   - This means SL only moves in the favorable direction (up for LONG, down for SHORT). Correct.
   - Rounding toward safety uses `math.floor()` for LONG and `math.ceil()` for SHORT (lines 833-837 in current code). This is correct: LONG SL rounds down (slightly tighter), SHORT SL rounds up (slightly tighter) — both bias toward safety.

3. **Trailing Distance Source**
   - The trailing distance comes from `levels[active_idx]["sl_distance_atr"]` where `active_idx = new_level - 1` (line 417-419).
   - After L1 fires, `new_level=1`, `active_idx=0` → uses L1's `sl_distance_atr` (0.0 → no trailing). Correct.
   - After L2 fires, `new_level=2`, `active_idx=1` → uses L2's `sl_distance_atr` (1.0). Correct.
   - After L3 fires, `new_level=3`, `active_idx=2` → uses L3's `sl_distance_atr` (0.75). Correct.
   - Edge case: if `active_idx >= len(levels)` (all levels exhausted), trailing is skipped (line ~418). Correct.

4. **Level Memory Across Pulses**
   - The daemon tracks `_symbol_level[symbol]` in memory — not persisted.
   - On qty change: level is reset to None, re-initialized via `find_level_and_sync_sl` on next pulse.
   - On daemon restart: level is None, re-initialized same way.
   - `find_level_and_sync_sl()` (lines 575-691) determines level from exchange state:
     - If SL < entry (LONG) → L1 not fired → return 0.
     - If SL >= entry → scan deviation against level thresholds → return first unmet.
   - Check: the scan loop uses `for i in range(1, len(levels))` starting at index 1 (L2). This means L1 is detected by SL position, L2+ by deviation. Is this correct when multi-level fired in a single pulse? (The loop advances `next_level` for each met threshold → yes.)

### D5: Daemon Integration — SniperDaemon + Executor Boundary

**Source file**: `run_sniper.py` (_guardian_check: line 498, _attempt_trade_execution: line 415)

1. **Trade State Lifecycle**
   - Created in `_attempt_trade_execution()` (line 415-477): after `sync_with_opinion` returns an order_id.
   - Updated by `_optimize_same_direction` return value: merged into existing state.
   - Updated by `_guardian_check()` (line 498-558): replaces trade_state when executor returns modified dict.
   - Cleared when executor returns `{}`: pops trade_state, level, last_qty, **and resets cooldown** (`last_trigger_time = None`, line ~553).
   - Cleared on `_EMERGENCY_CLOSED_SENTINEL` (line 466-467): pops trade_state. Cooldown is **NOT** reset — emergency closes retain the cooling-off period.

2. **Qty Change Detection**
   - `_guardian_check()` compares `net_qty` to `_symbol_last_qty[symbol]` (line 518).
   - If changed: resets `_symbol_level` (line 521). Correct.
   - But: the comparison uses `1e-8` tolerance. A round-trip precision truncation (e.g., 0.1 → 0.1000000001) could trigger a spurious reset. The threshold seems fine for meaningful changes but flag if this causes issues.

3. **Level Initialization on Missing**
   - When `_symbol_level.get(symbol) is None` and trade_state has direction → calls `find_level_and_sync_sl()` (line 525-531).
   - This happens on: daemon start, qty change, or first pulse after trade entry.
   - Check: `find_level_and_sync_sl` may call `cancel_all_symbol_orders` and `place_oco_order` — API mutations during what's supposed to be a "find" operation. The function name undersells its side effects. This is intentional (syncs SL to match found level) but the caller should be aware.

4. **Session Dispatch Gate (`has_active`)**
   - `has_active` is trade_state-based: `bool(self.trade_states.get(sym, {}).get("direction"))` (line 266).
   - This blocks new sessions when the bot has an active trade (pending entry or filled position). Manual positions without trade_state are allowed through — `sync_with_opinion` handles conflicts, and cooldown regulates frequency.
   - Guardian runs FIRST (step 0.5, line ~171), then AI session dispatch (step 3, line ~269). `has_active` is evaluated AFTER guardian — so if guardian clears trade_state (entry expired or position closed), `has_active` becomes False and AI CAN fire in the same pulse.
   - **Cooldown auto-reset amplifies this**: Guardian clearing trade_state also resets cooldown (`last_trigger_time = None`, line ~553). This means a trigger on the very next pulse has zero barriers — no trade_state, no cooldown. The risk of overtrading (position closed → immediate re-entry) is higher than before.
   - Emergency close (`_EMERGENCY_CLOSED_SENTINEL`) does NOT go through this path — cooldown is preserved, providing a cooling-off period after forced exits.
   - Audit question: is same-pulse re-entry after a Guardian-cleared position desirable, or should there be a minimum gap?

### D6: Manual Intervention Scenarios

**Source files**: `run_sniper.py` (daemon), `src/agent/order_executor.py` (executor)

1. **Manual Qty Increase**
   - User adds to position externally → net_qty increases.
   - Daemon detects qty change → resets level → calls find_level_and_sync_sl.
   - OCO qty mismatch detected (Case 4) → re-aligns OCO to new qty.
   - Trace: does the re-align preserve the correct TP/SL prices? (Yes — reads from active orders first, falls back to trade_state.)

2. **Manual Qty Decrease (Partial Close)**
   - User closes part of position → net_qty decreases.
   - Same flow as above. OCO re-aligned to new qty.
   - Check: what if user's partial close accidentally filled the TP order? The remaining SL order would be for the original qty. The qty mismatch check should catch this.

3. **Manual Full Close**
   - User closes entire position → net_qty ≈ 0.
   - Guardian Case 1: no position, has entry_filled_at → cancel_all, clear trade_state.
   - But: what if the user's market close left a dust amount (< tolerance)? Guardian sees "no position" and clears state, leaving the dust unprotected. The dust is economically insignificant but could accumulate.

4. **Manual Reverse (Close + Open Opposite)**
   - User closes LONG and opens SHORT externally.
   - Guardian sees: net_qty < -tolerance, trade_state says LONG.
   - Case 2 (direction sanity): intent=LONG but is_short_pos=True → logs warning, returns early.
   - Position is now SHORT with no protection (or worse, with LONG-protection OCO still on exchange).
   - This is a **real risk**. The direction sanity check detects the mismatch but does NOT fix it.

### D7: Restart & Recovery

1. **Clean Restart (No Positions)**
   - Daemon starts → scouts initialized → trade_states empty → guardian skips (no trade_state) → normal monitoring.

2. **Restart With Active Positions**
   - Daemon starts → trade_states empty → guardian_check called with `{}`.
   - Guardian STEP 1: empty trade_state + position + OCO → reconstruct from exchange.
   - Level is None → `find_level_and_sync_sl` called → level initialized.
   - Next pulse: guardian protects normally.
   - Check: what happens during the FIRST pulse after restart? Guardian runs with reconstructed trade_state. If OCO exists, Case 4 (protected) runs. But `entry_filled_at` is not in reconstructed state — is it needed? (Only for the "flat with entry_filled_at" cleanup path — not needed for active protection.)

3. **Restart With Unprotected Position**
   - Empty trade_state + position + NO OCO → guardian returns early (line ~231).
   - Position runs naked until next AI trigger.
   - Risk window: up to `pulse_interval * cooldown` minutes.

4. **Restart During Entry Pending**
   - Empty trade_state + no position + entry order on exchange.
   - Guardian sees no position, no trade_state → returns early.
   - The entry order is NOT tracked. If it fills, guardian won't know until next AI session places OCO (or until pulse detects position without OCO in Case 3 — but only if trade_state existed, which it doesn't).

### D8: Exchange API Failure Resilience

For every API call in the execution path, check failure handling:

1. **get_symbol_position / get_active_orders**: Called at start of guardian and sync. Failures propagate as exceptions caught by daemon's outer try/except (line ~130) — entire pulse skipped. Position unprotected for one pulse.

2. **get_ticker_price**: Returns 0.0 on failure. ~~FIXED/MITIGATED~~ There is now an explicit guard at lines 270-272: `if not current_price or current_price <= 0: return trade_state, None`. Price=0 (or falsy) is caught and returned early, before the SL breach check ever runs. This prevents a ticker failure from triggering a false emergency close.

3. **cancel_all_symbol_orders**: Returns False on failure. Every call site checks this and either aborts (returns early) or proceeds anyway. Audit each site for the correct behavior.

4. **place_oco_order**: Returns False on failure → emergency close. Correct.

5. **execute_market_close**: Returns False on failure. Caller retries next pulse (keeps trade_state). But: the position is naked until the retry succeeds.

## Execution Workflow

### Step 1: Scope & Triage

Ask the user (or infer from flags):
- Which dimensions? (all 8, or specific ones)
- Which symbol? (affects config path and precision checks)
- Report-only or --fix?

### Step 2: Parallel Dimension Audit

Read `references/checklists.md` for the detailed per-dimension checklist. For each selected dimension, spawn a subagent that:
1. Reads the tagged source files
2. Traces every code path in that dimension
3. Produces findings with: severity (CRITICAL/HIGH/MEDIUM/LOW), file:line, description, impact, and recommendation

### Step 3: Synthesize Report

Combine findings, deduplicate, sort by severity. Produce:

```markdown
# Order Management Audit Report — <timestamp>
## Executive Summary
- Dimensions audited: N
- Total findings: N (CRITICAL: N, HIGH: N, MEDIUM: N, LOW: N)
- Positions at risk of naked exposure: N sites
- Emergency close gaps: N sites
- Restart/recovery risks: N

## CRITICAL Findings
### [D#] Title
- **File**: path:line
- **Severity**: CRITICAL
- **Description**: ...
- **Impact**: what's the worst case?
- **Recommendation**: specific fix

[... repeat for all severities ...]

## Risk Matrix
| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|

## Appendix: Full Finding Index
```

### Step 4: Present & Act

Write the report to `docs/order_management_audit_YYYYMMDD_HHMMSS.md`.

If `--fix` is NOT set: present the summary and point to the report file. Stop.

If `--fix` IS set: for each HIGH+ finding, show the proposed fix as a diff. Ask user approval before applying each one. Apply fixes using Edit tool. After all fixes, suggest running the test suite.

### Risk Assessment Framework

For each finding, assess using `references/risk-matrix.md`:
- **Likelihood**: how often does the triggering condition occur?
- **Impact**: worst-case financial outcome (naked position duration × ATR × position size)
- **Detectability**: would the operator notice before damage occurs?
- **Mitigation**: what change eliminates or reduces the risk?

## What NOT to Do

- Do NOT modify source code unless `--fix` is set AND the user approved the specific change
- Do NOT run the sniper daemon or place real orders
- Do NOT produce findings without file:line citations
- Do NOT skip dimensions because they "look fine"
- Do NOT suggest architectural rewrites — fixes should be minimal and surgical, per CLAUDE.md principles
- Do NOT guess about exchange behavior — if a scenario depends on Binance API semantics, note the assumption
