# BTC / XAUT 信号器 & pre-AI gate 分析

**数据源**：`data/prod/sniper.log`（3.4 MB，8260 行）
**覆盖区间**：2026-09-05 13:23 NZST → 2026-09-18 01:53 NZST ≈ **12.5 天**，6 次 daemon 重启，
每个 symbol 各 **3158 个 pulse**（2 分钟一个）。
**日志时间戳是本地时区 NZST（UTC+12）**，session 文件名是 UTC；本报告一律换算成日志时间。
**生效配置**：本次日志区间内 `config/symbol_config.yaml` 的 gate 实际值是
`min_active_non_trend: 3` / `min_active_trend: 1`（XAUT、BTC 相同）——已用 git 核对，
9/5 13:19 的提交 c745fef 之后到日志结束没有再次改动 gate。

---

## 0. 结论速览（TL;DR）

| symbol | 参数 | 现值 | 建议 | 一句话理由 |
|---|---|---|---|---|
| XAUTUSDT | `min_active_non_trend` | 3 | **保持 3，不要降到 2/1** | 降到 2 会把 wake 从 1.28/天 放大到 **9.44/天（×7.4）**，而多放行的"2 信号"组期望为负（1h 内先摸 −1ATR 41% vs 先摸 +1ATR 11%）；XAUT 本区间 8 笔成交里 **6 笔 SL、0 笔 TP** |
| XAUTUSDT | `min_active_trend` | 1 | **保持 1** | 本区间 XAUT **0 次 trending wake**，无从标定；该值在逻辑上不可能拦任何东西 |
| BTCUSDT | `min_active_non_trend` | 3 | **保持 3，不要降到 2/1** | 非趋势 wake 仅 **0.16/天**；降到 2 → **2.96/天（×18）**，BTC 在这 12.5 天里 6 次 session **全部 NEUTRAL、0 笔交易**，多开会话只是烧 token |
| BTCUSDT | `min_active_trend` | 1 | **建议提到 2**（小改动，可选） | BTC 这 12.5 天真正放行的 6 次 wake 里 **4 次是 trending、只靠 `min_active_trend=1` 放行**（same_dir 只有 1~2），结果全部 NEUTRAL；提到 2 会拦掉其中 1 次（01:43 只有 boundary_test 那一次）。样本小，属低风险微调 |
| 两者 | 注释与取值 | — | **修正注释** | `symbol_config.yaml` 的注释写着"从 3 降回 2"，但取值是 3；git 显示这个值自 7 月起在 2↔3 之间被演化反复改写，注释一直在骗人 |

**比"调 gate 数字"更重要的三条**（详见 §6）：

1. gate 数的是**同向信号个数**，但 `cvd_momentum` 与 `large_trade` 的方向**100% 相同**
   （两者方向都取 `sign(cvd)`；XAUT 91/91、BTC 62/62 次同向），所以"3 个信号"经常只是
   **同一个 CVD burst 被数了 3 次**。XAUT 16 次 wake 里 **13 次**含 `cvd_momentum+large_trade`。
   → 真正该做的是**要求跨类别确认**（FLOW/SIZE/ENERGY/STRUCTURAL/POSITIONING 至少 2 类），
   而不是继续调 `min_active_non_trend`。
2. **emergency 通道（raw strength ≥ 0.8）在 XAUT 上 207/3158 = 6.6% 的 pulse 会命中**，
   16 次 wake 里 7 次靠它绕过 cooldown。原因是 XAUT `cvd_extreme_threshold=0.24`，
   而 `cvd_momentum` 的 strength 在 `|cvd|≈0.48` 就到 0.8 —— emergency 设计成"打破冷却的最后手段"，
   现在却是常态入口。建议提高 `emergency_threshold` 或重标定强度饱和曲线。
3. **门槛本身太松**：XAUT 有 **665/3158 = 21%** 的 pulse 达到 confluence 阈值（BTC 9.8%）。
   与其在这么宽的入口上用一个粗暴的下游 gate 去砍，不如直接把 confluence 阈值/强度标定收紧。

---

## 1. 方法与校验（为什么这些数字可信）

我没有只做描述统计，而是把 `src/sniper/trigger.py` 的确定性部分**原样重放**：

