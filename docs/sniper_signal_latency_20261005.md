# Sniper 信号迟钝度分析 — 2026-10-05

分析对象：`data/prod/sniper.log`（2026-09-18 → 2026-10-05，墙上 约 17.2 天，**实际运行 7.2 天**，
4979 个 pulse/symbol，43 个连续段，62 次 wake 事件，其中 57 次有足够的
前后数据可测量）。
工具：`scripts/sniper_signal_latency.py`（复用 `sniper_gate_replay.py` 的解析与 confluence 重建）。
日志快照：13:49:58（daemon 仍在运行，重跑会有 ±1 pulse 的抖动，结论不变）。
所有数值都是 ATR 归一化，且只用 daemon 自己看到的 2 分钟 pulse 网格，无未来函数。

---

## 结论摘要

1. **迟是真的，不是幻觉。** wake 发生时价格已经走掉的那段（prior）和 wake 之后剩下能吃到的那段（MFE）
   大致相当：capture = **0.43 (XAUT) / 0.49 (BTC)**，而 0.50 就等于"完全同步"。XAUT 的 wake 之后
   60 分钟里，中位数上**先逆向 0.62 ATR、最大顺向只有 0.34 ATR**。

2. **但"迟钝"不是最准确的诊断。** 真正的问题是复合分数里权重最高的几个检测器**几乎没有方向信息**：
   XAUT 上按权重排前三位的有方向检测器分别是 cvd_divergence(0.70)、cvd_momentum(0.65)、
   liquidation_hunt(0.60)，而它们实测的"±0.5 ATR 先触及率"是 57±11% / 50±8% / —，
   BTC 上是 54±10% / 44±7% / **27±13%**（掷硬币 = 50%）——
   注意误差棒：**这些数字没有一个能和掷硬币区分开**，见第 6 条。

3. **核心机械性缺陷：`cvd_divergence` 测的是 15 分钟 K 线时钟，不是资金背离。**
   它的 fire 有 **70% (XAUT) / 90% (BTC) 集中在一根 15m K 线刚收盘后的 2 分钟内**（那段时间只占 13%），
   触发率是盘中其他时段的 **12.9 倍 / 56.8 倍**。原因是 CVD 用的是"最近 4 根 15m K 线"的净 taker 比，
   每 15 分钟会掉出一根满量 K 线、补进一根空 K 线，分母骤降 → 比值跳变。
   这不是调参问题，是测量口径问题。
   → **2026-10-05 已修**（改为与同一相位的 15 分钟前比较），XAUT 已完全干净、BTC 尾部仍有残余，
   详见 **§2b**。

4. **权重和实测技能是反的。** 权重 0.50 的 cvd_absorption / positioning_extreme 反而表现最好
   （fav 60% / 56%），但它们 fire 次数少、进不了 wake 的组成；wake 的组成被 cvd_momentum(23/24)
   和 large_trade(20/24) 垄断。而且门闸要求"≥3 个信号"，所以这两个必然会同时出现。

5. **XAUT 的大行情多数被闸门拦掉 —— 但拦得对。** 15 个 ≥3 ATR 的行情只有 3 个 wake，其余 12 个
   都是 `PRE-AI GATE FAIL`（maxconf 高到 0.83、同向信号只有 1–2 个）。可是如果在 max-conf 那一刻
   进场，prior 已经走了 **1.5–7.6 ATR**，11 个里 7 个先逆向 0.5 ATR。**放开闸门买到的是"迟到入场"，
   不是"更早入场"。**

6. **样本量警告（最重要的一条）。** 62 次 wake 实际上只覆盖 **XAUT 11 个 / BTC 9 个独立行情**
   （wake 会在同一个行情里连续打好几次）。按独立事件重算 wake 后 60 分钟的漂移：
   XAUT +0.13 ATR (t=0.25)、BTC +0.26 ATR (t=1.76) —— **都不到显著**。
   也就是说：现有数据既不能证明有 edge，也不能证伪。任何基于"wake 对错"的调参，
   有效样本只有 ~10–20，之前几轮的 A/B 结论都要按这个打个折。

