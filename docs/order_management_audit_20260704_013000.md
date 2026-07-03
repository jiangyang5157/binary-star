# Order Management Audit Report — 2026-07-04 01:30 UTC

## Executive Summary

- **Dimensions audited**: 8 (D1–D8)
- **Total findings**: 45 (CRITICAL: 10 | HIGH: 10 | MEDIUM: 18 | LOW: 7)
- **Naked position exposure sites**: 5 distinct code paths
- **Emergency close gaps**: 3 distinct failure modes
- **Restart/recovery risks**: 4 scenarios

### Post-Review Corrections
Two HIGH findings downgraded after manual verification:
- **D5 HIGH #1** (cooldown tight loop): Invalid — `set_triggered("ACTIVE_POSITION")` at `run_sniper.py:403` refreshes cooldown every pulse while `has_active` blocks. Cooldown reset only matters when trade_state IS cleared, at which point re-evaluation is correct behavior. → **Removed**.
- **D6 HIGH #2** (manual close cooldown reset): Overstated — cooldown reset accelerates re-entry by 25–60 min but does not change the fundamental outcome. User should disable `--trade` to prevent bot re-entry, not rely on cooldown. → **Downgraded to LOW**.

### Recent Changes Audited (v26.7.05)
- `has_active` reverted to trade_state-based: `bool(trade_states.get(sym, {}).get("direction"))`
- Cooldown auto-reset on Guardian trade_state clear
- Emergency close (`_EMERGENCY_CLOSED_SENTINEL`) preserves cooldown

---

## CRITICAL Findings

### [D2] Pivot Fully Blocked — No Path to Align with Opposite Opinion
- **File**: `src/agent/order_executor.py:119-124`
- **Severity**: CRITICAL
- **Description**: When `current_direction != opinion_direction`, the code unconditionally returns `None` with "pivot blocked." Neither Case A-1 (force-close unprotected) nor Case A-2 (preserve+new entry) is implemented. An AI signal in the opposite direction is permanently ignored, and unprotected opposing positions run naked indefinitely.
- **Impact**: Sustained opposite-direction AI signals are wasted. Unprotected positions have unlimited downside risk with no self-correction.
- **Recommendation**: Implement Case A-1 (force-close unprotected opposing) at minimum. For protected opposing, at minimum alert that position is counter-signal.

### [D1] Two Emergency Close Failure Paths Return `position_intact=True`, Abandoning Naked Positions
- **File**: `src/agent/order_executor.py:513` (_optimize_same_direction), `src/agent/order_executor.py:871` (_migrate_dynamic_sl)
- **Severity**: CRITICAL
- **Description**: When `place_oco_order` fails AND `execute_market_close` also fails, both methods return `(True, None)` — claiming position is intact when it is in fact naked (orders cancelled, no new OCO placed, emergency close failed). The caller sees `position_intact=True` and takes no action. The next guardian pulse finds no SL orders and returns early without protection.
- **Impact**: Naked position persists indefinitely. No self-healing, no escalation. The position runs unprotected until manual intervention or a fortuitous price move.
- **Recommendation**: Return `(False, None)` on emergency close failure so the daemon emits `_EMERGENCY_CLOSED_SENTINEL`. Alternatively, keep `trade_state` alive so the next guardian pulse re-attempts OCO placement.

### [D2] Market Close Returns True for Partial Fills — Residual Quantity Ignored
- **File**: `src/infrastructure/binance/margin_client.py:210-230`
- **Severity**: CRITICAL
- **Description**: `execute_market_close` sends a MARKET order but never verifies fill completeness. A partial fill returns `True`, leaving residual quantity. Every emergency-close call chain in `order_executor.py` relies on this return value to decide whether to clear `trade_state`.
- **Impact**: After a partial-fill emergency close, `trade_state` is cleared but residual position remains on exchange. The guardian may skip the residual position (no `trade_state`, no SL), leaving it permanently unprotected.
- **Recommendation**: Re-query position after MARKET order. If residual remains, retry with updated quantity (max 3 attempts).

