# Audit Checklists — Detailed Per-Dimension

## D1: OCO Lifecycle — Synthetic OCO

### 1.1 Cancel-Place Gap Analysis
For each site that cancels then re-places OCO, answer:
- [ ] What is the sequence of API calls? (cancel → verify → place)
- [ ] What is the estimated wall-clock gap? (network RTT × N calls)
- [ ] During the gap, is the position naked? (yes if cancel succeeded and place hasn't happened yet)
- [ ] What happens if price moves adversely during the gap? (SL would have triggered but order was cancelled)
- [ ] Is there a re-verify step between cancel and place? (checks position still exists)

Sites to audit:
1. `_optimize_same_direction()` — `order_executor.py:~438-520`
2. `_try_partial_tp()` — `order_executor.py:~693-804`
3. `_migrate_dynamic_sl()` — `order_executor.py:~805-935`
4. `guardian_check()` Case 3 OCO placement — `order_executor.py:~255-320`
5. `guardian_check()` Case 4 qty re-align — `order_executor.py:~324-371`
6. `find_level_and_sync_sl()` — `order_executor.py:~575-691`

### 1.2 Emergency Close Completeness
For every `place_oco_order` call site, verify:
- [ ] On `place_oco_order` returning False, is `execute_market_close` called?
- [ ] On `execute_market_close` returning False, is the error handled correctly?
  - Does the caller return sentinel `_EMERGENCY_CLOSED_SENTINEL`?
  - Does the caller keep trade_state for retry?
  - Does the caller clear trade_state and leave position naked?
- [ ] Is there any path where `place_oco_order` fails but `execute_market_close` is NOT called?

### 1.3 OCO Qty Re-alignment (Case 4)
- [ ] Trace `guardian_check` Case 4 when qty mismatch detected.
- [ ] Does it correctly re-read TP/SL from active orders?
- [ ] What if only one leg remains (SL filled, TP still open or vice versa)?
- [ ] What if NO active orders remain but position exists?
- [ ] After re-align, is the new OCO qty verified to match position?

### 1.4 SL Slippage Buffer
- [ ] LONG direction: `buffered_sl = sl - buffer` at every SELL-exit call site
- [ ] SHORT direction: `buffered_sl = sl + buffer` at every BUY-exit call site
- [ ] Check `_optimize_same_direction` line 501
- [ ] Check `guardian_check` Case 3 line 296
- [ ] Check `guardian_check` Case 4 line 348
- [ ] Check `_try_partial_tp`
- [ ] Check `_migrate_dynamic_sl`
- [ ] Check `find_level_and_sync_sl`

## D2: Pivot Logic

**Current behavior**: Pivots are blocked. `sync_with_opinion` Scenario A returns `None` when `current_direction != opinion_direction`.

### 2.1 Pivot Block Correctness
- [ ] Verify Scenario A (line 114-124): returns None, logs "pivot blocked"
- [ ] Guardian continues protecting existing position. Is the SL still valid for the current price?
- [ ] Risk: if AI correctly calls a reversal, bot rides position into SL. Acceptable?
- [ ] Trade-off: blocking pivots prevents interference with manual positions and restart-gap reconstruction.

### 2.2 Scenario B: Same-Direction Optimization
- [ ] `current_direction == opinion_direction` → calls `_optimize_same_direction()`
- [ ] TP selection: greedy (widest) — correct for maximizing reward
- [ ] SL selection: tightest (most protective) — correct for risk minimization
- [ ] Cancel-all → verify position → place new OCO sequence is correct
- [ ] OCO placement failure → emergency market close
- [ ] `_EMERGENCY_CLOSED_SENTINEL` (-1) correctly signals daemon to clear trade_state

### 2.3 Scenario C: FLAT → New Entry
- [ ] Position is flat → clears stale orders → places LIMIT entry
- [ ] `cancel_all_symbol_orders` failure → returns None (safe abort)
- [ ] Entry qty from `_calculate_target_qty` — verify risk-per-trade and precision

### 2.4 Safety Gates
- [ ] NEUTRAL opinions → return None immediately (line 71-73)
- [ ] Symbol whitelist: unconfigured symbols rejected (line 55-60)
- [ ] Config validation: missing/corrupt config → abort (line 86-94)

## D3: Guardian Pulse Cycle

### 3.1 Entry Lifecycle
- [ ] Entry placed → tracked via `entry_order_id` + `entry_placed_at`
- [ ] Entry pending → guardian skips (returns trade_state)
- [ ] Entry expired → cancel order → clear state
- [ ] Entry filled (position exists) but no OCO → Case 3
- [ ] `projected_waiting_hours` missing → defaults to 24h. OK?
- [ ] What if entry order is cancelled externally (not by guardian)?

### 3.2 Position Without Protection (Case 3)
- [ ] Missing TP/SL → emergency close
- [ ] SL breached → emergency close
- [ ] Ticker price returns 0 → SL appears breached → false emergency close?
- [ ] Stale entry order cleaned before placing OCO
- [ ] OCO placement fails → emergency close
- [ ] `entry_filled_at` set to now() even if fill was hours ago

### 3.3 Direction Sanity (Case 2)
- [ ] Intent vs reality mismatch detected
- [ ] Logging throttled (good)
- [ ] Orders cancelled via `cancel_all_symbol_orders()` — removes wrong-side OCO
- [ ] But trade_state NOT cleared — direction mismatch persists, Case 2 loops each pulse
- [ ] Should Case 2 clear trade_state so Case 3 can emergency-close on the next pulse?

### 3.4 Restart Reconstruction
- [ ] trade_state reconstructed from exchange OCO
- [ ] direction derived from net_qty sign
- [ ] TP from LIMIT order price
- [ ] SL from STOP_LOSS_LIMIT stop_price
- [ ] What fields are MISSING from reconstruction? (`entry_filled_at`, `projected_holding_hours`, `entry_atr`, `entry_order_id`)
- [ ] Do missing fields cause issues in downstream logic?

## D4: Partial TP + Trailing Stop

### 4.1 Level Loop
- [ ] Sequential firing: `break` at first unmet threshold
- [ ] Multi-level same-pulse: loop continues past `break`?
- [ ] Position re-verified after each partial close
- [ ] Min qty check before placing OCO for remaining?
- [ ] What if remaining qty < min_order_qty? Should market-close the rest?

### 4.2 SL Migration
- [ ] LONG: `max(current_sl, price - N*ATR)` — SL only moves up
- [ ] SHORT: `min(current_sl, price + N*ATR)` — SL only moves down
- [ ] Rounding direction: toward safety?
- [ ] No migration when `sl_distance_atr == 0` (correct)
- [ ] SL source from active orders, not trade_state (source of truth)

### 4.3 Level Memory
- [ ] `_symbol_level` in daemon memory (not persisted) — OK since restart rebuilds
- [ ] Qty change detection resets level
- [ ] `find_level_and_sync_sl` side effects: API mutations during "find"
- [ ] Level initialization on first pulse after trade entry

### 4.4 Trailing Distance Selection
- [ ] `active_idx = new_level - 1` — maps level to config index
- [ ] L1 fired → active_idx=0 → distance=0.0 → no trailing (correct)
- [ ] L2 fired → active_idx=1 → distance=1.0 → trailing active
- [ ] L3 fired → active_idx=2 → distance=0.75 → tighter trailing
- [ ] All levels exhausted → no trailing

## D5: Daemon Integration

### 5.1 Trade State Flow
- [ ] Created: `_attempt_trade_execution` after successful entry
- [ ] Updated: `_optimize_same_direction` return merged
- [ ] Updated: `_guardian_check` return replaces
- [ ] Cleared: executor returns `{}`
- [ ] Cleared: `_EMERGENCY_CLOSED_SENTINEL`
- [ ] State consistency: is there any path where daemon and executor disagree?

### 5.2 Guardian-AI Interaction
- [ ] Guardian runs before AI session in pulse loop
- [ ] `has_active` is trade_state-based: `bool(self.trade_states.get(sym, {}).get("direction"))`
- [ ] Manual positions (no trade_state) allowed through — `sync_with_opinion` + cooldown regulate
- [ ] If guardian clears trade_state (entry expired / position closed), AI CAN fire in same pulse
- [ ] Guardian trade_state clear now **also resets cooldown** (`last_trigger_time = None`), amplifying same-pulse re-entry risk
- [ ] Emergency close (`_EMERGENCY_CLOSED_SENTINEL`) does NOT reset cooldown — cooling-off preserved
- [ ] Could this cause overtrading? (position closed → immediate re-entry with no cooldown barrier)

### 5.3 Level/Qty Tracking
- [ ] `_symbol_level` reset on qty change
- [ ] `_symbol_last_qty` updated every pulse
- [ ] Both cleared when trade_state cleared
- [ ] Qty comparison tolerance: 1e-8 (appropriate?)

## D6: Manual Intervention

### 6.1 Position Size Changes
- [ ] Qty increase → level reset → OCO re-aligned
- [ ] Qty decrease → same flow
- [ ] TP/SL prices preserved from active orders
- [ ] Full close → guardian clears state

### 6.2 Manual Direction Flip
- [ ] Close LONG + open SHORT externally
- [ ] Direction sanity check detects mismatch
- [ ] But takes NO action — position runs with wrong/no protection
- [ ] What should happen? (emergency close? wait for AI?)

### 6.3 avg_entry_price Effects
- [ ] Manual add at different price: avg_entry recalculated
- [ ] `get_avg_entry_price` has cache: only recalculates when qty changes
- [ ] Cache keyed by (symbol, net_qty) — what if same qty but different entry? (Impossible — same qty means no trade happened.)

## D7: Restart & Recovery

### 7.1 Trade State Reconstruction
- [ ] Empty trade_state + position + OCO → reconstructs
- [ ] Empty trade_state + position + NO OCO → early return (naked!)
- [ ] Empty trade_state + no position + entry order → early return (untracked!)

### 7.2 Level Recovery
- [ ] Level is None → `find_level_and_sync_sl` called
- [ ] SL synced to match found level's trailing distance
- [ ] No partial TP execution during sync (correct — only syncs, doesn't close)

### 7.3 Gap Analysis
- [ ] Time between daemon stop and restart: position status?
- [ ] If OCO existed before stop: it's still on exchange (OCO persists)
- [ ] If OCO didn't exist: position was already naked
- [ ] If entry was pending: order still on exchange

## D8: Exchange API Failure Resilience

### 8.1 Read Failures
- [ ] `get_symbol_position` fails → exception → pulse skipped
- [ ] `get_active_orders` fails → empty list returned (silent)
- [ ] `get_ticker_price` fails → returns 0.0 → false SL breach?

### 8.2 Write Failures
- [ ] `cancel_all_symbol_orders` fails → returns False
- [ ] `place_oco_order` fails → returns False → triggers emergency close
- [ ] `execute_market_close` fails → returns False → keeps trade_state for retry
- [ ] `place_limit_order` fails → returns None → no trade_state created

### 8.3 Specific Bug: Ticker=0 Triggers Emergency Close
- [ ] `guardian_check` line 269-287: if ticker returns 0, SL appears breached
- [ ] LONG: `0 <= sl` → True (for any positive SL) → emergency close!
- [ ] SHORT: `0 >= sl` → False (for any positive SL) → no trigger
- [ ] Mitigation: check `current_price > 0` before SL breach check