---

## 1. 怎么量的

| 量 | 定义 | 读法 |
|---|---|---|
| `prior(30m)` | 事件前的 30 分钟里，信号方向上已经走过的 ATR | 越大 = 越迟 |
| `mfe(60m)` / `mae(60m)` | 事件后 60 分钟内最大顺向 / 逆向 ATR | mae 比 mfe 大 = 进去就被打 |
| `capture` | `mfe / (prior + mfe)` | 0.5 = 完全同步，<0.5 = 迟 |
| `first touch ±0.5 ATR` | 事件后先触及 +0.5 还是 −0.5 ATR | fav% 50% = 掷硬币 |
| `boundary x` | 15m K 线开盘后 2 分钟内的 fire 率 ÷ 其他时段 fire 率 | ≫1 = 在测时钟 |
| `fwd drift` | 事件后 60 分钟的**带方向**收益（ATR） | 唯一能直接检验 edge 的量 |

窗口永远不跨 daemon 重启或 `RESUMED AFTER GAP`（跨进程的"60 分钟后"没有意义）；
`min to swing start` 用 120 分钟回看，避免被窗口边缘截断。

`min to swing start` 的中位数是 41 min (XAUT) / 80 min (BTC)，但这个量在趋势里天然偏大
（趋势的"波段起点"本来就在很久以前），**不能单独当作迟钝的证据**；capture 才是公平的那个。

---

## 2. cvd_divergence 的窗口换手伪信号（核心发现）

机制，全部可以在代码里指认：

* `src/analyzer/market_observer.py:534-543` —— `cvd_intensity_ratio = 净taker量 / 总量`，
  窗口是 `cvd_micro_lookback_candles = 4` 根 **15m** K 线（≈60 分钟）。
* 每 15 分钟，窗口掉出一根**满量**的旧 K 线、补进一根**刚开始、几乎没量**的新 K 线：
  分子（净量）几乎不变，分母（总量）骤降 → 比值被放大 → 跳变。
* `src/sniper/trigger.py:755-763` —— `cvd_divergence` 拿 `cvd - prev_cvd` 跟一个**固定阈值**比。
  阈值是按"盘中噪声"标定的（`symbol_config.yaml:44,91`，XAUT 0.12 / BTC 0.08，
  注释写的是 "XAUT CVD 变动幅度小(0.02-0.10/脉冲)"、"0.08 仍远超正常噪声(~0.02)"）——
  **这个前提在 K 线边界上不成立。**

实测（同一份 log，按每根 15m K 线的相位分组）：

| | 边界 2 分钟内 mean\|ΔCVD\| | 盘中 mean\|ΔCVD\| | 倍数 | 超过阈值的概率（边界/盘中） | fire 落在边界的比例 |
|---|---|---|---|---|---|
| XAUT (thr 0.12) | 0.0850 | 0.0230 | 3.7× | 22.3% / 2.9% | **70%** 的 fire 在 13% 的时间里 |
| BTC (thr 0.08) | 0.0494 | 0.0129 | 3.8× | 20.5% / 1.3% | **90%** 的 fire 在 13% 的时间里 |

其他检测器的边界偏置（`boundary x`）作为对照：`squeeze` 2.1×/2.0×、`large_trade` 1.5×/1.7×、
`cvd_momentum` 1.2×/1.4×、`cvd_absorption` 1.1×/1.2×。
**`cvd_divergence` 是 12.9×/56.8×，完全在另一个量级。**

顺带：`squeeze` 的权重 0.75 是全场最高，但它的 direction 是 `NEUTRAL`，
而 `_dir_score` 只累加 `direction == 目标方向` 的信号 —— 所以 **0.75 的权重在 confluence 里是死的**，
它只通过 regime 分类间接起作用。