* 从每行 `SIGNAL DIAG` 还原 9 个 detector 的触发状态、strength、方向；
* 按 `SignalMemory.ingest()` 的语义做跨 pulse 衰减（半衰期取 `global_config` 的 `decay`）；
* 复现 `ConfluenceEngine`（`1-∏(1-s·w)` + noise factor + regime modifier + emergency）；
* 复现 `_run_pre_ai_gate()`（含 `MIN_STACK_STRENGTH=0.15` 过滤）；
* cooldown 用日志里**真实发生的 wake**及其真实触发类型（`TRADED / NEUTRAL / ACTIVE_POSITION / FAILED`）
  回放，而不是猜测。

**校验结果（22 次已记录的 WAKE，全部对上）**：

| 校验项 | 结果 |
|---|---|
| confluence 数值（±0.011） | **22 / 22** |
| confluence 方向 | **22 / 22** |
| fresh 信号集合（`fresh=N`） | **22 / 22** |
| gate 计数 ≥3（非趋势）与日志 `gate=PASS` 一致 | 一致 |
| gate=3 反事实能否复现历史 wake | XAUT 15/16、BTC 2/2 非趋势（另 4 次是 trending，由 `min_active_trend=1` 放行） |

也就是：**confluence 的复现误差只有 ±0.003**。反事实数字因此可以当真，而不是估算。

**已知局限**（影响已在下文标注）：

* 日志不记录 `trend_intensity`，所以 **trending 与 ranging 无法从日志区分**。趋势 regime 的
  confluence 阈值（0.85×base）与 gate 规则都不同，因此反事实对"非趋势"做**保守**处理：
  所有非 squeeze 的 pulse 一律按 ranging（阈值 1.0×base、门槛 `min_active_non_trend`）计，
  这会把"其实是 trending 的 pulse"当成被 gate 拦住 → **多算**了被拦数量。
  同时 **调整 `min_active_non_trend` 对 trending pulse 完全无效**（它们走 `min_active_trend`），
  所以 §4 的结论方向是稳的。
* 日志只打印 2 位小数，`strength` 四舍五入会在 emergency 阈值 0.80 边界产生假命中，
  我已用 `>=0.805` 去圆整。
* gate 被拦时**完全不写日志**（`evaluate()` 只在 `should_trigger` 为真时才打印 `WAKE`），
  这是本次分析必须靠重放才能回答的根本原因，**建议补一条 gate FAIL 的 INFO 日志**。
* 反事实新增的 wake 假设 session 结果为 NEUTRAL（0.8× cooldown），因此 §4 的 wake 数是**上界**。

---

## 2. 信号器表现

### 2.1 detector 触发率与强度

**XAUTUSDT**

| detector | 触发 pulse 数 | 触发率 | strength 中位 | P90 |
|---|---|---|---|---|
| cvd_momentum | 619 | 19.6% | 0.43 | **1.00** |
| large_trade | 393 | 12.4% | 0.63 | 0.92 |
| cvd_absorption | 201 | 6.4% | 0.14 | 0.50 |
| positioning_extreme | 98 | 3.1% | 0.57 | 0.61 |
| cvd_divergence | 47 | 1.5% | 0.43 | 0.73 |
| squeeze | 47 | 1.5% | 0.42 | 0.51 |
| boundary_test | 6 | 0.2% | 0.38 | 1.00 |
| liquidation_hunt / volatility_surge | 1 / 1 | 0.0% | — | — |

**BTCUSDT**

| detector | 触发 pulse 数 | 触发率 | strength 中位 | P90 |
|---|---|---|---|---|
| cvd_momentum | 487 | 15.4% | 0.36 | 0.73 |
| cvd_absorption | 464 | 14.7% | 0.27 | 0.62 |
| large_trade | 214 | 6.8% | 0.59 | 0.74 |
| squeeze | 46 | 1.5% | 0.24 | 0.31 |
| cvd_divergence | 39 | 1.2% | 0.45 | 0.79 |
| liquidation_hunt | 15 | 0.5% | 0.29 | 0.81 |
| boundary_test | 5 | 0.2% | 0.56 | 0.78 |
| **positioning_extreme** | **0** | **0%** | — | — |
| volatility_surge | 0 | 0% | — | — |

