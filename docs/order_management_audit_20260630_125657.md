# Order Management Audit Report — 2026-06-30 12:56 UTC

## Executive Summary

**8 dimensions audited across 4 parallel review agents. 13 unique findings identified. 4 fixed (A/B/D/E).**

| Severity | Found | Fixed | Remaining |
|----------|-------|-------|-----------|
| CRITICAL | 0 | 0 | 0 |
| HIGH | 11 | 4 | 7 |
| MEDIUM | 2 | 0 | 2 |

### Fixes Applied (2026-06-30)

| ID | Root Cause | Fix | File |
|----|-----------|-----|------|
| **A** | `get_ticker_price()` 返回 0 导致误平仓 | Case 3 SL-breach 前加 `current_price <= 0` guard | `order_executor.py:357` |
| **B** | pivot-preserve 先取消再挂 OCO（裸仓窗口） | 先挂新 OCO → 成功后取消旧单 → 失败保留旧 OCO | `order_executor.py:163-199` |
| **D** | 方向冲突只检测不修复（反向 OCO） | 冲突时 `cancel_all_symbol_orders` | `order_executor.py:336-341` |
| **E** | `find_level_and_sync_sl` 紧急平仓后 fallthrough | 紧急平仓后 `return 0` | `order_executor.py:762-769` |
| MEDIUM | 2 |

### Top Risks by Score

| # | Score | Title | Root Cause |
|---|-------|-------|------------|
| 1 | 50 | [D7] Restart with pending entry order → fills into naked position | Post-restart state gap |
| 2 | 45 | [D1] `find_level_and_sync_sl` missing return after emergency close | Missing return/cleanup |
| 3 | 45 | [D2] Cancel-before-close + orientation conflict blocks re-protection | Cancel-before-close ordering |
| 4 | 40 | [D8] `get_ticker_price()` returns 0 → false emergency close (LONG) | No guard on error value |
| 5 | 40 | [D6] Manual reverse — direction sanity detects but doesn't fix wrong-side OCO | Detect-only, no action |
| 6 | 40 | [D1] Triple-site: emergency close failure returns "position intact" | Missing sentinel propagation |
| 7 | 36 | [D5] Same-pulse emergency-close + AI re-open concurrency | Lack of post-close cooldown |

---

## Root Cause Analysis

The 13 findings cluster into **5 root causes**:

### Root Cause A: `get_ticker_price()` returns 0 on failure — unguarded call sites

**Affected findings**: (1) False emergency close on LONG, (2) False partial TP triggers, (3) `guardian_check` Case 3 SL-breach, (4) `guardian_check` Case 4 partial TP

`src/infrastructure/binance/margin_client.py:122-132`: `get_ticker_price()` returns `0.0` on any exception. Two call sites in `guardian_check` consume this value without checking for 0:

- **Line 357‑370 (Case 3 SL‑breach)**: `current_price <= sl` → `0 <= positive_sl` is always TRUE for LONG → false emergency close. SHORT is accidentally safe (`0 >= positive_sl` is FALSE).
- **Line 470 (Case 4 partial TP)**: `deviation = abs(0 - entry) = entry` → may falsely trigger all partial TP levels.

The fix pattern already exists at `sync_with_opinion:136` (`if current_price is None or current_price <= 0: return None`). The same guard is missing in `guardian_check`.

**Fix**: Add `if not current_price or current_price <= 0:` guard before both call sites in `guardian_check`.

---

### Root Cause B: Cancel-before-close ordering leaves no recovery path

**Affected findings**: (1) Pivot A‑1/A‑2 cancel‑before‑market‑close, (2) Triple‑site OCO failure + emergency close failure = `intact=True`, (3) A‑2 OCO failure path

The architectural pattern across all pivot and OCO‑migration paths is: **cancel orders → then do something risky (market close / OCO place)**. If the risky step fails AND the emergency close also fails, the position is naked with all orders cancelled. Worse, the return values (`True, None` or `None`) do not distinguish "position is fine" from "position is naked and we couldn't close it."

At `_optimize_same_direction:597‑601`, `_try_partial_tp:857‑863`, `_migrate_dynamic_sl:941‑945`: when OCO placement fails AND emergency close fails, the functions return `(True, None)` — "position intact." The callers continue as if protected.

