# `_trace_qty` — 同 Pulse 仓位跟踪与安全双检

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix 同 pulse 内 `_try_breakeven()` 和 `_try_exit_ladder()` 因交易所结算延迟导致的 qty 计算不一致问题。

**Architecture:** 在 `MarginOrderExecutor` 中引入 pulse-local 的 qty trace。第一次 API 返回作为 baseline，后续所有 qty 操作在这条 trace 上做加减，每次 API 读取做 `min(abs(trace), abs(api))` 双检。Market close 例外，始终走实时 API。

**Tech Stack:** Python, Binance Margin API

## Global Constraints

- `_trace_qty` 是 `dict[str, float | None]`，key=symbol
- `_trace_qty[symbol] = None` 表示本 pulse 尚未初始化
- Market close 不经过 trace，始终用实时 API
- 所有 emergency close 路径不变（terminal return，无后续 qty 操作）

---

### Task 1: 添加 `_trace_qty` 变量和三个辅助方法

**Files:**
- Modify: `src/agent/order_executor.py`

**Interfaces:**
- Consumes: `self.client.get_symbol_position(symbol)` — 已有的客户端方法
- Produces: `self._trace_qty: dict[str, float | None]`, `init_trace(symbol)`, `_resolve_qty(symbol) → float`, `_update_trace_after_close(symbol, close_qty: float)`

- [ ] **Step 1: 在 `__init__` 中添加 `_trace_qty` 变量**

在 `src/agent/order_executor.py` 的 `MarginOrderExecutor.__init__` 方法中（line 42-60 附近），在已有实例变量初始化完成后添加：

```python
self._trace_qty: dict[str, float | None] = {}
```

寻找合适的插入位置：在 `self._symbol_config`、`self._guardian_config` 等配置缓存变量附近添加最合适。

- [ ] **Step 2: 添加 `init_trace(symbol)` 方法**

在 `MarginOrderExecutor` 类中找一个合适的位置——建议放在 `guardian_check` 方法前面，或放在 `find_level_and_sync_sl` 前面（因为它是 pulse 入口调用）。方法体：

```python
def init_trace(self, symbol: str):
    """每个 pulse 开始前重置。由 SniperDaemon._guardian_check 调用。"""
    self._trace_qty[symbol] = None
```

- [ ] **Step 3: 添加 `_resolve_qty(symbol)` 方法**

紧跟 `init_trace` 方法后面：

```python
def _resolve_qty(self, symbol: str) -> float:
    """读取仓位，用 trace 做 min double-check。
    
    首次调用: 初始化 trace baseline。
    后续调用: min(abs(trace), abs(api)) 保守取小。
    Market close: 不经过此方法，直接读实时 API。
    """
    pos = self.client.get_symbol_position(symbol)
    api_qty = pos.net_qty if pos else 0.0

    trace = self._trace_qty.get(symbol)
    if trace is None:
        self._trace_qty[symbol] = api_qty
        return api_qty

    abs_resolved = min(abs(trace), abs(api_qty))
    sign = 1 if trace >= 0 else -1
    self._trace_qty[symbol] = abs_resolved * sign
    return self._trace_qty[symbol]
```

- [ ] **Step 4: 添加 `_update_trace_after_close(symbol, close_qty)` 方法**

紧跟 `_resolve_qty` 方法后面：

```python
def _update_trace_after_close(self, symbol: str, close_qty: float):
    """部分平仓成功后减少 trace。close_qty 始终为正数。"""
    trace = self._trace_qty.get(symbol)
    if trace is None:
        return
    new_abs = max(0, abs(trace) - close_qty)
    self._trace_qty[symbol] = new_abs * (1 if trace >= 0 else -1)
```

- [ ] **Step 5: 验证导入和语法正确**

```bash
python3 -c "from src.agent.order_executor import MarginOrderExecutor; print('OK')"
```

Expected: `OK`

- [ ] **Step 6: Commit**

```bash
git add src/agent/order_executor.py
git commit -m "feat: add _trace_qty and helper methods for pulse-local qty tracking

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 2: 将 `get_symbol_position` 替换为 `_resolve_qty`（5 处只读调用点）

**Files:**
- Modify: `src/agent/order_executor.py`

**Interfaces:**
- Consumes: `self._resolve_qty(symbol) → float`（来自 Task 1）
- Replaces: `self.client.get_symbol_position(symbol)` + `pos.net_qty if pos else 0.0` → `self._resolve_qty(symbol)`

所有替换点的模式相同：`pos = self.client.get_symbol_position(symbol)` + `net_qty = pos.net_qty if pos else 0.0` → 直接改为 `net_qty = self._resolve_qty(symbol)`。

- [ ] **Step 1: 替换 `find_level_and_sync_sl` L705-706**

```python
# 替换前:
pos = self.client.get_symbol_position(symbol)
net_qty = pos.net_qty if pos else 0.0
active_orders = self.client.get_active_orders(symbol)