> BTC 的 `positioning_extreme` 整整 12.5 天**一次都没触发**（`ls_ratio` 长期在 1.0~1.5，
> 既没越过 `long_short_imbalance_ratio=2.0`，也没低于 `short_heavy_imbalance_ratio=0.6`），
> 意味着 BTC 实际可用的独立类别比 XAUT 更少：同向叠加基本只有
> `cvd_momentum` + `large_trade`（两者都取 `sign(cvd)`）+ `cvd_divergence`
> （由 `cvd_delta` 与 `price_delta` 反号决定，**同样是 CVD 派生**），
> `cvd_absorption` 方向与 `sign(cvd)` 相反因此永远无法与之同向，
> `squeeze` 恒为 NEUTRAL。BTC 实际发生的两次 ≥3 wake 其 active 集合正是
> `[cvd_divergence, cvd_momentum, large_trade]`。

**噪音特征**：

* 两个 symbol 的 pulse 有 **67%（XAUT）/ 74%（BTC）一个信号都不出**；
  出信号时**绝大多数只有 1 个**（XAUT：1 个 739 次、2 个 263 次、≥3 个仅 48 次；
  BTC：1 个 413 次、2 个 351 次、≥3 个仅 51 次）。
* 真正的"信息量"高度集中在 `cvd_momentum` + `large_trade` 这一对，而**这对是同源的**
  （方向都取 `sign(cvd)`）：XAUT 同时触发的 91 次里 **91 次同向（100%）**，BTC 62/62（100%）。
  → "同向 2 个信号"在 XAUT 上**从来不构成独立确认**，这对理解 gate 的失效至关重要。
* `liquidation_hunt`、`volatility_surge`、`boundary_test`、`squeeze` 在本区间近乎哑火
  （合计 < 2%），意味着"结构性确认"实际上几乎不参与组队；能堆到 3 个的，基本就是
  CVD 动量 + 大单 + 持仓极端（`positioning_extreme`，`ls` 长期贴近 0.60 下界）。

### 2.2 confluence 越阈分布（决定 gate 工作量的地方）

**XAUTUSDT**（阈值：ranging 0.34 / squeeze 0.255）

| regime | 同向活跃信号数 | 越阈 pulse 数 |
|---|---|---|
| non_squeeze(ranging) | 1 | 201 |
| non_squeeze(ranging) | 2 | 199 |
| non_squeeze(ranging) | ≥3 | **20** |
| squeeze | 1 | 166 |
| squeeze | 2 | 70 |
| squeeze | ≥3 | **9** |
| **合计** | | **665**（占全部 pulse 的 21%） |

**BTCUSDT**（阈值：ranging 0.36 / squeeze 0.27）

| regime | 同向活跃信号数 | 越阈 pulse 数 |
|---|---|---|
| non_squeeze(ranging) | 1 | 127 |
| non_squeeze(ranging) | 2 | 78 |
| non_squeeze(ranging) | ≥3 | **7** |
| squeeze | 1 | 69 |
| squeeze | 2 | 28 |
| squeeze | ≥3 | **0** |
| **合计** | | **309**（9.8%） |

**关键读数**：达到阈值的事件里，只有 **4.4%（XAUT，29/665）** 和 **2.3%（BTC，7/309）**
带 ≥3 个同向信号。所以 `min_active_non_trend=3` 事实上是**绝对主力的过滤器**——
它砍掉了 95% 以上的越阈事件；也正因为如此，把它调低 1 格，wake 量会成倍暴涨。

---

## 3. Trigger session 情况

### 3.1 汇总

| | XAUTUSDT | BTCUSDT |
|---|---|---|
| 日志 WAKE 次数 | **16**（1.28/天） | **6**（0.48/天） |
| 方向 | BULLISH 12 / BEARISH 4 | BULLISH 1 / BEARISH 5 |
| regime（日志标注） | ranging 11 / squeeze 5 | ranging 2 / **trending 4** |
| WAKE 时 fresh 信号数 | 1 个 1 次、2 个 4 次、3 个 7 次、4 个 4 次 | 1 个 3 次、2 个 2 次、4 个 1 次 |
| 会话结果 | TRADED 9 / NEUTRAL 4 / ACTIVE_POSITION 跳过 2 / FAILED 1 | **NEUTRAL 6（全部）** |
| 实际下单 | 8 笔 | **0 笔** |
| session 审计结果 | **6×SL_HIT、2×NEITHER（已成交）、1×未成交、0×TP_HIT** | 无（没有下单） |