At `sync_with_opinion:164‑212` (pivot paths): orders are cancelled BEFORE market close. If market close fails, position is open with no orders. Return `None` is indistinguishable from "no action needed."

**Fix**: Two changes needed:
1. **Reorder**: Do NOT cancel orders until the replacement is confirmed. Place OCO first, cancel old orders on success. Or re‑place the original protection if the operation fails.
2. **Propagate sentinel**: When emergency close fails, return `_EMERGENCY_CLOSED_SENTINEL` so the daemon clears state rather than continuing with a naked position.

---

### Root Cause C: Post‑restart state gaps

**Affected findings**: (1) Pending entry order untracked after restart, (2) Unprotected position after restart

`guardian_check` STEP 1 (line 270‑289): when `trade_state` is empty and no position exists, the guardian returns early without checking for pending LIMIT entry orders on the exchange. If a pending entry fills after restart, the resulting position has no `trade_state` and no OCO — guardian returns early again (line 287: position + no OCO + no trade_state). The position runs naked until the next AI trigger.

Additionally, when `trade_state` is empty and a position exists but has no OCO (daemon stopped before guardian could place protection), the same early‑return leaves it naked.

**Fix**: In STEP 1, when `trade_state` is empty:
- If pending LIMIT entry orders exist on exchange → reconstruct minimal trade_state from them.
- If position exists with no OCO → place a wide emergency SL (e.g., 3× ATR from current price) as a safety net, or log CRITICAL for operator intervention.

---

### Root Cause D: Direction sanity detects conflict but takes no action

**Affected findings**: (1) Manual reverse leaves wrong‑side OCO, (2) Orientation conflict on restart/pivot

`guardian_check` Case 2 (line 332‑341): when `trade_state["direction"]` disagrees with `net_qty` sign, the code throttled‑logs the conflict and returns early — **no orders are cancelled, no emergency close is triggered**. If `direction="LONG"` but the actual position is SHORT, the existing OCO was placed with `side="SELL"` (closing a LONG). A STOP_LOSS_LIMIT SELL on a SHORT position would **increase** the short exposure instead of capping the loss.

This is triggered by: manual reversal (user closes LONG + opens SHORT externally), or a pivot path leaving stale direction in `trade_state`.

**Fix**: When direction conflict is detected, immediately `cancel_all_symbol_orders(symbol)` and return `trade_state` unchanged. The position becomes naked → next pulse's Case 3 will detect "position without OCO" and either place OCO (if TP/SL known) or emergency‑close (if TP/SL missing).

---

### Root Cause E: Missing returns and sentinels in emergency paths

**Affected findings**: (1) `find_level_and_sync_sl` falls through after emergency close, (2) Case 4 qty mismatch fallthrough, (3) Same‑pulse close‑reopen

`find_level_and_sync_sl:757‑769`: After emergency close (whether successful or failed), execution falls through to `return next_level` with no indication the position was closed. The daemon stores this `next_level` as the current level, unaware the position is gone.

`guardian_check` Case 4 qty re‑align (line 453‑454): When OCO qty mismatch is detected but no TP/SL prices are available, the code logs `logger.critical` but does NOT emergency close. Falls through to partial TP logic.

`run_sniper.py:169‑262`: Guardian runs first and can emergency‑close a position. Later in the same pulse, `has_active` reads empty `trade_states` → AI CAN fire and re‑enter immediately on the same volatility that caused the close.

**Fix**:
1. `find_level_and_sync_sl`: Return `0` (or sentinel) after emergency close.
2. Case 4 qty mismatch: Emergency‑close when no TP/SL available.
3. Daemon: Set a per‑symbol `_emergency_close_cooldown` flag to prevent same‑pulse re‑entry.

---

## Fixes Applied

### Fix A: `get_ticker_price() = 0` → 误触发紧急平仓

**文件**: `src/agent/order_executor.py:357`

**问题**: `guardian_check` Case 3 调用 `get_ticker_price` 后不检查返回值。API 失败返回 `0.0` → LONG 仓位 `0.0 <= sl` 永远 True → 错误紧急平仓。

**修复**: SL-breach 检查前加 guard，匹配 `sync_with_opinion` 已有的模式：
```python
current_price = self.client.get_ticker_price(symbol)
if not current_price or current_price <= 0:      # ← 新增
    logger.error(f"[{symbol}] ticker unavailable (price={current_price}) — deferring SL breach check")
    return trade_state, None                      # ← 新增：保留仓位，下个 pulse 重试
```