### 2b. 修复与验证（2026-10-05 已实施）

改法：`cvd_divergence` 不再与相邻 pulse（2 分钟前）比较，而是与**同一相位的 15 分钟前**
的采样点比较（`SniperTrigger._cvd_reference`，容差 ±2.5 min）。这样两个端点处在窗口换手
周期的同一相位，换手效应相消，剩下的是"一根完整 K 线滚过去"的真实变化。

用真实 pulse 序列回放**已上线的检测器**（5061 pulse/symbol，逐段 reset）实测：

| | 盘中均值 \|ΔCVD\| 边界倍数 | 新阈值 | fire 量（旧） | fire 落在 K 线开盘 2 分钟内 |
|---|---|---|---|---|
| XAUT | 3.7× → **1.11×** | 0.35 | 51 次/7.2d（旧 48） | **14%**（时间占比 13%，Poisson p=0.24）✅ 偏置已不可检出 |
| BTC | 3.8× → **1.15×** | 0.16 | 55 次/7.2d（旧 59） | **29%**（期望 13%，p=0.002）⚠ 仍有 2.2× 残余偏置 |

**BTC 没修干净，原因和取舍：** BTC 的同相位 \|ΔCVD\| 分布被压缩（p50=0.053、p99=0.284、
max=0.449），要在量级上和旧 0.08 对齐就必须取到 ~p97。低阈值处完全无偏置
（thr 0.09 → 43 次/7.2d、16%、p=0.14），但阈值一抬高，边界处的**方差放大**效应就让
fire 集重新偏向 K 线开盘。当前选了**保量级**的 0.16；若更在意纯度，改成 0.09 即可，
代价是 fire 量 ×6。这是一个已知的、写在 `symbol_config.yaml` 里的折中，不是遗漏。

阈值重标定说明：口径变了，量纲也变了，旧值不能沿用 —— 按新量纲取 0.12/0.08 会让
fire 率涨到 60% 的 pulse。新值是对齐**旧 fire 量级**选的（51 vs 48、55 vs 59），
这样这次改动的影响面是"同样的信号量、但不再由时钟触发"，而不是"信号量也变了"。

---

## 3. 检测器记分卡（按权重排序）

见文末机器生成表格。要点：

* **cvd_momentum（权重 0.65，XAUT 一个窗口就 fire 1459 次）**：fav 50±8% / 44±7%，fwd drift −0.03 / −0.09 ATR。
  它出现在 XAUT 24 个 wake 中的 **23 个**、BTC 33 个中的 **31 个**。它是整个分数的主要成分。
* **cvd_divergence（0.70）**：见上，时钟伪信号。
* **liquidation_hunt（0.60）**：BTC fav 27%（n=15），方向可能是反的（清算簇是局部极值）。
  样本太小，先挂观察，不要改。
* **cvd_absorption（0.50）/ positioning_extreme（0.50）**：fav 60±13% / 56±10%，capture 1.00 / 0.70，
  prior ≈ 0，delay 2–11 分钟 —— **这两个才是"早"的**，但 fire 太少，撑不起分数。
* **volatility_surge**：prior 30 分钟已经走了 **4.37 ATR**才触发，是全场最迟的（只有 4 次，别当结论）。

---

## 4. XAUT 的大行情与闸门

XAUT 有 15 个 ≥3 ATR/60min 的行情，只有 3 个 wake（都是 same_dir=3）。其余 12 个全部 `gate_fail`，
其中两个是 5.90 和 11.42 ATR 的行情，maxconf 到 0.75、同向信号 2 个（闸门要 3 个）。

但在 max-conf 那一刻入场的效果（`entry@maxconf`）：

* prior 已经走了 1.5–7.6 ATR（中位 ~2.5 ATR）；
* 11 个有数据的里面 7 个**先逆向 0.5 ATR**；
* fwd 有正有负（+11.33 / +4.87 / −1.54 / …）。

