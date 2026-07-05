# OTOCO Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace two-step entry (limit → Guardian OCO) with atomic OTOCO (entry + nested TP/SL in one API call), eliminating the 0-2 minute naked-position window.

**Architecture:** Fix the broken `place_otoco_order`, add `_place_otoco_entry` helper, switch the FLAT branch in `sync_with_opinion` to use OTOCO, adapt Guardian Case 1 timeout logic, keep Cases 2/3/4 as-is. Trade state renames `entry_order_id` → removed, `entry_placed_at` → `otoco_placed_at`.

**Tech Stack:** Python, python-binance SDK, cross-margin trading

## Global Constraints

- Spec: `docs/2026-07-06-otoco-migration-design.md`
- Rollback-safe: restoring FLAT branch → `_place_entry_order` reverts to two-step flow
- Guardian Cases 2/3/4 unchanged
- Exit ladder, dynamic SL, restart recovery unchanged
- Dev branch: `develop` (current)

---

### Task 1: Fix `place_otoco_order` in margin_client.py

**Files:**
- Modify: `src/infrastructure/binance/margin_client.py:510-515`

**Interfaces:**
- Consumes: none (pre-existing function, no callers)
- Produces: `place_otoco_order(...) -> Optional[int]` — returns `orderListId` (int) on success, `None` on failure

- [ ] **Step 1: Add `pendingQuantity` to params dict**

In `src/infrastructure/binance/margin_client.py`, insert `"pendingQuantity"` into the params dict at line 486, after `"workingQuantity"`:

```python
params = {
    "symbol": symbol,
    "workingType": "LIMIT",
    "workingSide": side,
    "workingPrice": self._round_price(entry_price, p_price, side),
    "workingQuantity": round(qty, p_qty),
    "pendingQuantity": round(qty, p_qty),      # ← add this line
    "workingTimeInForce": "GTC",
    "pendingSide": pending_side,
    "pendingAboveTimeInForce": "GTC",
    "sideEffectType": "MARGIN_BUY",
}
```

- [ ] **Step 2: Change `send_request` → `sign_request` and return `orderListId`**

Replace lines 510-512:

```python
# Remove:
resp = self.client.send_request("POST", "/sapi/v1/margin/order/otoco", params)
logger.info(f"OTOCO placed | symbol={symbol} | order_list_id={resp.get('orderListId')}")
return True

# Replace with:
resp = self.client.sign_request("POST", "/sapi/v1/margin/order/otoco", params)
order_list_id = resp.get("orderListId")
logger.info(f"OTOCO placed | symbol={symbol} | order_list_id={order_list_id}")
return order_list_id
```

- [ ] **Step 3: Update return type in exception handler**

Replace line 515 `return False` with `return None`:

```python
except Exception as e:
    logger.error(f"OTOCO failed | symbol={symbol} | error={e}")
    return None
```

- [ ] **Step 4: Update return type annotation**

Change line 470:

```python
# Before:
def place_otoco_order(self, symbol: str, side: str, qty: float, entry_price: float, tp_price: float, sl_trigger_price: float, sl_limit_price: float) -> bool:

# After:
def place_otoco_order(self, symbol: str, side: str, qty: float, entry_price: float, tp_price: float, sl_trigger_price: float, sl_limit_price: float) -> Optional[int]:
```

- [ ] **Step 5: Verify syntax**

Run: `python3 -c "import ast; ast.parse(open('src/infrastructure/binance/margin_client.py').read()); print('OK')"`
Expected: `OK`

- [ ] **Step 6: Commit**