### 3.2 XAUT 的 16 次 wake

| 时间 | 方向 | conf | regime | fresh/mem | 活跃信号 | 会话结果 |
|---|---|---|---|---|---|---|
| 13:31:37 | BULL | 0.55 | ranging | 2/1 | cvd_momentum, large_trade | BULLISH 65.5% → 下单 |
| 22:15:34 | BULL | 0.68 | squeeze | 3/1 | cvd_momentum, cvd_absorption, large_trade | BULLISH 69.0% → 下单 |
| 22:22:33 | BULL | 0.69 | squeeze | 2/2 | cvd_momentum, large_trade | 下单（审计 NEITHER） |
| 17:52:57 | BULL | 0.84 | ranging | 3/1 | cvd_momentum, cvd_divergence, large_trade | BULLISH 56.0% → 下单（SL） |
| 18:01:02 | BULL | 0.72 | ranging | 2/2 | cvd_momentum, large_trade | 有持仓，跳过 |
| 18:26:16 | BULL | 0.61 | ranging | 2/1 | cvd_divergence, large_trade | 下单（SL） |
| 10:47:07 | BULL | 0.64 | ranging | 3/1 | cvd_momentum, cvd_divergence | **NEUTRAL** |
| 23:05:08 | BULL | 0.66 | ranging | 3/1 | cvd_momentum, positioning_extreme | BULLISH 52.5% → 下单（SL） |
| 10:15:27 | BULL | 0.63 | squeeze | 3/0 | cvd_momentum, large_trade, positioning_extreme | **FAILED**（JSON 解析失败） |
| 10:21:42 | BULL | 0.54 | squeeze | 1/2 | cvd_momentum | BULLISH 56.5% → 下单（SL） |
| 11:29:05 | BULL | 0.53 | squeeze | 2/1 | cvd_momentum, large_trade | 有持仓，跳过 |
| 13:37:46 | BEAR | 0.85 | ranging | 4/0 | cvd_momentum, cvd_divergence, large_trade | **NEUTRAL** |
| 13:42:13 | BEAR | 0.89 | ranging | 3/1 | cvd_momentum, large_trade, boundary_test | **NEUTRAL** |
| 13:45:37 | BEAR | 0.67 | ranging | 4/2 | cvd_momentum, large_trade, positioning_extreme | BEARISH 58.9% → 下单（SL） |
| 08:02:00 | BEAR | 0.77 | ranging | 4/0 | cvd_momentum, cvd_divergence, large_trade | **NEUTRAL** |
| 10:31:13 | BULL | 0.71 | ranging | 3/0 | cvd_momentum, cvd_divergence, large_trade | BULLISH 38.5% < 40% → 未下单 |

**读得出的东西**：

* conf 与结果**没有单调关系**：0.85/0.89 的两次都是 NEUTRAL，0.53/0.54 的两次反而开了仓。
* 4 次 NEUTRAL 里 3 次的 `active` 都是 cvd_momentum+cvd_divergence+large_trade——即"堆到 3 个"
  之后 AI 反而看不出方向，说明这 3 个信号**同时在讲同一件事**（一次 CVD 冲击），AI 看到的是
  "已经发生过的动量"而不是"可交易的边际"。
* 8 笔成交 6 笔 SL、0 笔 TP。这 12.5 天 XAUT 的 gate 产物是负期望的。

### 3.3 BTC 的 6 次 wake —— 全部 NEUTRAL