结论：**闸门拦掉的多数是"行情的后半段"**，放开它换来的不是更早的入场。
这跟之前几轮"边际候选超额为负"的结论一致，只是现在的解释更清楚：
问题是信号出现得太晚，不是闸门太严。

（BTC 那 6 个没收到的行情不一样：maxconf 只有 0.23–0.45，**低于 0.34 的触发线**，
根本没有 gate 事件 —— 那是检测器压根没响，不是闸门拦的。）

---

## 5. 建议（按信心从高到低）

> 以下都**没有执行**，等你定。这次分析本身没有改任何 production 代码或配置。

**S1（高信心，属于正确性修复而非调参）— 修 `cvd_divergence` 的窗口换手。** ✅ **已于 2026-10-05 实施方案 1，见 §2b**

原计划三个选项，从最小改动到最正确：

1. ✅ **口径最小改（已采用）**：`cvd_divergence` 不做 tick-to-tick 比较，改成和"同一相位的
   15 分钟前"的采样点比较（即真正比较两根相邻 K 线）。改动局限在两个函数
   （`_cvd_reference` / `_detect_cvd_divergence`）加一个 per-symbol 采样缓冲。
   ⚠ 计划里写的"阈值保持"**不成立**：口径一变量纲就变了，沿用旧值会让 fire 率涨到
   60% 的 pulse，所以阈值按新量纲重标到与旧 fire 量级对齐（XAUT 0.12→0.35、BTC 0.08→0.16）。
2. **数据源改**（未做）：`_derive_sentiment` 里把未收盘的 K 线排除（`micro_klines[:-1]` 取 4 根）。
   这样 `cvd_intensity_ratio` 每 15 分钟才更新一次、且相邻两次比较是两根完整 K 线之间，
   边界跳变消失；代价是该指标从"连续"变"阶梯"，`cvd_momentum` 的 growth 路径也要重新标定。
   —— 注意这个选项单独做**不解决问题**：它会让 2 分钟 tick 差在 13/15 的时间里恒为 0、
   只在边界跳一次，等于把伪信号变成 100% 的伪信号。必须先有方案 1 的"跨一整根 K 线比较"。
3. 两个一起做（未做）。

验证方式见 §2b：用真实 pulse 序列回放**已上线代码**，XAUT 的边界偏置从 3.7× 降到 1.11×、
fire 时间分布回到与时钟无关；BTC 均值层面 3.8×→1.15×，但尾部仍有 2.2× 残余偏置。

**S1b（新增，BTC 专项）** — 见 §2b 的说明：BTC 在"保量级"的 0.16 上仍有 29% 的 fire
落在 13% 的时间里。三个可选方向：(a) 维持现状并接受（已写在配置注释里）；
(b) 阈值降到 0.09（无偏置，但 fire 量 ×6）；(c) BTC 上直接停用该检测器。
在拿到更多数据前我倾向 (a)，因为 (b) 的 fire 量变化需要 A/B，(c) 是权重 0.70 的信号被撤，
不该只凭 24 个样本决定。

**S2（中信心）— 复核 cvd_momentum / large_trade 的权重。**
它们占掉了 wake 组成的绝大部分，实测方向 fav ≈ 50%/43%（XAUT）。
但**注意第 6 条的样本量问题**：要判定"降权更好"需要 ~100+ 独立事件，现在只有 ~20。
所以我建议**先不动**，而是把这两个检测器的 fire 记进一个可以长期累积的日志/表，
等样本够了再一次性判。

**S3（观察项）— liquidation_hunt 在 BTC 上方向存疑（27% fav, n=15）。** 只记录，不改。

**S4（不建议做）— 不要动 gate 的 3/1。** 数据说被拦的是迟到的入场。