### [D3] OCO Qty Mismatch With No Corrective Action Leaves Position Unprotected
- **File**: `src/agent/order_executor.py:365-366`
- **Severity**: CRITICAL
- **Description**: When OCO SL qty diverges from position qty and neither TP nor SL can be found in active orders, the code logs CRITICAL and falls through with no corrective action — no emergency close, no re-placement, no retry.
- **Impact**: Position runs with mismatched protection. Partial TP execution that consumed the TP order but left stale SL qty is a real trigger scenario.
- **Recommendation**: Trigger emergency close in this branch, matching the pattern at lines 314-319 for OCO placement failures.

### [D6] Direction Flip Dead Loop — Trade State Stuck, Position Unprotected Permanently
- **File**: `src/agent/order_executor.py:248-250`
- **Severity**: CRITICAL
- **Description**: When direction sanity check detects intent vs. reality mismatch, it cancels all orders and returns `(trade_state, None)`. The comment says "next pulse Case 3 will emergency-close" — but this is **impossible**: Case 2 fires again (same conditions) and returns before Case 3 is reached. The position is trapped in a loop: every pulse cancels orders, nothing re-protects, nothing closes.
- **Impact**: User who manually flips direction gets a position with zero protection. Bot is permanently stuck for that symbol — `has_active` stays `True`, blocking new sessions. Only recovery: daemon restart.
- **Recommendation**: Emergency-close the position when direction flips instead of returning before Case 3. At minimum, clear `trade_state` so Case 1's reconstruction can fire.

### [D7] Position Naked After Restart When Entry Fills During Downtime
- **File**: `src/agent/order_executor.py:179-198`
- **Severity**: CRITICAL
- **Description**: After restart, if position exists WITHOUT stop-loss (entry filled during downtime, guardian never placed OCO), STEP 1 returns `({}, None)` without placing protection. The daemon interprets empty dict as "clear trade_state" and pops state. Next pulse: same cycle repeats. Position permanently naked.
- **Impact**: Open position runs without any SL/TP. Unlimited downside. Guardian's sole purpose is protection — it silently abandons the position every pulse.
- **Recommendation**: In STEP 1, when `has_position` is True but `has_sl` is False, fall through to Case 3 to place emergency OCO protection.

### [D7] Orphaned Entry Order After Restart Never Tracked or Cancelled
- **File**: `src/agent/order_executor.py:197-198`
- **Severity**: CRITICAL
- **Description**: After restart, pending entry orders without a position are not tracked — guardian returns early. The entry order sits on exchange indefinitely. If it fills, creates naked position (see D7 finding above). In `--llm`-off mode, `sync_with_opinion` never runs, so orphan is never cleaned up.
- **Impact**: Stale entry ties up margin. If price reaches entry level, fills silently with no OCO follow-up. Two entries could fill simultaneously if a new session places a second entry.
- **Recommendation**: Add startup reconciliation: query open orders for all symbols, cancel any entry-side orders without corresponding trade_state.

### [D8] `get_active_orders` Silently Returns Empty List on API Failure
- **File**: `src/infrastructure/binance/margin_client.py:115-120`
- **Severity**: CRITICAL
- **Description**: `get_active_orders()` catches `ClientError`/`ServerError` and returns `[]`. Every caller interprets `[]` as "no active orders," with no way to distinguish API blip from genuinely empty order book. `guardian_check` `has_oco` evaluates to `False` → unnecessary OCO placement or emergency close.
- **Impact**: API degradation triggers false "no protection" detection → emergency closes perfectly good positions or places duplicate OCOs.
- **Recommendation**: Return `None` or raise `ExchangeUnavailableError`. Callers must skip the pulse rather than act on fabricated data.

### [D8] `_calculate_target_qty` Uses Unguarded Ticker Price for Benchmark
- **File**: `src/agent/order_executor.py:893`
- **Severity**: CRITICAL
- **Description**: When `manual_balance_usdt` is `None` (production default), `_calculate_target_qty` calls `get_ticker_price(benchmark_symbol)` with no guard for `0.0` return. If ticker fails, `total_equity_usdt = 0`, `max_loss_usdt = 0`, `target_qty = 0` → floored to `min_order_qty`. Entire risk guardrail is absent.
- **Impact**: API blip on benchmark ticker silently destroys position sizing. Instead of `risk_per_trade * account_equity / stop_distance`, the system places a minimum-size order with no risk calculation.
- **Recommendation**: Add `if not current_price or current_price <= 0:` guard, abort entry placement and log failure.

