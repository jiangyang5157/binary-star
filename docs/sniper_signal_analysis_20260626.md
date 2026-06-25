# Sniper 信号敏感度与质量分析报告

**分析周期**: 2026-06-25 22:30 — 2026-06-26 09:24 (约 11 小时)  
**监控标的**: BTCUSDT, XAUTUSDT  
**数据源**: `data/prod/sniper.log` (1378 行), `data/prod/session.log` (618 行), `data/prod/sessions/*.json` (19 个 session)

---

## 1. 总览

| 指标 | 数值 |
|------|------|
| 总脉冲次数 | 547 (约每 2 分钟一次) |
| 触发次数 (SNIPER WAKE UP) | **11 次** |
| 触发率 | 2.0% |
| AI Session 启动次数 | **10 次** (1 次被 active position 跳过) |
| 实际执行交易 | **8 次** (2 次 NEUTRAL 放弃) |
| 触发→执行转化率 | **72.7%** |
| 总 Token 消耗 | 1,714,338 tokens (81 次 AI 调用) |
| 平均每次 AI 调用 | 21,165 tokens |

---

## 2. 信号触发明细

| # | 时间 | 标的 | 方向 | Confluence | 信号数 | 活跃信号 | Regime | Gate |
|---|------|------|------|------------|--------|----------|--------|------|
| 1 | 22:30 | XAUT | BULLISH | 0.53 | 3 | cvd_momentum, retail_extreme | squeeze | PASS |
| 2 | 22:47 | BTC | BEARISH | 0.38 | 1 | cvd_momentum | ranging | PASS |
| 3 | 23:09 | BTC | BEARISH | 0.42 | 2 | cvd_momentum, retail_extreme | ranging | PASS |
| 4 | 00:17 | XAUT | BULLISH | 0.27 | 2 | cvd_momentum | squeeze | PASS |
| 5 | 01:45 | BTC | BEARISH | 0.47 | 2 | liquidation_hunt, oi_divergence | ranging | PASS |
| 6 | 02:33 | BTC | BULLISH | 0.37 | 1 | liquidation_hunt | ranging | PASS |
| 7 | 03:23 | XAUT | BULLISH | 0.43 | 1 | (空) | squeeze | PASS |
| 8 | 04:00 | XAUT | BULLISH | **0.68** | 5 | cvd_momentum, cvd_divergence, cvd_absorption, taker_imbalance, oi_divergence | squeeze | PASS |
| 9 | 05:16 | XAUT | BULLISH | 0.53 | 2 | cvd_momentum | ranging | PASS |
| 10 | 06:08 | XAUT | BULLISH | 0.41 | 2 | cvd_absorption, taker_imbalance | ranging | PASS |
| 11 | 08:57 | XAUT | BULLISH | 0.46 | 2 | cvd_momentum | ranging | PASS |

### 2.1 关键观察

- **方向偏差**: 9/11 (82%) 触发为 BULLISH，市场呈现明显的单边看涨倾向
- **最低 confluence 触发**: 0.27（#4，XAUT squeeze 期间触发，最终 PASS→执行 LONG 85%）
- **最高 confluence 触发**: 0.68（#8，5 信号并发，是最高质量的触发）
- **CVD Momentum 主导**: 出现在 8/11 (73%) 触发中，是最高频的触发信号

---

## 3. Session 辩论质量分析

### 3.1 辩论结果统计

| 结果 | 次数 | 占比 |
|------|------|------|
| R1 直接 PASS | 3 | 30% |
| 经过 CONSTRUCTIVE 修正 → 执行 | 5 | 50% |
| TERMINAL 否决 → NEUTRAL | 2 | 20% |
| **总计有结论** | **10** | **100%** |

### 3.2 辩论轮次分布

| 轮数 | 次数 |
|------|------|
| 1 轮 (PASS) | 3 |
| 2 轮 (CONSTRUCTIVE→执行 或 TERMINAL→放弃) | 7 |

**无冷合成兜底（cold-synthesis）被触发** — 所有 session 均在 2 轮内达成结论。

### 3.3 首轮 Veto 类型分布

| Veto | 次数 | 最终结果 |
|------|------|----------|
| PASS | 3 | 直接执行 |
| CONSTRUCTIVE | 5 | 经修正后全部执行 |
| TERMINAL | 2 | NEUTRAL 放弃 |

**关键发现**: CONSTRUCTIVE 修正后执行率 100% — R2 修正没有导致任何放弃。

---

## 4. 交易执行分析

### 4.1 执行明细