---

### Fix B: pivot-preserve 先挂 OCO 再取消旧单

**文件**: `src/agent/order_executor.py:163-199`

**问题**: A-2 standard（pivot-preserve）路径：先 `cancel_all_symbol_orders` → 再 `place_oco_order`。如果新 OCO 失败，旧 OCO 已被取消，仓位裸奔。即使新 OCO 成功，cancel 和 place 之间也存在裸仓窗口。

**修复**: 调整顺序——**先挂新 OCO，成功后再取消旧单**：
```python
# 先挂新 OCO
oco_success = self.client.place_oco_order(...)
if not oco_success:
    # 失败 → 旧 OCO 还在（未取消），紧急平仓
    ...
    return self._place_entry_order(...)

# 新 OCO 已生效 → 安全清理旧单（best-effort，失败也无害）
if not self.client.cancel_all_symbol_orders(symbol):
    logger.warning("failed to cancel old orders (new OCO already active)")
```

---

### Fix D: 方向冲突时取消错误方向订单

**文件**: `src/agent/order_executor.py:336-341`

**问题**: guardian Case 2 检测到 `trade_state["direction"]` 与实际 `net_qty` 符号不一致时，只打 log 不行动。LONG-protection OCO（SELL 方向）留在 SHORT 仓位上 → SELL 止损触发 = 加空而非减仓。

**修复**: 冲突时立即取消所有订单，让仓位裸奔 → 下个 pulse Case 3 检测到「有仓位无 OCO」→ 紧急平仓：
```python
if (intent == "LONG" and not is_long_pos) or (intent == "SHORT" and not is_short_pos):
    ...
    self.client.cancel_all_symbol_orders(symbol)  # ← 新增
    return trade_state, None
```

---

### Fix E: `find_level_and_sync_sl` 紧急平仓后 return 0

**文件**: `src/agent/order_executor.py:762-769`

**问题**: `find_level_and_sync_sl` 中 OCO 重挂失败 → 紧急平仓 → 无论成败都 fallthrough 到 `return next_level`（如 2）。daemon 收到 `next_level=2` 以为「部分止盈 L2 已完成」，但仓位已被平掉（或裸奔）。

**修复**: 紧急平仓后 `return 0`，强制 daemon 重置 level：
```python
if not self.client.place_oco_order(...):
    logger.critical("OCO re-place failed, emergency closing")
    if not self.client.execute_market_close(symbol):
        logger.critical("emergency close FAILED")
    else:
        logger.info("emergency close succeeded, position closed")
    return 0  # ← 新增：reset level
```

---

## Full Finding Index

### HIGH Severity

#### [D8] `get_ticker_price()` returns 0 → false emergency close on LONG positions
- **File**: `src/agent/order_executor.py:357‑370`, `src/infrastructure/binance/margin_client.py:122‑132`
- **Risk**: L=3 × I=4 × D=3 = **36**
- **Description**: Ticker API failure returns 0.0. `guardian_check` Case 3 SL‑breach check: `current_price(0) <= sl(positive)` is always True for LONG, triggering emergency market close of a healthy position. SHORT is accidentally safe.
- **Also**: Line 470 — `current_price=0` causes `deviation = |0 - entry| = entry`, potentially falsely triggering all partial TP levels.
- **Fix**: Add `if not current_price or current_price <= 0:` guard at both call sites (line 359 and line 470), matching the existing pattern at `sync_with_opinion:136`.

#### [D1] `find_level_and_sync_sl` missing return after emergency close
- **File**: `src/agent/order_executor.py:757‑769`
- **Risk**: L=3 × I=5 × D=3 = **45**
- **Description**: After emergency close at line 763 (whether success or fail), execution falls through to `return next_level`. Caller receives an integer as if everything is normal. After a failed emergency close, position is naked with no indication.
- **Fix**: Return `0` after successful emergency close; return `_EMERGENCY_CLOSED_SENTINEL` after failed emergency close.

#### [D2] Cancel‑before‑close ordering in pivot paths — no re‑protection on failure
- **File**: `src/agent/order_executor.py:164‑212`
- **Risk**: L=3 × I=5 × D=3 = **45**
- **Description**: In Case A‑1 (line 206‑212) and A‑2 (line 164‑193), orders are cancelled BEFORE market close. If market close fails, position is open with no orders. Return `None` gives caller no indication. Combined with orientation conflict (Case 2), the position may never be re‑protected.
- **Fix**: Cancel orders only AFTER confirming market close success. If market close fails, re‑place the original OCO protection.