# 替换后:
net_qty = self._resolve_qty(symbol)
active_orders = self.client.get_active_orders(symbol)
```

注意：仅替换 `get_symbol_position` 两行。`get_active_orders` 不受影响。

- [ ] **Step 2: 替换 `guardian_check` L163-164**

```python
# 替换前:
pos = self.client.get_symbol_position(symbol)
net_qty = pos.net_qty if pos else 0.0
active_orders = self.client.get_active_orders(symbol)

# 替换后:
net_qty = self._resolve_qty(symbol)
active_orders = self.client.get_active_orders(symbol)
```

- [ ] **Step 3: 替换 `_guardian_case_4_protected` L409-410**

```python
# 替换前:
pos = self.client.get_symbol_position(symbol)
net_qty = pos.net_qty if pos else 0.0
if abs(net_qty) <= 0:
    return {}, None

# 替换后:
net_qty = self._resolve_qty(symbol)
if abs(net_qty) <= 0:
    return {}, None
```

- [ ] **Step 4: 替换 `_breakeven_sl_only` L907-908**

```python
# 替换前:
pos = self.client.get_symbol_position(symbol)
if not pos or abs(pos.net_qty) <= 0:
    logger.info(f"[{symbol}] breakeven SL-only — position already closed")
    return True, {}

# 替换后:
pos_qty = self._resolve_qty(symbol)
if abs(pos_qty) <= 0:
    logger.info(f"[{symbol}] breakeven SL-only — position already closed")
    return True, {}
```

注意此处要保留 `pos` 变量名 → 改为 `pos_qty`（不再是对象，只是 float）。下面 L913 附近如果有使用 `pos` 的地方也需要调整。检查 `_breakeven_sl_only` 的完整函数体，确认无其他 `pos` 引用。

- [ ] **Step 5: 替换 `_apply_sl_lock` L1130-1137**

```python
# 替换前:
pos = self.client.get_symbol_position(symbol)
if not pos or abs(pos.net_qty) <= 0:
    logger.critical(f"[{symbol}] dynamic SL -- position vanished, emergency closing")
    if not self.client.execute_market_close(symbol):
        logger.critical(f"[{symbol}] emergency close FAILED — keeping trade state for retry next pulse")
        return True, None
    return False, None
exchange_qty = round(abs(pos.net_qty), cfg["precision_qty"])

# 替换后:
pos_qty = self._resolve_qty(symbol)
if abs(pos_qty) <= 0:
    logger.critical(f"[{symbol}] dynamic SL -- position vanished, emergency closing")
    if not self.client.execute_market_close(symbol):
        logger.critical(f"[{symbol}] emergency close FAILED — keeping trade state for retry next pulse")
        return True, None
    return False, None
exchange_qty = round(abs(pos_qty), cfg["precision_qty"])
```

注意：变 `pos` 对象 → `pos_qty` float。`exchange_qty` 从 `pos.net_qty` 改为 `pos_qty`。下面用到 `pos` 的地方也一并调整（如果有的话），搜索函数体内所有 `pos` 引用。

- [ ] **Step 6: 验证语法正确**

```bash
python3 -c "from src.agent.order_executor import MarginOrderExecutor; print('OK')"
```

Expected: `OK`

- [ ] **Step 7: Commit**

```bash
git add src/agent/order_executor.py
git commit -m "refactor: replace get_symbol_position with _resolve_qty in guardian flow

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 3: 在 partial close 成功后添加 `_update_trace_after_close`

**Files:**
- Modify: `src/agent/order_executor.py`

**Interfaces:**
- Consumes: `self._update_trace_after_close(symbol, close_qty)`（来自 Task 1）
- Placement: 在 partial market close 成功后、OCO re-place / 返回值之前

- [ ] **Step 1: 在 `_try_breakeven` 中添加**

在 line 865（`execute_partial_market_close` 成功后）之后、L872 ("Fully closed?" 检查) 之前插入：

```python
        if not self.client.execute_partial_market_close(
            symbol=symbol, side=close_side, qty=tp_qty
        ):
            logger.critical(f"[{symbol}] breakeven — close failed, emergency closing all")
            if not self.client.execute_market_close(symbol):
                logger.critical(f"[{symbol}] breakeven — emergency close FAILED, position naked")
            return False, None

        # ── Update trace after successful partial close ──
        self._update_trace_after_close(symbol, tp_qty)

        # Fully closed?
        if remaining_qty < cfg.get("min_order_qty", 0):
            logger.info(f"[{symbol}] breakeven — position fully closed")
            return True, {}
```

插入完成后该区域代码应该是：

