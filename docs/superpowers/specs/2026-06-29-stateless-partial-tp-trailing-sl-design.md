# Stateless Partial TP + Dynamic Trailing SL

**Date:** 2026-06-29
**Status:** spec

---

## 1. Motivation

当前系统使用固定三级移动止损（1.5 / 2.5 / 4.0 ATR），不涉及分批止盈。问题：

- Level 1（保本）之后价格回撤 → 零盈利甚至亏损手续费
- `trade_state` 纯内存，重启丢失 → `trailing_sl_level` 归零
- 手动改仓后 entry 不更新 → 移动止损基于过期数据
- 三级离散迁移，Level 1→2 之间 SL 纹丝不动

## 2. Design Goals

1. **零持久化**：不依赖任何内存状态或文件恢复。所有决策信息来自交易所实时数据
2. **手动改仓自动适应**：用户随时补仓/改 OCO，系统通过 FIFO 重算 avg_entry 自动跟上
3. **Level 1 分批止盈**：首次浮盈达标时落袋 50%，剩余仓位进入零风险保本 + 动态尾随
4. **SL 以当前 SL 为基准连续推进**：不用固定级别，不依赖 entry 做后续判断，SL 自己成为锚点

## 3. Architecture

### 3.1 新增基础设施：avg_entry 计算与缓存

**文件：** `margin_client.py`

新增方法 `get_avg_entry_price(symbol, net_qty)`：

1. 若 `net_qty` 与缓存一致 → 返回缓存值
2. 若不一致 → 调用 `margin_my_trades(symbol, limit=500)`，FIFO 计算加权均价
3. 缓存 `(net_qty, avg_entry)`

**FIFO 算法（方向感知）：**

```
LONG 持仓（net_qty > 0）:
  - BUY = 增加仓位，入队
  - SELL = 减少仓位，FIFO 扣最早的 BUY
  - 队列剩余 = 当前活跃仓位的买入记录
  - avg_entry = Σ(price × qty) / Σ(qty)

SHORT 持仓（net_qty < 0）:
  - SELL = 增加仓位（绝对值），入队
  - BUY = 减少仓位（绝对值），FIFO 扣最早的 SELL
  - avg_entry = Σ(price × qty) / Σ(qty)   ← 做空均价
```

**翻页：** 若 500 笔不够覆盖当前仓位（队列总 qty < |net_qty|），用 `fromId` 翻页继续拉，直到覆盖。

**API 压力：** 仅在 net_qty 变化时调用（入场成交、TP/SL 成交、手动补仓），实际频率远低于每 pulse。缓存命中时不产生额外 API 调用。

### 3.2 Guardian Pulse 主流程

**文件：** `order_executor.py` — `guardian_check()`

```
每个 Pulse:
  │
  ├─ Step 0: 检测 entry 是否需要刷新
  │   avg_entry = client.get_avg_entry_price(symbol, net_qty)
  │   （内部缓存，net_qty 未变则直接返回）
  │
  ├─ Step 1: 裸仓保护（保留现有 Case 3 逻辑，不动）
  │   有仓位、无 SL 单 → 挂 OCO 或紧急平仓
  │
  ├─ Step 2: 分批止盈判断 → _try_partial_tp()
  │   前置：从活跃订单提取 api.SL（STOP_LOSS_LIMIT.stop_price）和 api.TP（LIMIT.price）
  │   LONG:  api.SL >= avg_entry → 跳过，进入 Step 3
  │   SHORT: api.SL <= avg_entry → 跳过，进入 Step 3
  │   否则: |price - avg_entry| >= 1.5 × ATR_macro？
  │     → 市价止盈 50% qty
  │     → 对剩余 50% qty：挂 OCO（SL=avg_entry, TP=api.TP）
  │     → 失败则紧急平仓
  │
  └─ Step 3: 动态尾随止损 → _migrate_dynamic_sl()
      前置：从活跃订单提取 api.SL 和 api.TP
      LONG:  new_sl = max(api.SL, api.price - 1.5 × ATR_macro)
      SHORT: new_sl = min(api.SL, api.price + 1.5 × ATR_macro)
      new_sl ≠ api.SL？
        → 取消 OCO → 挂新 OCO（SL=new_sl, TP=api.TP, qty=剩余）
        → 失败则紧急平仓
```

### 3.3 取消-重挂安全模型

与现有系统一致：取消成功 + 重挂失败 → 紧急市价平仓。取消失败 → 中止，保留旧 OCO。

### 3.4 原有三级迁移移除

`_migrate_trailing_stop` 被 Step 2 + Step 3 替代。`global_config.yaml` 中的三级阈值（`trailing_profit_atr_level_1/2/3`、`trailing_sl_offset_atr_level_2/3`）废弃，由新配置替代。

## 4. Configuration

**文件：** `global_config.yaml`