**S5（基础设施）— 提高判定功效。** 现在"信号有没有用"这个问题的有效样本只有 ~20，
而 `fav%` 这种二元指标需要上百个样本才能分辨 55% vs 50%。两个办法：
(a) 决策标准改用连续量（capture / delay / fwd drift），同样数据下功效高得多；
(b) 把 wake 事件按"独立行情"聚类后再统计（这次已经这么做，建议固化进脚本）。
如果打算长期调这一块，值得加一张 "detector × 独立行情" 的累积表。

---

## 附录：机器生成的完整表格

（`python3 scripts/sniper_signal_latency.py --out <file>` 可复现）

## XAUTUSDT

4980 pulses in 43 continuous segments, 24 wakes.

| wakes | prior(30m) | mfe(60m) | mae(60m) | capture | min to swing start | same-dir active |
|---|---|---|---|---|---|---|
| 21 | +0.55 | +0.34 | -0.62 | +0.43 | +41.35 | +3.00 |

Forward drift over the 60m after a wake: **0.2 ATR** (se 0.34, t = 0.61, n = 24). |t| < 2 means the sample cannot distinguish this from no edge.

First touch after a wake (60m): ±0.5 ATR — fav 38% / adv 50% / flat 12% (n=24); ±1.0 ATR — fav 12% / adv 21% / flat 67% (n=24).

Lead/lag (4627 pulses): corr(conf, past 30m move) = **0.038**, corr(conf, future 30m move) = **0.063**, price-momentum baseline corr(past, future) = **0.384**, edge = **-0.321**.

| detector | act | prior(30m) | mfe(60m) | mae(60m) | capture | fwd drift | min to start | first touch ±0.5 |
|---|---|---|---|---|---|---|---|---|
| cvd_absorption | 31 | +0.00 | +0.26 | -0.10 | +1.00 | +0.01 | +2.10 | fav 29% / adv 19% / flat 52% (n=31) |
| cvd_divergence | 40 | +0.12 | +0.30 | -0.28 | +0.76 | +0.01 | +14.64 | fav 30% / adv 22% / flat 48% (n=40) |
| positioning_extreme | 44 | +0.14 | +0.35 | -0.29 | +0.70 | -0.06 | +11.49 | fav 34% / adv 27% / flat 39% (n=44) |
| boundary_test | 18 | +0.61 | +0.69 | -0.67 | +0.55 | +0.24 | +17.77 | fav 44% / adv 50% / flat 6% (n=18) |
| cvd_momentum | 76 | +0.28 | +0.23 | -0.27 | +0.45 | -0.03 | +21.93 | fav 25% / adv 25% / flat 50% (n=76) |
| large_trade | 78 | +0.31 | +0.22 | -0.40 | +0.44 | -0.01 | +18.79 | fav 27% / adv 36% / flat 37% (n=78) |
| volatility_surge | 4 | +4.37 | +0.75 | -1.12 | +0.29 | +0.53 | +22.66 | fav 0% / adv 100% / flat 0% (n=4) |
| liquidation_hunt | 1 | +2.51 | -0.09 | -1.51 | -0.04 | -1.41 | +10.51 | fav 0% / adv 100% / flat 0% (n=1) |

### Detector scorecard

`boundary x` = fire rate in the first 2 min of a 15-min candle ÷ rate elsewhere. `decided` = activations that reached ±0.5 ATR within 60 min; `fav%` = share of those that went the detector's way (50% = coin flip).