```python
        close_side = self._exit_side(direction)
        if not self.client.execute_partial_market_close(
            symbol=symbol, side=close_side, qty=tp_qty
        ):
            logger.critical(f"[{symbol}] breakeven — close failed, emergency closing all")
            if not self.client.execute_market_close(symbol):
                logger.critical(f"[{symbol}] breakeven — emergency close FAILED, position naked")
            return False, None

        # ── Update trace after successful partial close ──
        self._update_trace_after_close(symbol, tp_qty)

        # Fully closed?
        if remaining_qty < cfg.get("min_order_qty", 0):
            logger.info(f"[{symbol}] breakeven — position fully closed")
            return True, {}
```

- [ ] **Step 2: 在 `_try_exit_ladder` 中添加**

在 line 1014（`execute_partial_market_close` 成功后）之后、L1023（`remaining_qty = ...`）之前插入：

```python
        if not self.client.execute_partial_market_close(
            symbol=symbol, side=close_side, qty=tp_qty
        ):
            logger.critical(
                f"[{symbol}] exit ladder L{i+1} — market close failed, emergency closing all"
            )
            if not self.client.execute_market_close(symbol):
                logger.critical(f"[{symbol}] emergency close FAILED — position naked")
                return False, None
            return False, None

        # ── Update trace after successful partial close ──
        self._update_trace_after_close(symbol, tp_qty)

        remaining_qty = abs(live_net_qty) - tp_qty
        if remaining_qty < cfg.get("min_order_qty", 0):
            logger.info(f"[{symbol}] exit ladder L{i+1} — position fully closed")
            return True, {}
```

- [ ] **Step 3: 验证语法正确**

```bash
python3 -c "from src.agent.order_executor import MarginOrderExecutor; print('OK')"
```

Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add src/agent/order_executor.py
git commit -m "feat: update _trace_qty after partial closes in breakeven and exit ladder

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 4: 在 daemon pulse 入口添加 `init_trace` 调用

**Files:**
- Modify: `run_sniper.py`

**Interfaces:**
- Consumes: `self.executor.init_trace(symbol)`（来自 Task 1）

- [ ] **Step 1: 在 `SniperDaemon._guardian_check` 开头添加**

在 `run_sniper.py` 的 `SniperDaemon._guardian_check` 方法（line 525），在 `try:` 之后、现有代码之前添加：

```python
    def _guardian_check(self, symbol: str) -> dict | None:
        """Delegates to MarginOrderExecutor.guardian_check() and updates trade_states[symbol]."""
        try:
            # Reset pulse-local qty trace for this symbol
            self.executor.init_trace(symbol)

            logger.debug(f"[{symbol}] checking position state")
            ...
```

- [ ] **Step 2: 验证语法正确**

```bash
python3 -c "from run_sniper import SniperDaemon; print('OK')"
```

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add run_sniper.py
git commit -m "feat: reset _trace_qty at start of each guardian pulse

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 5: 验证修复效果（手动测试或单元测试）

**Files:**
- Check: `src/agent/order_executor.py`（已修改）
- Test: `tests/unit/test_order_executor.py` 或 `tests/unit/test_order_executor_exceptions.py`

- [ ] **Step 1: 检查现有测试是否能通过**

```bash
python3 -m pytest tests/unit/test_order_executor_exceptions.py -v 2>&1 | head -40
```

Expected: 所有现有测试通过（不引入回归）

- [ ] **Step 2: 在 `_resolve_qty` 中添加简单的调试日志（可选，验证用）**

```python
def _resolve_qty(self, symbol: str) -> float:
    pos = self.client.get_symbol_position(symbol)
    api_qty = pos.net_qty if pos else 0.0
    trace = self._trace_qty.get(symbol)
    if trace is None:
        self._trace_qty[symbol] = api_qty
        logger.debug(f"[{symbol}] trace initialized | api={api_qty}")
        return api_qty
    abs_resolved = min(abs(trace), abs(api_qty))
    sign = 1 if trace >= 0 else -1
    self._trace_qty[symbol] = abs_resolved * sign
    logger.debug(f"[{symbol}] trace resolved | trace_before={trace} | api={api_qty} | resolved={self._trace_qty[symbol]}")
    return self._trace_qty[symbol]
```

**注意：** 验证完成后建议将 `logger.debug` 移除或改为 `TRACE` 级别，避免生产环境日志过多。

- [ ] **Step 3: 运行 sniper 观察日志**

```bash
grep "trace" /Users/yangjiang/workspace/binary-star/data/prod/sniper.log | grep "BTCUSDT" | tail -20
```

Expected: 可以看到 trace init 和 resolve 的日志，breakeven 后 L1 使用的是 correct/trace-reduced qty

- [ ] **Step 4: 完成确认后移除调试日志（如果 Step 2 加了）**

如果 Step 2 添加了 `logger.debug`，将其移除。

- [ ] **Step 5: 最终验证代码整洁**

```bash
git diff
```

检查是否有未预期的改动（比如调试日志残留、多余空格）。

- [ ] **Step 6: Final commit**

```bash
git add -A
git commit -m "chore: cleanup debug logging from trace_qty implementation

Co-Authored-By: Claude <noreply@anthropic.com>"
```