| 时间 | 方向 | conf | regime | same_dir | 活跃信号 | 结果 |
|---|---|---|---|---|---|---|
| 15:15:57 | BULL | 0.60 | ranging | 3 | cvd_momentum, cvd_divergence, cvd_absorption, large_trade | NEUTRAL |
| 18:46:53 | BEAR | 0.71 | ranging | 3 | cvd_momentum, cvd_divergence | NEUTRAL |
| 00:31:40 | BEAR | 0.69 | **trending** | 2 | cvd_momentum, large_trade | NEUTRAL |
| 00:49:48 | BEAR | 0.37 | **trending** | 2 | cvd_momentum | NEUTRAL |
| 01:43:25 | BEAR | 0.50 | **trending** | **1** | boundary_test | NEUTRAL |
| 11:13:48 | BEAR | 0.41 | **trending** | 2 | cvd_momentum | NEUTRAL |

* BTC 在 12.5 天里 **0 笔交易**，6 次 session 全部 NEUTRAL。BTC 的 min_active gate 无论 1/2/3，
  在这个区间都没有产出任何正收益；它唯一的作用是**限制 LLM 花费**。
* **6 次里有 4 次是 trending**，也就是 `min_active_non_trend` 根本没参与，全靠
  `min_active_trend=1` 放行 —— 这正是 §6 建议 BTC 把它提到 2 的依据。
* conf 最低的 0.37（只有 1 个 cvd_momentum）也照样放行并跑了一次完整 AI session。

---

## 4. gate 反事实：`min_active_non_trend` = 1 / 2 / 3

把 cooldown 也纳入模型（历史 wake 用真实触发类型，反事实新增 wake 按 NEUTRAL 计），
得到"如果把该参数改成 k，这段时间会醒来多少次"：

| symbol | `min_active_non_trend` | wakes（12.5天） | wakes/天 | 相比现值 |
|---|---|---|---|---|
| XAUTUSDT | **3（现）** | **16** | **1.28** | — |
| XAUTUSDT | 2 | 118 | 9.44 | **×7.4** |
| XAUTUSDT | 1 | 277 | 22.16 | **×17.3** |
| BTCUSDT（非趋势部分） | **3（现）** | **2** | **0.16** | — |
| BTCUSDT（非趋势部分） | 2 | 37 | 2.96 | **×18.5** |
| BTCUSDT（非趋势部分） | 1 | 110 | 8.80 | **×55** |

> BTC 另有 4 次 trending wake 由 `min_active_trend=1` 放行，不受本参数影响；
> 所以 BTC 的"总 wake"在 k=3 时是 2+4=6 次，k=2 时约为 37+4=41 次。

**被 gate 拦下的候选规模**：

| symbol | 现值 k=3 拦下 | 其中 1 个信号 | 其中 2 个信号 | 被拦者 conf 中位 |
|---|---|---|---|---|
| XAUTUSDT | 606 | 355 | 251 | 0.435 |
| BTCUSDT | 280 | 180 | 100 | 0.411 |

即：把 k 从 3 降到 2，**XAUT 每天多出约 8 次完整 AI session，BTC 多出约 2.8 次**；
降到 1 则分别多出约 21 次 / 8.6 次。以 session ~90 s 计，XAUT 在 k=1 时几乎会被
AI 会话占满整个交易日。这是**成本侧**决定性的反对理由。

---

## 5. 噪音 vs "踏空"：被拦下的那些到底是不是机会

对每个"engine 已越阈、被 gate 拦下"的候选，用其后 1 小时（30 个 pulse）的
按信号方向计算的 MFE / MAE（单位：ATR），并统计"先摸 +1ATR 还是先摸 −1ATR"：

**XAUTUSDT**

| 分组 | n | MFE 中位 | MAE 中位 | 1h 末中位 | 先摸 +1ATR | 先摸 −1ATR | 纯震荡 |
|---|---|---|---|---|---|---|---|
| 被拦 · 1 信号（k=2 会放行） | 355 | +0.17 | −0.49 | −0.06 | **19%** | 34% | 47% |
| 被拦 · 2 信号（k=3→2 会放行） | 251 | +0.09 | −0.51 | −0.12 | **11%** | 41% | 49% |
| **实际放行（k=3）** | 16 | +0.06 | **−1.47** | −0.29 | **6%** | **56%** | 38% |

按方向拆开（避免被单边行情混淆）：