#### [D1] Triple‑site: OCO failure + emergency close failure returns "intact=True"
- **File**: `src/agent/order_executor.py:599‑601`, `861‑863`, `943‑945`
- **Risk**: L=2 × I=5 × D=4 = **40**
- **Description**: At `_optimize_same_direction`, `_try_partial_tp`, and `_migrate_dynamic_sl`: when both OCO placement AND subsequent emergency close fail, functions return `(True, None)` — signaling "position intact." The daemon continues as if protected, but the position has all orders cancelled.
- **Fix**: Return `(False, None)` or `_EMERGENCY_CLOSED_SENTINEL` to force daemon to clear trade state. Or re‑structure to NOT cancel before placing new OCO.

#### [D2] A‑2 OCO failure + emergency close failure → naked position, no sentinel
- **File**: `src/agent/order_executor.py:187‑195`
- **Risk**: L=2 × I=5 × D=4 = **40**
- **Description**: Pivot‑preserve: OCO placement fails → emergency close called. If emergency close ALSO fails, returns `None`. All orders were already cancelled at line 164. Position is open and naked. `None` return is indistinguishable from "no action needed."
- **Fix**: Return `_EMERGENCY_CLOSED_SENTINEL` on emergency close failure.

#### [D6] Manual reverse — direction sanity detects but doesn't fix wrong‑side OCO
- **File**: `src/agent/order_executor.py:332‑341`
- **Risk**: L=2 × I=5 × D=4 = **40**
- **Description**: Case 2 detects when intent direction disagrees with actual net_qty sign, but only throttled‑logs the conflict and returns early — no orders are cancelled. A LONG‑protection OCO (SELL side) on a SHORT position means: SELL STOP_LOSS_LIMIT on a SHORT = increasing the short (not capping loss). Position has inverted protection.
- **Fix**: On conflict detection, `cancel_all_symbol_orders(symbol)`. Let next pulse's Case 3 handle the now‑unprotected position.

#### [D5] Same‑pulse emergency‑close + AI re‑open concurrency
- **File**: `run_sniper.py:169‑173`, `run_sniper.py:262‑273`
- **Risk**: L=3 × I=4 × D=3 = **36**
- **Description**: Guardian runs first, emergency‑closes a position, clears `trade_state`. Later in same pulse, AI session fires (since `has_active=False` after the clear) and can open a new position on the same volatility that caused the close.
- **Fix**: Set a per‑symbol `_emergency_close_cooldown` timestamp. Skip AI sessions for that symbol if cooldown hasn't expired.

#### [D7] Restart with pending entry order → fills into naked position
- **File**: `src/agent/order_executor.py:287‑289`
- **Risk**: L=2 × I=5 × D=5 = **50**
- **Description**: On daemon restart with empty `trade_states`, guardian STEP 1 returns early without detecting pending LIMIT entry orders on the exchange. If the entry fills, the resulting position has no `trade_state` and no OCO — guardian's next pulses return early at line 287 (position + no OCO + no trade_state). Position runs naked until next AI trigger.
- **Fix**: In STEP 1, detect pending LIMIT entry orders from exchange. If found, reconstruct a minimal `trade_state` (direction from entry side, entry_order_id from order).

#### [D7] Restart with unprotected position runs naked
- **File**: `src/agent/order_executor.py:286‑287`
- **Risk**: L=2 × I=5 × D=3 = **30**
- **Description**: Restart with position but no OCO → guardian returns early. Position unprotected until next AI trigger, which could be hours away.
- **Fix**: Place a wide emergency SL (e.g., 3× ATR from current price) as safety net. At minimum, log CRITICAL for operator awareness.

#### [D8] `get_active_orders` silent failure returns empty list
- **File**: `src/infrastructure/binance/margin_client.py:115‑120`
- **Risk**: L=2 × I=5 × D=3 = **30**
- **Description**: On API error, `get_active_orders` catches the exception and returns `[]`. Guardian sees "no active orders" and may falsely conclude the position is unprotected → triggers unnecessary OCO placement or emergency close.
- **Fix**: Return `None` on failure instead of `[]`, and handle `None` at call sites by skipping the pulse rather than acting on missing data.