### [D8] Guardian Protection Entirely Skipped When `get_symbol_position` Raises
- **File**: `src/agent/order_executor.py:164` → `run_sniper.py:578-580`
- **Severity**: CRITICAL
- **Description**: `guardian_check` calls `get_symbol_position` at entry. If it raises (any `ClientError`, `ServerError`, or network exception), the exception propagates to `_guardian_check` which returns `None`. Zero protection for that symbol for that pulse. No stale-state timeout, no alert.
- **Impact**: During sustained exchange outage, guardian is completely blind. Position runs without SL/TP for entire outage. Price can move against position with no circuit breaker.
- **Recommendation**: Wrap `get_symbol_position` in its own try/except. Add a consecutive-failure counter; escalate to alert after N failures.

---

## HIGH Findings

### [D2] Stale trade_state After Cancel Failure — Data/Exchange Mismatch
- **File**: `src/agent/order_executor.py:481-483`
- **Severity**: HIGH
- **Description**: When `cancel_all_symbol_orders` fails in `_optimize_same_direction`, the method returns a state update with computed TP/SL while old orders remain on exchange at original prices. In-memory `trade_state` says `tp=105, sl=92`; exchange has `tp=100, sl=90`.
- **Impact**: Logs/dashboards show incorrect OCO levels. If future code reads `trade_state` prices for decisions (instead of exchange orders), it acts on wrong data.
- **Recommendation**: Do not return state update when cancel fails. Return `(True, None)` — existing orders are still intact.

### [D2] Unnecessary Cancel-and-Replace When Protection Already Optimal
- **File**: `src/agent/order_executor.py:479-481`
- **Severity**: HIGH
- **Description**: `_optimize_same_direction` always cancels all orders and re-places OCO, even when `best_tp == existing_tp` and `best_sl == existing_sl`. The cancel-create gap leaves position naked. If re-place fails, previously well-protected position is now exposed.
- **Impact**: Transient API failure during unnecessary OCO re-placement triggers emergency close that could have been avoided.
- **Recommendation**: Before cancelling, compare exchange TP/SL against computed best. If identical, skip cancel-replace and return `(True, None)`.

### [D1] `_try_partial_tp`: Emergency Fallback Uses Partial Close, Same Naked-Position Leak
- **File**: `src/agent/order_executor.py:787,789`
- **Severity**: HIGH
- **Description**: OCO re-place failure in partial TP triggers `execute_partial_market_close` (not full close) with computed qty. If that also fails, returns `(True, None)` — same silent naked-position pattern as CRITICAL D1 findings.
- **Impact**: Partial TP executed, no OCO, remaining position naked. If `sl_distance_atr=0`, downstream trailing is skipped and naked position survives into next pulse.
- **Recommendation**: Use `execute_market_close(symbol)` instead of `execute_partial_market_close`. Return `(False, None)` on double-failure.

### [D1] Case 4 Qty Re-Align: Missing Position Re-Verify Between Cancel and OCO Placement
- **File**: `src/agent/order_executor.py:343-349`
- **Severity**: HIGH
- **Description**: Qty re-alignment cancels orders then places OCO using pre-pulse `net_qty` without re-fetching position. Inconsistent with `_optimize_same_direction` and `_migrate_dynamic_sl` which do re-verify.
- **Impact**: External fill during cancel window causes mis-sized OCO (over-selling or partial protection).
- **Recommendation**: Add position re-fetch between cancel and place, matching pattern in `_optimize_same_direction`.

### [D1] `_try_partial_tp`: Widest Naked Window — No Re-Verify Between Cancel and OCO Place
- **File**: `src/agent/order_executor.py:738-775`
- **Severity**: HIGH
- **Description**: Partial TP sequence: cancel all → market order → arithmetic qty → place OCO. Includes a market-order API round-trip with position naked throughout. Multi-level TP compounds the window. Crash between lines 744-775 leaves position naked permanently.
- **Impact**: Naked window during partial TP. Crash scenario: position naked on exchange with TP partially executed, OCO never placed, restart may not detect.
- **Recommendation**: Execute partial TP BEFORE cancelling existing OCO, or re-verify position after cancel and before OCO placement. Add crash-recovery check in guardian restart path.