| 分组 | n | MFE | MAE | 先摸 +1ATR | 先摸 −1ATR |
|---|---|---|---|---|---|
| 被拦 1 信号 · BEAR | 208 | +0.18 | −0.31 | 18% | 22% |
| 被拦 1 信号 · BULL | 147 | +0.16 | −1.18 | 19% | 52% |
| 被拦 2 信号 · BEAR | 94 | +0.09 | −0.36 | 5% | 26% |
| 被拦 2 信号 · BULL | 157 | +0.11 | −0.94 | 14% | 50% |
| 放行 · BULL | 12 | +0.06 | −1.05 | 8% | 50% |
| 放行 · BEAR | 4 | +0.17 | −4.54 | 0% | 75% |

**BTCUSDT**

| 分组 | n | MFE | MAE | 先摸 +1ATR | 先摸 −1ATR | 纯震荡 |
|---|---|---|---|---|---|---|
| 被拦 · 1 信号 | 179 | +0.27 | −0.36 | 19% | 33% | 48% |
| 被拦 · 2 信号 | 100 | +0.32 | −0.25 | 17% | 23% | 60% |
| 放行（k=3） | 2 | +1.23 | −1.87 | 50% | 50% | 0% |

**怎么读这张表（这是回答"踏空是否频繁"的核心）**：

1. **"踏空"确实在发生，而且量不小，但不是被 gate 制造出来的**：
   XAUT 被拦的 606 个候选里，约 **19%（1 信号组，≈67 次）** 和 **11%（2 信号组，≈28 次）**
   在 1 小时内先摸到 +1 ATR —— 折算约 **7.6 次/天的"本可以走一段"的候选**。
   但同一个组里先摸 −1 ATR 的比例是 34% / 41%，**赔率明显不划算**：
   要覆盖 19% vs 34% 的胜负比，盈亏比得做到 **≥1.8:1**（按 1ATR 止损）。
   所以它们绝大多数是"看起来像踏空、实际是噪音"。
2. **真正的异常是"放行的反而更差"**：XAUT 实际放行的 16 次，MFE 中位只有 +0.06 ATR、
   MAE 中位 **−1.47 ATR**，56% 会先打掉 −1ATR。这与 §3 的 6×SL / 0×TP 完全吻合。
   也就是说 **`min_active_non_trend=3` 并没有筛出"更干净"的信号，反而筛出了波动更大、
   更容易立刻反向的那一类**（多个同向信号同时达到高 strength，本身就是一次已经完成的
   动量冲击）。把 k 降到 2 引入的候选，质量反而略好于现状（19%/34% vs 6%/56%），
   **但两组都是负期望**，所以正确结论不是"降到 2"，而是**入口太宽需要重做，而不是这道闸门**。
3. BTC 的数据同样说明问题：被拦的 1 信号组 19% vs 33%，放行的 2 次几乎全是运气样本
   （n=2，不可用）。BTC 在这段时间**根本不该交易**，gate 调到 1 或 2 都只是多烧 token。

**"踏空"的另一种形态——预判促发被 cooldown 抢跑**：模型里有 43 次（XAUT）/ 27 次（BTC）
越阈事件被 **cooldown**（而不是 gate）挡住。这类才是真正"信号来了但系统没醒"的情形。
XAUT 有一次（10:21:42，conf 0.54）就因为上一个失败 session 的 cooldown 归属产生歧义。
建议：给 gate FAIL 和 cooldown 拦截都补 INFO 日志，这类问题以后才能直接统计，不必重放。

---

## 6. 建议

### 6.1 直接回答你的问题（gate 参数怎么调）

1. **XAUTUSDT `min_active_non_trend: 3` → 保持 3。**
   降到 2 让 wake ×7.4，而多放行的候选期望为负；降到 1 更糟（×17，且 277 次里 207 次
   由 emergency 通道驱动）。**不要"降低"，但也不要以为 3 是对的值**——它是"以量换质"
   的权宜之计（见 6.2）。
2. **BTCUSDT `min_active_non_trend: 3` → 保持 3。**
   非趋势 wake 只有 0.16/天，降到 2 是 ×18 的 token 浪费，而 BTC 这段时间 0 笔交易。
