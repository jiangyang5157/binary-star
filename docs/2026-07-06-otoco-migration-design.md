# OTOCO Migration Design

**Date:** 2026-07-06
**Status:** Designed

## Motivation

Current two-step entry flow has a naked-position window:

```
limit entry → [0-2 min gap, no TP/SL] → Guardian pulse → place OCO
```

Replace with atomic OTOCO (One-Triggers-One-Cancels-Other): entry limit + nested
TP/SL in a single Binance API call. Entry fill automatically activates OCO
protection — zero naked-position window.

## Trade State Changes

| Before | After | Reason |
|--------|-------|--------|
| `entry_order_id` (int) | removed | OTOCO has no single entry order ID |
| `entry_placed_at` (datetime) | `otoco_placed_at` (datetime) | rename for clarity |
| `projected_waiting_hours` | unchanged | timeout threshold |
| `direction`, `tp_price`, `sl_price`, `entry_filled_at`, `projected_holding_hours` | unchanged | same semantics |

No `otoco_list_id` needed — `cancel_all_symbol_orders` handles timeout
cancellation, consistent with Guardian Cases 2/3/4.

## Module 1: Fix `place_otoco_order`

**File:** `src/infrastructure/binance/margin_client.py`

Three fixes:

1. `send_request` → `sign_request` (missing timestamp + signature)
2. Add `pendingQuantity` to params dict (required by API, value = `qty`)
3. Return `Optional[int]` (orderListId) instead of `bool`

```python
# Before
resp = self.client.send_request("POST", "/sapi/v1/margin/order/otoco", params)
return True

# After
resp = self.client.sign_request("POST", "/sapi/v1/margin/order/otoco", params)
return resp.get("orderListId")
```

## Module 2: Entry Flow

**File:** `src/agent/order_executor.py` — `sync_with_opinion()`

Scenario C (FLAT): replace `_place_entry_order()` with new `_place_otoco_entry()`.

```python
# Before (FLAT branch)
return self._place_entry_order(symbol, opinion_direction, entry_price, sl_price)

# After (FLAT branch)
return self._place_otoco_entry(symbol, opinion_direction, entry_price, tp_price, sl_price)
```

New helper `_place_otoco_entry()`:
- Calls `place_otoco_order()`
- Calculates buffered SL the same way `_place_entry_order` does
- Returns `orderListId` (int) or `None` on failure

**File:** `run_sniper.py` — `_attempt_trade_execution()`

trade_state initialization:

```python
# Before
self.trade_states[symbol] = {
    "direction": direction,
    "entry_price": float(entry),
    "tp_price": float(tp),
    "sl_price": float(sl),
    "entry_order_id": result,
    "entry_placed_at": datetime.now(timezone.utc),
    ...
}

# After
self.trade_states[symbol] = {
    "direction": direction,
    "entry_price": float(entry),
    "tp_price": float(tp),
    "sl_price": float(sl),
    "otoco_placed_at": datetime.now(timezone.utc),
    ...
}
```

Scenarios A (PIVOT) and B (SAME DIRECTION) unchanged.

## Module 3: Guardian Adaptation

**File:** `src/agent/order_executor.py` — `guardian_check()`

### Case 1 — Pending Entry (branch A)

```python
# Before
entry_order_id = trade_state.get("entry_order_id")
if entry_order_id:
    placed_at = trade_state.get("entry_placed_at")
    ...
    if elapsed > timeout:
        self.client.cancel_order(symbol, entry_order_id)
        return {}, None

# After
otoco_placed_at = trade_state.get("otoco_placed_at")
if otoco_placed_at:
    elapsed = (datetime.now(timezone.utc) - otoco_placed_at).total_seconds() / 3600
    if elapsed > timeout:
        self.client.cancel_all_symbol_orders(symbol)
        return {}, None
```

`cancel_order(single)` → `cancel_all_symbol_orders` — consistent with the rest
of Guardian and safer for OTOCO (cancels entire order list, no orphaned legs).

### Case 1 — Position Closed (branch B)

Unchanged — still gated by `entry_filled_at` which is not renamed.

### Case 2 — Orientation Conflict

Unchanged.

### Case 3 — Naked Position (safety net)

Kept as-is. The two `entry_order_id` lines become harmless dead code:

```python
entry_order_id = trade_state.get("entry_order_id")  # → None
if entry_order_id:                                    # → skipped
    self.client.cancel_order(...)
```

OTOCO normal path never reaches Case 3 (position opens with OCO → goes to Case 4).

### Case 4 — Protected Position

Unchanged. Exit ladder, dynamic SL migration, OCO re-alignment all work
identically — the exchange state (position + OCO orders) looks the same
whether the position was opened via OTOCO or two-step.

## Module 4: Restart Recovery

Unchanged. Guardian reconstructs `trade_state` from exchange orders:

```python
if has_position and has_sl:
    reconstructed = {"direction": ..., "tp_price": ..., "sl_price": ...}
```

OTOCO-created positions have the same exchange footprint as two-step positions
(position + OCO orders), so reconstruction works without modification.

## What Does NOT Change

- Exit ladder (3-level partial TP)
- Dynamic trailing stop (`_apply_sl_lock`)
- OCO qty re-alignment
- `_optimize_same_direction` (same-direction optimization)
- Pivot blocking (Scenario A)
- All emergency close paths
- Restart recovery
- `find_level_and_sync_sl`
- `_calculate_target_qty` / risk checks / position sizing
- `guardian_check` Cases 2, 3 (safety net), 4

## Risk Assessment

| Risk | Mitigation |
|------|-----------|
| OTOCO API call fails | Returns None; no trade_state created; same as limit entry failure today |
| Entry doesn't fill, times out | `cancel_all_symbol_orders` clears entire OTOCO list |
| Need to rollback | Restore FLAT branch → `_place_entry_order`; all other changes are compatible with two-step flow |
| `place_otoco_order` previously broken | Fix verified: `sign_request` + `pendingQuantity` + `sideEffectType` (already added) |

## Files Changed

| File | Scope |
|------|-------|
| `src/infrastructure/binance/margin_client.py` | Fix `place_otoco_order`: sign_request, pendingQuantity, return listId |
| `src/agent/order_executor.py` | New `_place_otoco_entry()`; FLAT branch switch; Guardian Case 1 rename; Case 3 dead code |
| `run_sniper.py` | trade_state field rename in `_attempt_trade_execution` |