### [D1] `_optimize_same_direction`: Cancel Failure Returns Stale Prices While Orders Remain Active
- **File**: `src/agent/order_executor.py:481-483`
- **Severity**: HIGH (duplicate of D2 finding, cross-confirmed)
- **Description**: See D2 finding above. Cross-confirmed by D1 audit.
- **Impact**: Same as D2 finding.
- **Recommendation**: Same as D2 finding.

### [D3] Externally Cancelled Entry Order Not Detected — Trade State Stuck Until Timeout
- **File**: `src/agent/order_executor.py:213-235`
- **Severity**: HIGH
- **Description**: Case 1 tracks pending entries purely via trade_state metadata. Never cross-checks whether the entry order is still alive on exchange. If cancelled externally, guardian waits until `projected_waiting_hours` timeout.
- **Impact**: During the stuck period, `has_active` blocks new sessions. Bot cannot enter new trade for that symbol.
- **Recommendation**: In Case 1, validate `entry_order_id` is in `active_orders`. If not, clear trade state immediately.

### [D3] `entry_filled_at` Set to `now()` Instead of Actual Fill Time
- **File**: `src/agent/order_executor.py:310-311`
- **Severity**: HIGH
- **Description**: Guardian sets `entry_filled_at` to OCO placement time, not actual fill time. Entry may have filled minutes/hours earlier.
- **Impact**: Data integrity issue. Downstream analytics, audit scripts, or future time-based trailing logic will get systematically incorrect timestamps.
- **Recommendation**: Retrieve actual fill time from filled entry order's exchange data.

### [D3] Restart Reconstruction Missing Critical Fields
- **File**: `src/agent/order_executor.py:187-194`
- **Severity**: HIGH
- **Description**: Reconstruction only populates `direction`, `tp_price`, `sl_price`. Missing: `entry_filled_at`, `projected_holding_hours`, `entry_atr`, `projected_waiting_hours`. `entry_filled_at` will be set to `now()` on first OCO placement pulse, compounding the timestamp issue above.
- **Impact**: `projected_holding_hours` permanently lost → sessions appear with 0 holding hours in dashboards. Reconstructed `entry_filled_at` is wrong.
- **Recommendation**: Query position's average entry or recent fills to backfill `entry_filled_at`.

### [D6] AI Session Overwrites Manual OCO When Direction Matches
- **File**: `src/agent/order_executor.py:127-131`
- **Severity**: HIGH
- **Description**: When user holds manual position in SAME direction as AI opinion with no trade_state, session fires and `_optimize_same_direction` cancels ALL active orders — including user-placed OCO — replacing with AI's TP/SL.
- **Impact**: User's SL/TP silently replaced by AI-generated levels. Tighter stop or different profit target lost without warning.
- **Recommendation**: Add `bot_managed` flag to trade_state. Only optimize when position was originally opened by bot.

### [D6] Cooldown Reset on Manual Close Enables Immediate Re-Entry ↓ LOW (downgraded)
- **File**: `run_sniper.py:561-564`
- **Severity**: ~~HIGH~~ → LOW
- **Description**: Guardian trade_state clear resets cooldown regardless of who closed the position. Manual close accelerates re-entry by 25–60 min but does not change the fundamental outcome — bot will re-enter when cooldown naturally expires anyway.
- **Impact**: Minor. User who disagrees with bot direction should disable `--trade`, not rely on cooldown timing to prevent re-entry.
- **Recommendation**: Low priority. A `bot_managed` flag could be considered as an enhancement to prevent AI from touching manually-managed positions.

### ~~[D5] Cooldown Reset Enables Same-Pulse Re-Trigger After Entry Expiry~~ → REMOVED (Post-Review)
- **Original File**: `run_sniper.py:561-564`, `run_sniper.py:168-171`
- **Verdict**: **Not a bug.** Trace was incorrect — `set_triggered("ACTIVE_POSITION")` at `run_sniper.py:403` refreshes cooldown every pulse while `has_active=True` blocks dispatch. Between entry placement and timeout, every pulse where trigger fires but `has_active` blocks calls `set_triggered(result, "ACTIVE_POSITION")`, which sets `last_trigger_time = now()` and reactivates cooldown. The cooldown never expires while pending. The reset at trade_state clear is correct: bot is flat, cooldown should release.