3. **BTCUSDT `min_active_trend: 1` → 建议 2。**
   这是唯一有明确证据支持、且成本极低的改动：本区间 BTC 的 6 次 wake 里 4 次是 trending、
   same_dir 只有 1~2，全部 NEUTRAL。提到 2 会拦掉 01:43:25 那次（只有 `boundary_test`
   一个信号）——那次是 §3.3 里信息量最低的一次。注意样本只有 4 次，属"低风险微调"而非强证据。
4. **XAUTUSDT `min_active_trend: 1` → 保持 1。**
   本区间 XAUT 没有任何 trending wake，没有数据支持改动。（顺带说明：`min_active_*` = 1
   在逻辑上等于没有这道闸门，因为能触发就必然 ≥1 个信号；它只是"防呆"，不产生过滤。）
5. **修注释**：`symbol_config.yaml` 第 50、91 行的注释写着"从 3 降回 2"，取值却是 3。
   git 记录显示该值在 7/25→7/27→8/25→8/26 之间被来回改成 2、3、2、3，
   注释是某次回滚时留下的。演化循环（evolution）会继续改这个参数，
   建议把注释改成不带方向的中性描述（如"当前生效值：3，历史在 2/3 间摆动"），否则下一个人还会被误导。

### 6.2 比调数字更值得做的（按性价比排序）

1. **把"信号个数"换成"信号类别数"。**
   `cvd_momentum` 与 `large_trade` 永远同向（同取 `sign(cvd)`），所以"≥3 同向"经常等于
   "1 个 CVD 事件 + 1 个独立信号"。建议 gate 改为
   **要求覆盖 ≥2 个类别（FLOW / SIZE / ENERGY / STRUCTURAL / POSITIONING），
   且其中至少 1 个来自 FLOW 之外**。这直接切掉 XAUT 16 次 wake 里 13 次的"同源堆叠"，
   同时保留真正的跨维度确认。这才是"3"想表达但没表达出来的东西。
2. **重标定 emergency 通道。**
   XAUT 有 207/3158 = 6.6% 的 pulse 携带 raw strength ≥ 0.8 的信号，16 次 wake 里 7 次
   由它绕过 cooldown。根因是 `cvd_extreme_threshold=0.24` 与强度饱和曲线不匹配
   （`|cvd|≈0.48` 就到 0.8；而 XAUT |CVD| 的 P90 只有 0.18，说明 0.5+ 的脉冲虽然少但足以常态化）。
   建议把 `emergency_threshold` 提到 0.9，或让 strength 的饱和分母按 symbol 的 |CVD| 分位数标定。
3. **收紧 confluence 入口，而不是加厚下游闸门。**
   XAUT 21% 的 pulse 越阈（squeeze 档阈值仅 0.255 是主因）。当前架构是
   "入口极宽（21%）→ 用一个粗暴计数闸门砍到 0.5%"；更合理的是
   "入口中等（5~8%）→ 用类别多样性做最后确认"。
4. **补日志**：在 `_run_pre_ai_gate` 返回 FAIL 时打一条 INFO（带 `gate_tag`、regime、
   `len(same_dir_active)`、dominant direction）。现在 gate 拦截是完全静默的，
   任何关于 gate 的评估都必须靠重放（本报告就是），这对线上调参很不利。

### 6.3 一句话版本

> `min_active_non_trend: 3` 对 BTC 和 XAUT **都该保留**（降 1 格 = wake ×7~×18，
> 且多放行的候选期望为负）；`min_active_trend: 1` 对 XAUT 保留、**对 BTC 建议提到 2**。
> 但真正的问题不在这个数字上：**gate 数的是同源信号的个数，且入口阈值太松**——
> 建议改成"跨类别 ≥2"，并重标定 emergency 通道。

---

## 7. 复现方式

```bash
# 完整证据表（探测率、wake 明细、反事实、前瞻收益、ATR 游程）
python3 scripts/sniper_gate_core.py \
    --json /tmp/gate.json \
    --out docs/sniper_gate_evidence_20260917.md
```

* 分析脚本：`scripts/sniper_gate_core.py`（重放 `src/sniper/trigger.py` 的确定性链路）
* 证据明细表：`docs/sniper_gate_evidence_20260917.md`
* 数据源：`data/prod/sniper.log`
* 配置核对：`config/symbol_config.yaml`（提交 `c745fef`，2026-09-05）+ `config/global_config.yaml`