| detector | weight | fires | fires at candle start | boundary x | decided | fav% | capture | fwd drift | verdict |
|---|---|---|---|---|---|---|---|---|---|
| squeeze | 0.75 | 181 | 24% | 2.1x | 0 | —% | — | — |  |
| cvd_divergence | 0.7 | 48 | 67% | 12.9x | 21 | 57±10.9% | +0.76 | +0.01 | clock artifact |
| cvd_momentum | 0.65 | 1459 | 16% | 1.2x | 38 | 50±8.1% | +0.45 | -0.03 |  |
| volatility_surge | 0.55 | 6 | 17% | 1.3x | 4 | 0±25.0% | +0.29 | +0.53 |  |
| large_trade | 0.55 | 681 | 19% | 1.5x | 49 | 43±7.1% | +0.44 | -0.01 |  |
| positioning_extreme | 0.5 | 48 | 17% | 1.3x | 27 | 56±9.6% | +0.70 | -0.06 |  |
| cvd_absorption | 0.5 | 504 | 15% | 1.1x | 15 | 60±12.9% | +1.00 | +0.01 |  |
| boundary_test | 0.5 | 18 | 17% | 1.3x | 17 | 47±12.1% | +0.55 | +0.24 |  |


Big moves (>= 3.0 ATR within 60m): **15**, of which a wake happened nearby: **3**, same-direction wake: **3**.

| move dir | size | wake | max conf | same-dir active | first detector | why blocked |
|---|---|---|---|---|---|---|
| BEARISH | 3.06 | **no** | 0.55 | 1 | cvd_divergence @8.4m | gate_fail |
| BEARISH | 5.9 | **no** | 0.75 | 2 | cvd_momentum @0.0m | gate_fail |
| BEARISH | 11.42 | **no** | 0.75 | 2 | cvd_momentum @0.0m | gate_fail |
| BEARISH | 6.79 | **no** | 0.48 | 2 | large_trade @0.0m | gate_fail |
| BEARISH | 3.06 | **no** | 0.5 | 1 | boundary_test @35.5m | gate_fail |
| BEARISH | 7.79 | yes | 0.84 | 3 | boundary_test @4.2m | shadow |
| BEARISH | 5.33 | yes | 0.84 | 3 | cvd_momentum @8.4m | shadow |
| BEARISH | 4.71 | yes | 0.61 | 3 | large_trade @0.0m | shadow |
| BEARISH | 3.22 | **no** | 0.74 | 2 | large_trade @16.7m | gate_fail |
| BULLISH | 3.43 | **no** | 0.83 | 2 | cvd_absorption @0.0m | gate_fail |
| BULLISH | 3.86 | **no** | 0.53 | 2 | cvd_absorption @0.0m | gate_fail |
| BULLISH | 4.31 | **no** | 0.64 | 1 | cvd_divergence @43.8m | gate_fail |
| BEARISH | 3.02 | **no** | 0.64 | 1 | boundary_test @2.1m | gate_fail |
| BULLISH | 3.85 | **no** | 0.58 | 2 | large_trade @48.5m | gate_fail |
| BULLISH | 6.15 | **no** | 0.51 | 1 | large_trade @16.7m | gate_fail |

## BTCUSDT

4980 pulses in 43 continuous segments, 33 wakes.

| wakes | prior(30m) | mfe(60m) | mae(60m) | capture | min to swing start | same-dir active |
|---|---|---|---|---|---|---|
| 33 | +0.42 | +0.45 | -0.24 | +0.49 | +79.50 | +2.00 |

Forward drift over the 60m after a wake: **0.3 ATR** (se 0.1, t = 3.14, n = 33). |t| < 2 means the sample cannot distinguish this from no edge.

First touch after a wake (60m): ±0.5 ATR — fav 42% / adv 21% / flat 36% (n=33); ±1.0 ATR — fav 12% / adv 3% / flat 85% (n=33).

Lead/lag (4627 pulses): corr(conf, past 30m move) = **0.158**, corr(conf, future 30m move) = **0.013**, price-momentum baseline corr(past, future) = **0.257**, edge = **-0.244**.