### [D7] Cooldown State Loss on Restart Enables Immediate Re-Trigger
- **File**: `src/sniper/trigger.py:219-222`, `run_sniper.py:267`
- **Severity**: HIGH
- **Description**: Cooldown state is in-memory only. On restart, all cooldown resets to initial. Combined with empty `trade_states` (has_active=False), first pulse can fire immediately — bypassing 30-90 min cooldown.
- **Impact**: Rapid daemon restart cycles → back-to-back sessions with no cooldown gap → overtrading, duplicate entries.
- **Recommendation**: Persist `last_trigger_time` to disk and restore on startup. Or enforce minimum startup delay before first trigger evaluation.

### [D8] Position Left Naked When Cancel Succeeds But OCO Re-Place Fails
- **File**: `src/agent/order_executor.py:313-319, 343-364, 501-514, 673-683`
- **Severity**: HIGH
- **Description**: In four code paths, cancel-then-place pattern: if cancel succeeds but OCO placement fails, position has all orders cancelled and no new protection. System attempts emergency close, but if that also fails (see CRITICAL D1), position stays naked.
- **Impact**: Transient API error during OCO placement leaves position unprotected for one full pulse interval.
- **Recommendation**: Retry `place_oco_order` with exponential backoff (3 attempts) before falling through to emergency close.

---

## MEDIUM Findings

| # | Dimension | Finding | File:Line |
|---|-----------|---------|-----------|
| 1 | D2 | Stale LIMIT orders mistaken for TP targets when 3+ active orders | `order_executor.py:449-452` |
| 2 | D2 | Position vanish after cancel leaves stale trade_state for one pulse | `order_executor.py:489-491` |
| 3 | D3 | Case 2 direction mismatch creates persistent naked position (infinite loop) | `order_executor.py:237-250` |
| 4 | D3 | `projected_waiting_hours` defaults to 24h — brittle | `order_executor.py:218` |
| 5 | D4 | `_migrate_dynamic_sl` uses `round()` instead of directional safety rounding; dead if/else branches | `order_executor.py:829-832` |
| 6 | D4 | `find_level_and_sync_sl` returns valid level on cancel failure, masking error | `order_executor.py:665-667` |
| 7 | D1 | guardian_check Case 3: Places OCO without cancelling existing exit orders | `order_executor.py:284-302` |
| 8 | D1 | has_oco check only validates SL order existence, semantically fragile | `order_executor.py:204-207` |
| 9 | D5 | Emergency close via sentinel does not clean `_symbol_level` and `_symbol_last_qty` | `run_sniper.py:474-476` |
| 10 | D5 | Cooldown treatment inconsistent between two emergency-close code paths | `run_sniper.py:474-476` vs `561-564` |
| 11 | D5 | Duplicate `get_active_orders` API call in guardian heartbeat snapshot | `run_sniper.py:572` + `order_executor.py:166` |
| 12 | D5 | `last_trigger_score` not reset during cooldown reset — inconsistent state | `run_sniper.py:562-563` |
| 13 | D6 | Per-pulse no-op cycle for manual positions without trade state | `run_sniper.py:553-564` |
| 14 | D6 | Level memory reset on any qty delta (including dust/rounding) loses partial TP progress | `run_sniper.py:528-530` |
| 15 | D7 | Level recovery delayed by one pulse after trade state reconstruction | `run_sniper.py:535-541` |
| 16 | D7 | OBSERVE_ONLY mode cannot clean up orphaned entry orders | `run_sniper.py:271-278` |

---

## LOW Findings