```bash
git add src/infrastructure/binance/margin_client.py
git commit -m "fix: place_otoco_order — sign_request, pendingQuantity, return listId

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 2: Add `_place_otoco_entry` and switch FLAT branch

**Files:**
- Modify: `src/agent/order_executor.py:103-112` (FLAT branch)
- Modify: `src/agent/order_executor.py:926-939` (add `_place_otoco_entry` after `_place_entry_order`)
- Modify: `run_sniper.py:475-486` (trade_state init)

**Interfaces:**
- Consumes: `self.client.place_otoco_order()` (from Task 1)
- Produces: `_place_otoco_entry(symbol, direction, entry_price, tp_price, sl_price) -> Optional[int]`

- [ ] **Step 1: Add `_place_otoco_entry` helper**

After `_place_entry_order` (line 939), add:

```python
    def _place_otoco_entry(self, symbol: str, direction: str, entry_price: float, tp_price: float, sl_price: float) -> Optional[int]:
        """Places an OTOCO order (entry + nested TP/SL). Returns orderListId for Guardian tracking."""
        dynamic_qty = self._calculate_target_qty(symbol, entry_price, sl_price)

        side = "BUY" if direction == "LONG" else "SELL"

        # Calculate buffered SL Limit (same as _place_entry_order direction logic)
        cfg = self._get_trade_config(symbol)
        buffer = cfg.get("sl_slippage_buffer", 0.0)
        # LONG SL (Sell): Limit < Trigger | SHORT SL (Buy): Limit > Trigger
        buffered_sl = sl_price + (buffer if direction == "SHORT" else -buffer)

        logger.info(f"[{symbol}] deploying OTOCO | dir={direction} | entry={entry_price} | tp={tp_price} | sl={sl_price} | qty={dynamic_qty}")

        order_list_id = self.client.place_otoco_order(
            symbol=symbol,
            side=side,
            qty=dynamic_qty,
            entry_price=entry_price,
            tp_price=tp_price,
            sl_trigger_price=sl_price,
            sl_limit_price=buffered_sl,
        )
        return order_list_id
```

- [ ] **Step 2: Verify syntax**

Run: `python3 -c "import ast; ast.parse(open('src/agent/order_executor.py').read()); print('OK')"`
Expected: `OK`

- [ ] **Step 3: Switch FLAT branch to use OTOCO**

In `sync_with_opinion`, line 112, replace:

```python
# Before:
logger.info(f"[{symbol}] placing LIMIT entry | dir={opinion_direction}")
return self._place_entry_order(symbol, opinion_direction, entry_price, sl_price)

# After:
logger.info(f"[{symbol}] placing OTOCO entry | dir={opinion_direction}")
return self._place_otoco_entry(symbol, opinion_direction, entry_price, tp_price, sl_price)
```

- [ ] **Step 4: Verify syntax**

Run: `python3 -c "import ast; ast.parse(open('src/agent/order_executor.py').read()); print('OK')"`
Expected: `OK`

- [ ] **Step 5: Update trade_state initialization in run_sniper.py**

In `_attempt_trade_execution`, lines 476-486, rename the fields:

```python
# Before:
self.trade_states[symbol] = {
    "direction": direction,
    "entry_price": float(entry),
    "tp_price": float(tp),
    "sl_price": float(sl),
    "entry_order_id": result,
    "entry_placed_at": datetime.now(timezone.utc),
    "projected_waiting_hours": float(projected_waiting),
    "projected_holding_hours": float(projected_holding),
}

# After:
self.trade_states[symbol] = {
    "direction": direction,
    "entry_price": float(entry),
    "tp_price": float(tp),
    "sl_price": float(sl),
    "otoco_placed_at": datetime.now(timezone.utc),
    "projected_waiting_hours": float(projected_waiting),
    "projected_holding_hours": float(projected_holding),
}
```

- [ ] **Step 6: Verify syntax**

Run: `python3 -c "import ast; ast.parse(open('run_sniper.py').read()); print('OK')"`
Expected: `OK`

- [ ] **Step 7: Commit**

```bash
git add src/agent/order_executor.py run_sniper.py
git commit -m "feat: switch FLAT entry to OTOCO, rename trade_state fields

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 3: Guardian Case 1 adaptation

**Files:**
- Modify: `src/agent/order_executor.py:210-233` (Case 1)

**Interfaces:**
- Consumes: `trade_state["otoco_placed_at"]` (from Task 2)
- Produces: same `(trade_state, None)` return as before

- [ ] **Step 1: Replace `entry_order_id` / `entry_placed_at` with `otoco_placed_at` in Case 1**

Replace lines 210-233:

```python
# Before:
        # --- Case 1: No position yet (entry pending or expired) ---
        if not has_position:
            entry_order_id = trade_state.get("entry_order_id")
            if entry_order_id:
                # Check timeout
                placed_at = trade_state.get("entry_placed_at")
                timeout_hours = trade_state.get("projected_waiting_hours", 24.0)

                if placed_at:
                    elapsed_hours = (datetime.now(timezone.utc) - placed_at).total_seconds() / 3600
                    if elapsed_hours > timeout_hours:
                        logger.warning(f"[{symbol}] entry order expired | id={entry_order_id} | elapsed={elapsed_hours:.1f}h > {timeout_hours}h")
                        self.client.cancel_order(symbol, entry_order_id)
                        return {}, None  # Clear trade state
                    else:
                        logger.info(f"[{symbol}] entry order pending | id={entry_order_id} | elapsed={elapsed_hours:.1f}h / {timeout_hours}h")
            else:
                # Position was entered and then closed (net≈0, no entry order).
                # Cancel any stray orders and clear stale trade state.
                if trade_state.get("entry_filled_at"):
                    logger.info(f"[{symbol}] position flat — cleaning orders")
                self.client.cancel_all_symbol_orders(symbol)
                return {}, None
            return trade_state, None

# After:
        # --- Case 1: No position yet (OTOCO pending or position closed) ---
        if not has_position:
            otoco_placed_at = trade_state.get("otoco_placed_at")
            if otoco_placed_at:
                timeout_hours = trade_state.get("projected_waiting_hours", 24.0)
                elapsed_hours = (datetime.now(timezone.utc) - otoco_placed_at).total_seconds() / 3600
                if elapsed_hours > timeout_hours:
                    logger.warning(f"[{symbol}] OTOCO entry expired | elapsed={elapsed_hours:.1f}h > {timeout_hours}h")
                    self.client.cancel_all_symbol_orders(symbol)
                    return {}, None  # Clear trade state
                else:
                    logger.info(f"[{symbol}] OTOCO entry pending | elapsed={elapsed_hours:.1f}h / {timeout_hours}h")
            else:
                # Position was entered and then closed (net≈0, no pending OTOCO).
                # Cancel any stray orders and clear stale trade state.
                if trade_state.get("entry_filled_at"):
                    logger.info(f"[{symbol}] position flat — cleaning orders")
                self.client.cancel_all_symbol_orders(symbol)
                return {}, None
            return trade_state, None
```

Key changes:
- `entry_order_id` → `otoco_placed_at` (datetime comparison, no intermediate `placed_at` variable)
- `cancel_order(symbol, entry_order_id)` → `cancel_all_symbol_orders(symbol)`
- Log prefix: "entry order" → "OTOCO entry"

- [ ] **Step 2: Verify syntax**

Run: `python3 -c "import ast; ast.parse(open('src/agent/order_executor.py').read()); print('OK')"`
Expected: `OK`

- [ ] **Step 3: Search for any remaining references to the old field names**

Run: `grep -rn "entry_order_id\|entry_placed_at" src/agent/order_executor.py run_sniper.py`

Expected output (only Case 3 dead code in order_executor.py, which is harmless):
```
src/agent/order_executor.py:289:            entry_order_id = trade_state.get("entry_order_id")
src/agent/order_executor.py:290:            if entry_order_id:
```

- [ ] **Step 4: Commit**

```bash
git add src/agent/order_executor.py
git commit -m "feat: adapt Guardian Case 1 for OTOCO entry timeout

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 4: Verify restart recovery and full flow

**Files:**
- No code changes — verification only

- [ ] **Step 1: Verify restart recovery logic untouched**

Read the restart recovery section in `order_executor.py:177-196` and confirm it uses only `direction`, `tp_price`, `sl_price` — none of the renamed fields:

Run: `sed -n '177,196p' src/agent/order_executor.py`

Expected: No mention of `entry_order_id`, `entry_placed_at`, or `otoco_placed_at`.

- [ ] **Step 2: Verify all Guardian cases other than Case 1 are untouched**

Run: `grep -n "entry_order_id\|entry_placed_at\|otoco_placed_at" src/agent/order_executor.py`

Expected: Only Case 1 uses `otoco_placed_at`; Case 3 has the harmless dead-code `entry_order_id` references.

- [ ] **Step 3: Run existing test suite**

Run: `pytest tests/ -x -q 2>&1 | tail -20`

Expected: All tests pass (no test should reference the changed fields directly — `entry_order_id` / `entry_placed_at` are internal implementation details of trade_state, not in test assertions).

- [ ] **Step 4: Verify rollback path**

Confirm that `_place_entry_order` still exists and works:

Run: `grep -n "def _place_entry_order" src/agent/order_executor.py`

Expected: Function still defined and unchanged.

- [ ] **Step 5: Commit verification notes**

```bash
git add -A
git commit -m "chore: verify OTOCO migration — restart recovery and tests intact

Co-Authored-By: Claude <noreply@anthropic.com>"
```