| # | 时间 | 标的 | 方向 | 置信度 | Entry | TP | SL | 等待 | 持仓 |
|---|------|------|------|--------|-------|-----|------|------|------|
| 1 | 22:56 | BTC | SHORT | 72% | 61431.44 | 58898.21 | 63097.66 | 0.6h | 23.2h |
| 2 | 23:20 | BTC | LONG | 80% | 60800.0 | 62201.57 | 59900.0 | 1.1h | 7.9h |
| 3 | 00:19 | XAUT | LONG | 85% | 3960.0 | 4085.0 | 3925.0 | 2.4h | 29.7h |
| 4 | 03:30 | XAUT | LONG | 77% | 4021.0 | 4086.92 | 3975.0 | 0.6h | 14.8h |
| 5 | 04:05 | XAUT | LONG | 90% | 4020.0 | 4049.0 | 4005.0 | 1.5h | 6.7h |
| 6 | 05:24 | XAUT | LONG | 91% | 4017.0 | 4041.5 | 3998.0 | 0.9h | 3.4h |
| 7 | 06:14 | XAUT | LONG | 85% | 4018.0 | 4038.0 | 4006.0 | 0.6h | 4.6h |
| 8 | 08:59 | XAUT | LONG | **100%** | 4017.5 | 4041.71 | 4005.0 | 0.1h | 5.6h |

### 4.2 交易质量观察