#### [D1] Case 4 qty mismatch — no TP/SL available, falls through without emergency close
- **File**: `src/agent/order_executor.py:453‑454`
- **Risk**: L=2 × I=5 × D=3 = **30**
- **Description**: OCO qty mismatch detected, but no TP/SL prices available from orders or trade_state. Logs `logger.critical` but does NOT emergency close. Position continues with mismatched protection.
- **Fix**: When `oco_tp <= 0 or oco_sl <= 0`, call `cancel_all_symbol_orders` + `execute_market_close`.

### MEDIUM Severity

#### [D2] A‑1 partial fill residual after market close
- **File**: `src/agent/order_executor.py:210‑215`
- **Risk**: L=2 × I=4 × D=4 = **32**
- **Description**: `execute_market_close` can partially fill. Residual qty left unprotected alongside new entry. Guardian protects the combined qty on next pulse.
- **Fix**: After market close, re‑verify position qty. If residual > tolerance, retry close or place emergency OCO.

#### [D1] `_optimize_same_direction` — stale trade_state on cancel failure
- **File**: `src/agent/order_executor.py:569‑571`
- **Risk**: L=2 × I=3 × D=4 = **24**
- **Description**: When `cancel_all_symbol_orders` fails, function returns optimized TP/SL prices that were never applied to exchange. Self‑corrects on next pulse (guardian reads from exchange).
- **Fix**: Return existing (unoptimized) prices when cancel fails, not the new ones.

---

## Risk Matrix

| Risk | L | I | D | Score | Mitigation |
|------|---|---|---|-------|------------|
| Restart with pending entry → naked fill | 2 | 5 | 5 | **50** | Reconstruct trade_state from exchange orders |
| find_level_and_sync_sl fallthrough | 3 | 5 | 3 | **45** | Return sentinel after emergency close |
| Cancel-before-close blocks re-protection | 3 | 5 | 3 | **45** | Reorder: close first, cancel after |
| Ticker=0 false emergency close (LONG) | 3 | 4 | 3 | **36** | Guard `current_price > 0` |
| Manual reverse → wrong-side OCO | 2 | 5 | 4 | **40** | Cancel all orders on conflict |
| Triple-site intact=True after emerg fail | 2 | 5 | 4 | **40** | Return sentinel, or don't cancel first |
| A-2 OCO fail + emerg close fail | 2 | 5 | 4 | **40** | Return `_EMERGENCY_CLOSED_SENTINEL` |
| Same-pulse close + reopen | 3 | 4 | 3 | **36** | Post-emergency-close cooldown |
| A-1 partial fill residual | 2 | 4 | 4 | **32** | Re-verify qty after market close |
| Restart unprotected position | 2 | 5 | 3 | **30** | Place emergency SL or log CRITICAL |
| get_active_orders silent [] return | 2 | 5 | 3 | **30** | Return None, skip pulse on None |
| Case 4 qty mismatch fallthrough | 2 | 5 | 3 | **30** | Emergency close on no TP/SL |
| Stale trade_state on cancel fail | 2 | 3 | 4 | **24** | Return existing prices, not new |

---

## Appendix: Confirmed‑Safe Paths

The following code paths were verified correct by at least one audit agent:

- **SL slippage buffer direction**: All 7 call sites use identical `sl + (buffer if SHORT else -buffer)` pattern — directionally correct.
- **SL migration direction**: `max(current_sl, price - N×ATR)` for LONG, `min(current_sl, price + N×ATR)` for SHORT — SL only moves favorably.
- **Level loop sequentiality**: `for i in range(start_level, len(levels))` with `break` at first unmet threshold — L1→L2→L3 ordering enforced.
- **Overshot detection operator**: `<=` (not `<`) is correct — at exact equality, entry would be marketable limit.
- **Pivot TP selection**: `pivot_tp = entry_price` — intentional "Seamless Flip" design.
- **Entry timeout default**: `projected_waiting_hours` defaults to 24.0 — reasonable.
- **Restart reconstruction**: Missing fields (`entry_filled_at`, `projected_holding_hours`, `entry_atr`) are not used by active‑protection path.
- **Partial TP full‑close detection**: `live_qty <= 0` returns `True, {}` → daemon correctly clears all state.
- **Config validity**: `global_config.yaml` guardian levels are syntactically valid and consistent with code expectations.