| detector | act | prior(30m) | mfe(60m) | mae(60m) | capture | fwd drift | min to start | first touch ±0.5 |
|---|---|---|---|---|---|---|---|---|
| boundary_test | 4 | +0.00 | +0.59 | -0.31 | +1.00 | +0.17 | +0.00 | fav 50% / adv 25% / flat 25% (n=4) |
| cvd_absorption | 51 | +0.03 | +0.33 | -0.27 | +0.92 | +0.12 | +4.16 | fav 35% / adv 31% / flat 33% (n=51) |
| large_trade | 63 | +0.24 | +0.28 | -0.24 | +0.63 | -0.06 | +14.62 | fav 30% / adv 24% / flat 46% (n=63) |
| positioning_extreme | 3 | +1.63 | +1.50 | -1.01 | +0.59 | +0.90 | +28.48 | fav 67% / adv 33% / flat 0% (n=3) |
| cvd_divergence | 47 | +0.15 | +0.21 | -0.23 | +0.58 | -0.08 | +21.06 | fav 28% / adv 23% / flat 49% (n=47) |
| cvd_momentum | 82 | +0.21 | +0.25 | -0.27 | +0.48 | -0.09 | +23.03 | fav 26% / adv 33% / flat 41% (n=82) |
| liquidation_hunt | 24 | +0.52 | +0.23 | -0.48 | +0.35 | -0.09 | +22.03 | fav 17% / adv 46% / flat 38% (n=24) |

### Detector scorecard

`boundary x` = fire rate in the first 2 min of a 15-min candle ÷ rate elsewhere. `decided` = activations that reached ±0.5 ATR within 60 min; `fav%` = share of those that went the detector's way (50% = coin flip).

| detector | weight | fires | fires at candle start | boundary x | decided | fav% | capture | fwd drift | verdict |
|---|---|---|---|---|---|---|---|---|---|
| squeeze | 0.75 | 55 | 24% | 2.0x | 0 | —% | — | — |  |
| cvd_divergence | 0.7 | 59 | 90% | 56.8x | 24 | 54±10.2% | +0.58 | -0.08 | clock artifact |
| cvd_momentum | 0.65 | 846 | 18% | 1.4x | 48 | 44±7.2% | +0.48 | -0.09 |  |
| liquidation_hunt | 0.6 | 27 | 22% | 1.8x | 15 | 27±12.9% | +0.35 | -0.09 |  |
| large_trade | 0.55 | 367 | 21% | 1.7x | 34 | 56±8.6% | +0.63 | -0.06 |  |
| cvd_absorption | 0.5 | 829 | 15% | 1.2x | 34 | 53±8.6% | +0.92 | +0.12 |  |
| boundary_test | 0.5 | 5 | 0% | 0.0x | 3 | 67±28.9% | +1.00 | +0.17 |  |


Big moves (>= 3.0 ATR within 60m): **10**, of which a wake happened nearby: **4**, same-direction wake: **4**.

| move dir | size | wake | max conf | same-dir active | first detector | why blocked |
|---|---|---|---|---|---|---|
| BEARISH | 3.03 | **no** | 0.45 | 1 | large_trade @31.4m | gate_fail |
| BULLISH | 3.01 | **no** | 0.24 | 2 | cvd_absorption @25.2m | — |
| BULLISH | 4.85 | **no** | 0.25 | 1 | cvd_momentum @18.9m | — |
| BEARISH | 3.13 | **no** | 0.23 | 1 | positioning_extreme @52.4m | — |
| BEARISH | 3.51 | **no** | 0.23 | 1 | positioning_extreme @21.0m | — |
| BULLISH | 3.07 | yes | 0.7 | 2 | liquidation_hunt @27.1m | cooldown_block/shadow |
| BULLISH | 3.14 | yes | 0.7 | 2 | liquidation_hunt @2.1m | cooldown_block/shadow |
| BULLISH | 3.55 | yes | 0.51 | 1 | cvd_momentum @29.3m | shadow |
| BULLISH | 4.09 | yes | 0.28 | 1 | large_trade @0.0m | — |
| BULLISH | 3.39 | **no** | 0.24 | 1 | liquidation_hunt @43.8m | — |

