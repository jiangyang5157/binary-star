# `_trace_qty` — 同 Pulse 仓位跟踪与安全双检

## 问题

一个 guardian pulse 内，`_try_breakeven()` 和 `_try_exit_ladder()` 先后各调一次 `get_symbol_position()` 来计算部分平仓数量。交易所结算有延迟，第二个 API 调用返回的是过期仓位，导致 L1 误按原始仓位（0.0092）算 tp_qty，而不是按 breakeven 后的剩余（0.0065）。

## 方案

在 `MarginOrderExecutor` 中引入 **pulse-local 的 qty trace**：每个 pulse 第一次 API 返回作为 baseline，后续所有 qty 操作在这条 trace 上做加减。每次 API 读取做 `min(abs(trace), abs(api))` 安全双检。

## 改动

### 1. 新变量

```python
self._trace_qty: dict[str, float | None] = {}
```

Key 为 symbol，value 为带符号的 net_qty。`None` = 本 pulse 尚未初始化。

### 2. 新辅助方法

#### `init_trace(symbol)`

```python
def init_trace(self, symbol: str):
    """每个 pulse 开始前重置，放在 SniperDaemon._guardian_check 第一行。"""
    self._trace_qty[symbol] = None
```

#### `_resolve_qty(symbol) → float`

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

#### `_update_trace_after_close(symbol, close_qty)`

```python
def _update_trace_after_close(self, symbol: str, close_qty: float):
    """部分平仓成功后减少 trace。close_qty 始终为正数。"""
    trace = self._trace_qty.get(symbol)
    if trace is None:
        return
    new_abs = max(0, abs(trace) - close_qty)
    self._trace_qty[symbol] = new_abs * (1 if trace >= 0 else -1)
```

### 3. 所有修改点

| # | 位置 | 当前代码 | 改为 |
|---|------|---------|------|
| 1 | `SniperDaemon._guardian_check()` 开头 | — | `self.executor.init_trace(symbol)` |
| 2 | `find_level_and_sync_sl` L705 | `get_symbol_position` → `net_qty` | `net_qty = self._resolve_qty(symbol)` |
| 3 | `guardian_check` L163 | `get_symbol_position` → `net_qty` | `net_qty = self._resolve_qty(symbol)` |
| 4 | `_guardian_case_4_protected` L409 | `get_symbol_position` → `net_qty` | `net_qty = self._resolve_qty(symbol)` |
| 5 | `_try_breakeven` partial close 成功后 | — | `self._update_trace_after_close(sym, tp_qty)`（在 L865 位置） |
| 6 | `_try_exit_ladder` partial close 成功后 | — | `self._update_trace_after_close(sym, tp_qty)`（在 L1015 位置） |
| 7 | `_breakeven_sl_only` L907 | `get_symbol_position` | `self._resolve_qty(symbol)`（只读检查，不需要更新 trace） |
| 8 | `_apply_sl_lock` L1130 | `get_symbol_position` | `self._resolve_qty(symbol)`（只读检查，不需要更新 trace） |

### 4. 不修改的例外

`execute_market_close()`（在 `margin_client.py`）保持不变。它是紧急安全阀，必须始终用实时 API 值，不走 trace。

所有 emergency close 路径（12 处）也不变。它们都是 terminal return，执行后本 pulse 无后续 qty 操作。

### 5. 修复效果验证

```
原始仓位: 0.0092
① init_trace              → trace = None
② _resolve_qty()          → api=0.0092, trace=None → trace=0.0092
③ breakeven close 0.0027  → trace -= 0.0027 = 0.0065
④ _resolve_qty()          → api=0.0092(stale), trace=0.0065 → min=0.0065 ✅
⑤ L1 tp_qty = 0.0065×0.3 = 0.0019 ✅
⑥ L1 OCO = 0.0065-0.0019 = 0.0046 ✅
```

## 不变形

- Market close 仍然用实时 API（安全阀不受影响）
- 单个 pulse 内 partial close 失败走 emergency close 时，`_update_trace_after_close` 不会误调用（放在成功分支后）
- 即使 trace 偶尔不同步，下一 pulse `init_trace` 重置，从 API 重新初始化，一个 pulse 后自愈