- **置信度区间**: 72%-100%，平均 85.0%，中位数 85%
- **SL 距离**: BTC 约 2.7% ATL(#1 SHORT) ~ 1.5%(#2 LONG)；XAUT 约 1.0-1.5%
- **RR 比**: XAUT LONG 典型 TP~4040-4090, SL~3920-4005, RR 范围 0.9:1 到 2.5:1

---

## 5. 🔴 重大问题：BTC ORIENTATION CONFLICT 事件

### 5.1 事件时序

```
22:56:40  BTC SHORT entry 成交 (-0.0024), OCO 保护部署
22:58:41  BTC SHORT 仓位被平仓 (2分钟内!)
23:20:35  Session 决定 BULLISH/LONG (Confidence 80%)
23:20:36  Executor: PIVOT detected (SHORT→LONG)
23:20:36  Pivot-Preserve: 调整SHORT的TP=60800.0, 部署LONG限价单
23:22:37  首次 ORIENTATION CONFLICT: Intent=LONG but NetQty=-0.0024
   ↓
01:39:23  持续100+分钟的 ORIENTATION CONFLICT (每2分钟一次，共50+次)
01:39:23  最终: BTC LONG entry 成交 (0.0044), OCO 保护部署
01:47:46  仓位被平仓 (8分钟后)
```

### 5.2 问题分析

1. **第一个 SHORT 仓位在 2 分钟内就被平仓了** — 分析周期窗口内的这笔交易可能是被止损或者 TP 迅速击中，需要检查 session JSON 确认
2. **PIVOT-PRESERVE 机制导致 100+ 分钟的裸仓状态**: 旧的 SHORT 仓位还开着（NetQty=-0.0024），新的 LONG 限价单未成交。Guardian 每 2 分钟报告 ORIENTATION CONFLICT，拒绝接受这个"手工仓位"的方向，但也没有强制平仓
3. **Guardian 正确拒绝但遗留风险**: 系统不应该让一个已判断为错误的仓位方向持续存在 100+ 分钟

### 5.3 潜在根因

- BTC SHORT 仓在 22:56 成交后，2 分钟内迅速被填充（可能瞬间触及 TP）
- 但 Binance 账户中残留了一个 0.0024 BTC 的 SHORT 仓位（可能来自部分成交、挂单残留、或者是账户中的另一个手动仓位）
- 系统无法自动平掉这个方向冲突的仓位

---

## 6. 信号敏感度分析

### 6.1 信号类型频率

| 信号 | 出现次数 | 占比 |
|------|----------|------|
| cvd_momentum | 8 | 73% |
| retail_extreme | 2 | 18% |
| cvd_absorption | 2 | 18% |
| taker_imbalance | 2 | 18% |
| oi_divergence | 2 | 18% |
| liquidation_hunt | 2 | 18% |
| cvd_divergence | 1 | 9% |

### 6.2 Confluence Score 分布

```
0.27 ██ (XAUT squeeze)
0.37 ██ (BTC ranging)
0.38 ██ (BTC ranging)
0.41 ███ (XAUT ranging)
0.42 ███ (BTC ranging)
0.43 ███ (XAUT squeeze)
0.46 ███ (XAUT ranging)
0.47 ███ (BTC ranging)
0.53 ████ (XAUT squeeze/ranging ×2)
0.68 █████ (XAUT squeeze, 5 signals)
```

- 最低值 0.27 依然触发 → 敏感度高
- 大部分(8/11) in 0.37-0.53 区间
- 仅一次 >0.6 的高质量多信号触发

### 6.3 Regime 对触发的影响

| Regime | 触发次数 | 占比 | 冷却时间 |
|--------|---------|------|---------|
| RANGING | 7 | 64% | 45 分钟 |
| SQUEEZE | 4 | 36% | 25 分钟 |

SQUEEZE 期间冷却更短（25m vs 45m），触发更密集。

---

## 7. ENTRY_FEASIBILITY Gate 拦截分析

- 总拦截次数: **33 次**
- 全部发生在 XAUTUSDT
- 典型拦截消息: `nearest structure at 6.0-7.9 ATR > 2.0`
- 说明: XAUT 价格在大多数时间内远离结构锚点（HVN/LVN），gate 正确阻止了不合适入场

**这是 gate 正常工作的信号** — 它在防止不良入场几何结构方面发挥了作用。

---

## 8. Confluence 与置信度相关性

| Trigger Confluence | Session Confidence | Result |
|-------------------|-------------------|--------|
| 0.53 | NEUTRAL (0%) | 首轮 TERMINAL 否决 |
| 0.38 | 72% | 执行 SHORT |
| 0.42 | 80% | 执行 LONG |
| 0.27 | 85% | 执行 LONG ⚠️ |
| 0.37 | NEUTRAL (0%) | 两轮 TERMINAL |
| 0.43 | 77% | 执行 LONG |
| 0.68 | 90% | 执行 LONG |
| 0.53 | 91% | 执行 LONG |
| 0.41 | 85% | 执行 LONG |
| 0.46 | **100%** | 执行 LONG |

### 8.1 关键发现

- **Confluence 与 Confidence 弱相关**: 0.27 的 confluence 产生了 85% 的置信度，而 0.53 的 confluence 反而 NEUTRAL
- **Confluence ≠ Session 最终质量**: AI 辩论层完全覆盖了信号层。一个弱的 confluence 信号可以通过 AI 推理变成高置信度执行，一个强的 confluence 可以被 Critic 否决
- **Confluence 0.68 的最高信号** 产生了 90% 的置信度（不是最高置信度）
- **100% 置信度的 session** confluence 仅 0.46，但 R1 直接 PASS — AI 对自己的判断非常确定

---

## 9. 信号质量评分

### 9.1 误报风险

| 风险评估 | 等级 | 说明 |
|----------|------|------|
| 假阳性（不该触发但触发了） | **中低** | 11 次触发中 2 次 NEUTRAL (18%) — AI 层有效过滤 |
| 假阴性（该触发但未触发） | **未知** | 无法从日志判定错过的好交易机会 |
| 信号单薄触发 | **中** | 4/11 (36%) 触发仅 1-2 信号，confluence 低至 0.27 |

### 9.2 信号多样性

| 指标 | 数值 |
|------|------|
| 总独特信号数 | 7 种 (来自 14 种可能) |
| CVD 系列信号占比 | 73% (cvd_momentum + cvd_divergence + cvd_absorption) |
| 从未触发的信号 | 7 种 (50% 信号从未被触发) |

**问题**: 50% 的信号从未出现在任何触发中。需要检查是否：
- 这些信号的条件过于严苛
- 当前市场环境不适合这些信号
- 信号检测器存在 bug（审计报告 D3-F6：detector failure at DEBUG level）

---

## 10. 建议与改进

### 10.1 高优先级

1. **修复 ORIENTATION CONFLICT 死锁** (详见上文 §5): PIVOT-PRESERVE 后应该加入 timeout——如果 X 分钟内新方向限价单未成交，要么取消、要么强制平掉冲突仓位。目前 100+ 分钟的裸仓状态不可接受。

2. **Gate 敏感度校准**: 33 次 ENTRY_FEASIBILITY 拦截说明 XAUT 的结构距离 gate 可能过紧。考虑将 `max_price_to_structure_atr` 从 2.0 放宽到 3.0-4.0（或按 regime 动态调整）。

3. **未触发信号审计**: 检查 7 个从未触发的信号检测器是否正常工作（审计报告已指出 DEBUG 级别日志可能隐藏了 detector 失败）。

### 10.2 中优先级

4. **Confluence 下限考虑**: 是否应设置 minimum confluence threshold（如 0.30）来过滤单薄信号？0.27 的触发虽然最终执行了，但质量存疑。

5. **XAUT 信号质量退化观察**: 03:30→06:14 期间 XAUT 连续 4 次触发，每次的 TP 越来越近（4087→4049→4042→4038），SL 越来越紧（3975→4005→3998→4006）。这反映了价格在收窄区间内运行，每次"优化"只是微调。

### 10.3 低优先级

6. **CVD 系列信号降权考虑**: CVD 信号占据了 73% 的触发，可能导致 confluence 过度依赖单一信号族。考虑对 CVD 类信号施加 correlation penalty。

7. **Confluence 冷合成暴露**: 本轮没有触发 cold-synthesis（max_rounds 耗尽），但审计报告已指出 cold-synthesis 失败路径的代码保护不足。

---

## 11. 总结

**信号系统总体健康**，但存在以下核心问题：

- ✅ AI 辩论层有效（CONSTRUCTIVE→执行率 100%，TERMINAL 正确拦截了 20% 的触发）
- ✅ Gate 系统正常工作（33 次 ENTRY_FEASIBILITY 正确拦截）
- ✅ Guardian 在大多数情况下正确保护仓位
- ⚠️ PIVOT + ORIENTATION CONFLICT 暴露了多腿仓位管理的设计缺陷
- ⚠️ 50% 信号从未触发，需排查 detector 健康状态
- ⚠️ Confluence 与最终置信度相关性弱，信号层和 AI 层之间的信息传递可能需要改善

*报告生成时间: 2026-06-26*