```yaml
guardian:
  # --- Partial Take-Profit ---
  partial_tp:
    level_1_atr_threshold: 1.5   # 浮盈 ATR 阈值，触发首次分批止盈
    level_1_tp_ratio: 0.5        # 止盈净仓位的比例 (0.0–1.0)

  # --- Dynamic Trailing Stop ---
  trailing:
    sl_distance_atr: 1.5         # SL 尾随价格的距离(ATR)

  # --- Time-Based Stop (保留) ---
  time_stop:
    time_stop_multiplier: 1.5
```

## 5. Key Design Decisions

### 5.1 为什么用 `api.SL >= api.entry` 做幂等判断？

SL 移到 entry 是 Level 1 TP 的标志。TP 后 SL 恰好等于 entry。下次 Pulse 用 `>=`（非严格不等）判断，确保不再触发。SHORT 方向用 `<=`。

### 5.2 为什么后续用 SL 自身而非 entry 做基准？

Level 1 之后仓位只剩 50%，entry 对剩余仓位的意义减半。SL 自身成为最佳锚点——`max(api.SL, price - N×ATR)` 天然保证只进不退，且不依赖任何历史值。

### 5.3 为什么用 macro (1h) ATR 而非 micro (15min)？

Level 1 触发和尾随距离都是结构性判断——价格是否真正脱离了入场区。1h ATR 反映日内真实振幅，15min ATR 噪音过大。

### 5.4 为什么 TP 比例选 50%？

一半落袋、一半奔跑。首次实现中设为可配置参数，后续可根据实际表现调整。

## 6. Scope

### In Scope

- `margin_client.py`: 新增 `get_avg_entry_price(symbol, net_qty)`（FIFO + 缓存）
- `order_executor.py`: 
  - 新增 `_try_partial_tp()` — Step 2
  - 新增 `_migrate_dynamic_sl()` — Step 3
  - 修改 `guardian_check()` — 接入新流程，移除旧三级迁移
  - `_optimize_same_direction`: 成功保护后补充 trade_state 写入（顺手修）
- `guardian_check()`: 当 trade_state 为空但有仓位+OCO 时，从交易所重建基础 trade_state（修复重启后裸仓缺口）
- `global_config.yaml`: 新增 `partial_tp` 段、`trailing.sl_distance_atr`，废弃旧三级配置
- `tests/system/test_order_executor.py`: 新增测试

### Out of Scope

- Audit 盈亏计算对齐（用户明确排除）
- OTOCO 入口单改造
- 时间止损修改

## 7. Risk Mitigation

| 风险 | 缓解 |
|------|------|
| `myTrades` 500 笔不够覆盖仓位 | fromId 翻页 |
| FIFO 计算偏差（部分成交） | 用 executed_qty 而非 orig_qty |
| 重启后 trade_state 为空, 裸仓不受保护 | guardian_check Step 1 从交易所重建 |
| 市价止盈滑点 | 市价单由 exchange 最优撮合，滑点缓冲已覆盖 OCO 限价 |
| `_optimize_same_direction` 不写 trade_state | 顺手补写 |

## 8. Test Scenarios

| # | 场景 | 预期 |
|---|------|------|
| 1 | LONG, 浮盈 = 1.5 ATR, SL < entry | TP 50%, SL = entry, 新 OCO 覆盖 50% qty |
| 2 | LONG, SL 已 = entry (TP 后) | 跳过 TP, 进入动态尾随 |
| 3 | LONG, 重启, SL = entry | entry 从 myTrades 恢复, 跳过 TP, 尾随正常 |
| 4 | LONG, 手动补仓, 重挂 OCO | entry 重算, 重新判断, 自动适应 |
| 5 | LONG, price 远超 SL, trailing 推进 | SL = price - 1.5 ATR, OCO 更新 |
| 6 | SHORT, 浮盈 = 1.5 ATR, SL > entry | TP 50%, SL = entry |
| 7 | SHORT, 重启, SL 已 trailing | 跳过 TP, 尾随正常 |
| 8 | OCO 重挂失败 | 紧急市价平仓 |
| 9 | 取消失败 | 旧 OCO 保留, 中止本次迁移 |
| 10 | 时间止损触发 | 不管 TP/尾随状态, 直接市价平仓 |

## 9. Files Changed

| 文件 | 改动 |
|------|------|
| `src/infrastructure/binance/margin_client.py` | 新增 `get_avg_entry_price()` + 缓存 |
| `src/agent/order_executor.py` | 新增 `_try_partial_tp()`, `_migrate_dynamic_sl()`, 改 `guardian_check()`, 移除 `_migrate_trailing_stop`, 补 `_optimize_same_direction` |
| `config/global_config.yaml` | 新增 `partial_tp`, `trailing.sl_distance_atr`, 废弃旧三级 |
| `tests/system/test_order_executor.py` | 新增 10 个测试场景 |