| # | Dimension | Finding | File:Line |
|---|-----------|---------|-----------|
| 1 | D2 | `cancel_all_symbol_orders` ignores partial cancellation on server error | `margin_client.py:179-181` |
| 2 | D2 | No escalation for persistent ticker failure in SL breach check | `order_executor.py:267-269` |
| 3 | D4 | Inconsistent SL-change tolerance between `_migrate_dynamic_sl` and `find_level_and_sync_sl` | `order_executor.py:834` vs `662` |
| 4 | D4 | Remaining qty computed arithmetically after partial close without exchange re-verify | `order_executor.py:759` |
| 5 | D4 | Double cancel+replace OCO cycle when trailing follows same-pulse partial TP | `order_executor.py:738,843` |
| 6 | D6 | has_active blind to exchange-only positions on restart | `run_sniper.py:267` |
| 7 | D8 | Emergency close has no backoff or max-retry guard; retries indefinitely | `order_executor.py:260-262,279-281` |

---

## Risk Matrix

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Emergency close failure → naked position (D1 CRITICAL) | L=2 (API must fail twice) | I=5 (unbounded downside) | Return `position_intact=False` |
| Pivot permanently blocked (D2 CRITICAL) | L=4 (every direction flip) | I=4 (naked or stuck) | Implement Case A-1 force-close |
| Market close partial fill → residual (D2 CRITICAL) | L=2 (low liquidity) | I=5 (unprotected residual) | Post-close position re-verify |
| Direction flip dead loop (D6 CRITICAL) | L=2 (manual intervention) | I=5 (permanently naked) | Emergency close on direction flip |
| Restart naked position (D7 CRITICAL) | L=3 (every restart with pending entry) | I=5 (unlimited downside) | Fall through to Case 3 |
| Orphaned entry after restart (D7 CRITICAL) | L=3 (every restart with pending entry) | I=4 (double entry risk) | Startup reconciliation |
| Silent API failure → false actions (D8 CRITICAL) | L=3 (intermittent API issues) | I=4 (false emergency closes) | Return None/raise, skip pulse |
| Cooldown reset on manual close (D6 LOW) | L=2 (manual positions) | I=1 (re-entry 25-60 min sooner) | User disables --trade if disagreeing |
| Manual OCO overwritten (D6 HIGH) | L=2 (manual positions) | I=3 (user intent lost) | `bot_managed` flag |
| Restart cooldown loss (D7 HIGH) | L=2 (daemon restarts) | I=3 (rapid re-trigger) | Persist trigger state to disk |

---

## New Change Impact Assessment

### `has_active` Revert (v26.7.05)
**Status**: ✅ Correct, lower risk than previous exchange-based check.
- **D5 finding**: Manual positions now correctly allowed through (sync_with_opinion handles).
- **D6 finding**: But AI can overwrite manual OCO in same-direction scenario — needs `bot_managed` flag.
- **D7 finding**: On restart, trade_states empty → has_active=False for everything → no startup gap protection.

### Cooldown Auto-Reset (v26.7.05)
**Status**: ✅ Correct and safe. Post-review verification confirms no tight loop.
- ~~D5 HIGH~~: Invalid — cooldown never expires while `has_active` blocks (refreshed every pulse by `set_triggered`). Reset only takes effect after trade_state IS cleared, which is correct behavior.
- **D6 HIGH**: Manual close triggers immediate re-entry against user intent.
- **Emergency close path isolation**: ✅ Correctly preserves cooldown on `_EMERGENCY_CLOSED_SENTINEL`.

### Recommendations for Immediate Follow-up
1. Fix D1 CRITICAL: emergency close failure return values (2-line fix, maximum safety gain)
2. Fix D7 CRITICAL: restart naked position detection (1-line fall-through)
3. Fix D3 HIGH: entry order liveness check in Case 1 (1-line validation)
4. Fix D5 HIGH: min-gap on entry expiry cooldown reset (2-line guard)

---

## Appendix: Confirmed Correct Behaviors

- **SL slippage buffer direction**: All 6 call sites correctly implement LONG `sl - buffer`, SHORT `sl + buffer` ✅
- **Ticker=0 SL breach guard**: `guardian_check:267` correctly validates `current_price > 0` before breach check ✅
- **Cooldown auto-reset**: Correctly implemented at daemon layer, not executor layer ✅
- **Emergency close cooldown preservation**: `_EMERGENCY_CLOSED_SENTINEL` path correctly preserves cooldown ✅
- **Partial TP sequential firing**: `break` at first unmet threshold, multi-level same-pulse works correctly ✅
- **Trailing SL directional safety**: `max()` for LONG, `min()` for SHORT — SL only moves favorably ✅
