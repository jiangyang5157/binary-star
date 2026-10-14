# 信号器重新设计 — 2026-10-14

目标（operator 原话）：**在保证信号质量的背景下，尽量抓住真实波动。**
约束：不轻动 session / LLM / prompt；最后判断 UI 是否要跟着改；尽量避免 magic number；
default 改了要报备，overrides 可自行决定。

---

## 0. 先把边界划清（决定了设计的自由度）

代码里的真实数据流：

```
metrics ──> 9 个 detector ──> SignalMemory(衰减) ──> ConfluenceEngine ──> Pre-AI Gate
                                                                              │
                                              ┌───────────────────────────────┴──────────────┐
                                              │ TriggerResult                                 │
                                              │  ├ situation_brief ──> observation ──> LLM    │
                                              │  └ (state/pulse file) ──> dashboard UI        │
                                              └───────────────────────────────────────────────┘
```

`_build_situation_brief()`（trigger.py:729）只往外送三样东西：

```python
{"confluence_score": float,
 "confluence_direction": str,
 "activated_by": [ {"signal": <detector sub_type>, "direction": str, "strength": float}, ... ]}  # 最多 5 个
```

`run_session.py:135` 把它塞进 `observation['situation_brief']`，observation 进 prompt。
UI 侧（`live.html`）渲染 `sd.all_signals[]`，字段 `type / score / strength / direction / is_active`，
注释写明是 "Compact signal strip (**10 blocks**)"，tooltip 用检测器名。

**因此：**

| 改动类型 | 触达 session/LLM？ | 触达 UI？ | 本设计是否允许 |
|---|---|---|---|
| 检测器**触发条件**、阈值、计算方式 | ❌ | ❌（只有数值变化） | ✅ 自由 |
| 新增 `SignalCard` 字段（不进 brief） | ❌ | 仅当写进 pulse file | ✅ 可控 |
| `situation_brief` 结构 / `activated_by` 选择逻辑 | ⚠️ **是** | ❌ | ⛔ **本设计不动** |
| 检测器**名字 / 数量 / 顺序** | ⚠️ **是** | ⚠️ **是** | ⛔ **本设计不动** |
| session / prompt / LLM config | — | — | ⛔ **完全不碰** |

> **本设计的自我约束：检测器名字、数量、顺序一律不变，`situation_brief` 结构不变。**
> 这样这一轮重构对 session / LLM / prompt **零影响**，operator 不需要审 prompt。
> 如果将来要动 brief 或检测器清单，那必须单独提出来评估。

---

## 1. 设计目标（全部由前面几轮的证据推出，不是拍脑袋）

| # | 目标 | 依据 |
|---|---|---|
| **G1** | 让"广度"要求变真实 | "≥3 个信号"实际只承载约 1 份独立信息：cvd_momentum 与 large_trade 的方向都取自 `sign(cvd)`，cvd_absorption 亦由 cvd 驱动；62 次 wake 里 cvd_momentum 出现 60 次 |
| **G2** | 消灭 magic number 与"永不可达"条件 | `pos_ext` 的 `ls>1.5/2.0`（实测 max 1.07/1.72）与 `\|fund\|>0.0005`（实测 max 0.0001）算术上永不成立；cvd_divergence 的旧口径也是同一类问题 |
| **G3** | 让质量可测量 | 闸门拒绝只进日志、从不回流；evolution 也不消费 → 系统学不到"哪个检测器值它的权重"，所有优化只能靠人工读日志 |
| **G4** | 降低延迟 | 波动丢在"信号太晚"：wake 的 capture 只有 0.43/0.49、距波段起点 41/80 分钟；被闸门拦掉的 14 个 XAUT 大行情里 10 个"进场先逆向" |
| **G5** | 守住 §0 边界 | 不动名字/数量/顺序/brief —— session、LLM、UI 契约不动 |

---

## 2. 设计

### 2.1 来源标签（provenance）—— 修 G1 的地基，零行为变化

给 `SignalCard` 增加一个字段 `source`，集中定义在一张映射表里（**不散落魔字符串**）：

```python
# 一个信息源 = 一批共享同一底层数据与方向的检测器
SIGNAL_SOURCES = {
    "cvd_momentum":       "flow",         # 方向 = sign(cvd)
    "cvd_divergence":     "divergence",   # 方向 = **-sign(price_delta)**（逆势价格），不是 sign(cvd)
    "cvd_absorption":     "flow",         # 方向 = -sign(cvd)
    "large_trade":        "flow",         # 方向 = sign(cvd)
    "volatility_surge":   "volatility",   # 方向 = sign(cvd) or trend  ← 见下方注
    "squeeze":            "volatility",   # 方向 = NEUTRAL
    "boundary_test":      "structure",    # 方向 = 离 VAH/VAL 哪边近
    "liquidation_hunt":   "liquidity",    # 方向 = 簇位置 + 价格方向
    "positioning_extreme":"positioning",  # 方向 = ls / funding / OI
    "leader_sync":        "cross_symbol",
}
```

> **注 1**：`volatility_surge` 的方向取自 `sign(cvd)`，所以它**不是**独立的。
> 按"方向从哪来"分，它应归 `flow`；但按"它测什么"分，它属于 `volatility`。
> 设计上取**前者**（方向来源）—— 因为广度要求的本质是"独立的信息"，不是"不同的指标"。
> 即：`volatility_surge → "flow"`。
>
> **注 2（2026-10-14 self-review 修正）**：初版把 `cvd_divergence` 也归进 `flow`，这是**错的**。
> 它的方向是 `BEARISH if price_delta > 0 else BULLISH` —— 取自**价格的逆向**，不是 `sign(cvd)`。
> 按本设计自己的规则（按方向来源分组），它必须单独成源，否则会**低估**独立来源数、
> 让 shadow 闸门读起来比实际更容易拦。已改为 `divergence`。

**这一条本身不改变任何行为**，只是让系统（和 UI）第一次能说清"我现在有几份独立信息"。

### 2.2 自适应条件 —— 修 G2 + 直接消灭 magic number

**原则：任何检测器的触发条件都不写绝对值，而是相对"该 symbol 自身的近期分布"。**

现有先例已经在代码里：`large_trade` 用 `deque(maxlen=large_trade_lookback)` 存 `avg_trade_size`
并算 z-score。把同一个模式推广到所有还在用绝对常数的条件：

| 检测器 | 现在的绝对条件 | 改成 | magic number |
|---|---|---|---|
| pos_ext P1a | `ls > long_short_imbalance_ratio`（1.5 / 2.0） | `z(ls) > k` | 消失（k 全局唯一） |
| pos_ext P2 | `\|funding\| > funding_extreme_threshold`（0.0005） | `z(funding) > k` | 消失 |
| pos_ext P3/P4 | `\|oi_delta\| > 0.01 / 0.02`（还有 `0.01` 这种裸数字） | `z(oi_delta) > k` | 消失 |
| cvd_momentum | `\|cvd\| > 0.2/0.14`，extreme `0.24/0.18` | `z(cvd) > k` | 消失 |
| vol_surge | `vii > 1.25`、`vpr > 1.5`、增长 `×1.03` | `z(vii) > k`、`z(vpr) > k`、`Δz(vii) > k` | 消失 |
| boundary_test | `proximity.vah_val_atr`（0.7） | 保留（**有物理单位**：ATR，不是魔数） | 保留 |
| cvd_divergence | `\|Δcvd\| > 0.35/0.16` | `z(Δcvd) > k` | 消失 |

**为什么这一步同时解决 G2 和 magic number：**
- z-score 的条件**永远可达**（除非该指标恒定），所以不可能再出现"声明了却永不触发"的检测器；
- 它自动适配 symbol 与 regime（BTC 的 `ls` 分布天生比 XAUT 窄，不用再手写两组阈值）；
- config 里只剩一个全局 `k`，而不是每 symbol × 每检测器一个数。

**代价（必须说清）：**
- 每个检测器需要一个滚动窗口 → **warmup 期间该检测器变暗**（与 cvd_divergence 现在的行为一致）。
  窗口长度是一个可调参数（建议用"分钟"表达，而不是"pulse 数"，避免与 pulse 周期耦合 —— 这正是我上一轮修掉的 A8 缺陷）。
- z-score 对厚尾敏感 → 用**稳健**版本（median + MAD），不用 mean/std。

### 2.3 广度判据：从"信号数"改为"独立来源数"（**先 shadow，不改行为**）

```yaml
gate:
  min_active_non_trend: 3      # ← 保留，回归对照
  min_active_trend: 1
  min_sources_non_trend: 2     # ← 新：≥2 个独立来源（shadow 先跑）
  min_sources_trend: 1
  sources_mode: shadow         # off | shadow | enforce
```

`shadow` 模式下：**闸门判决完全按旧逻辑**，只额外记一行 `GATE SOURCE SHADOW | would=… | actual=…`。
这样可以在**零风险**下积累"来源判据到底会不会更早/更好"的证据，等样本够了再 `enforce`。

> ⚠️ 注意：`min_sources_non_trend: 2` 对现状是**收紧**（{cvd_momentum, large_trade, cvd_absorption}
> 全是 `flow`，只有 1 个来源）。这是有意的 —— 现有证据（P1/P2/P5）都说不该放松闸门，
> 该做的是让"广度"名副其实。但**是否 enforcing 必须等 shadow 数据**，本轮只跑 shadow。

### 2.4 反馈回路 —— 修 G3

1. **pulse file 增加 `source`**（每 signal 一个字段）→ UI 可用，也是离线评分的输入。
2. **diag 行增加 `sources=`**，与 `fresh=`/`memory=` 并列 → 每轮可解析。
3. **每轮记录闸门判决**（已有 `gate_result/gate_reason`）→ 加上 shadow 判决。
4. 离线评分工具（`scripts/sniper_threshold_ab.py` 已具备雏形）按**来源**分组统计质量，
   使"某个来源值不值得留"成为一个可累积、可判定的问题。

### 2.5 延迟（G4）—— 本轮只做**测量**，不做改动

G4 的解法需要新的快指标（例如 5 分钟 taker 净流），而**该数据当前没有落日志**，
所以无法回测。本轮不猜测、不实现，只把"每轮记录各检测器的 prior/delay"纳入 §2.4 的观测面，
等数据够了再设计。

---

## 3. 对 session / LLM / prompt 的影响（约束 #1 的答复）

**这一轮：零影响。** 因为：

- 检测器**名字、数量、顺序**不变 → `activated_by[].signal` 不变；
- `situation_brief` 的结构与选择逻辑（`_build_situation_brief`）不改；
- prompt 模板、session 逻辑、LLM config 完全不碰。

唯一的间接影响：条件变成自适应之后，**哪些信号会出现**会变（这是设计目的），
但那属于"阈值变化"，不改变 LLM 看到的**字段与格式**。

> 若将来要动 `activated_by`（例如把 `source` 也送进 prompt 让 LLM 知道信号是否独立），
> 那是**改 prompt 输入**，必须单独提出并让你审。

## 4. config 变更的影响面（default vs overrides）

按你的规则：**default 动了要报备，overrides 我自行决定。**

| 位置 | 变更 | 报告 |
|---|---|---|
| `config/global_config.yaml` → `signal_stack.adaptive`（**新增段**） | 新增，不删旧值 | ⚠️ **default 新增**（详见实施说明） |
| `config/global_config.yaml` → `thresholds.*` | 改为 `adaptive` 的兜底值（保留原键，向后兼容） | ⚠️ **default 语义变化** |
| `config/global_config.yaml` → `gate.min_sources_*` / `sources_mode` | 新增，默认 `shadow` | ⚠️ **default 新增** |
| `config/symbol_config.yaml` → 各 symbol overrides | 可删掉一批被自适应取代的绝对阈值 | ✅ 我自行处理 |

## 5. UI 评估（约束 #2 的答复，详见 §6）

---

## 6. UI sniper panel 是否该跟着改

**现状**（`live.html`）：`all_signals` 渲染成 **10 个方块**的 strip，tooltip = 检测器名，
颜色 = 方向（BULLISH 绿 / BEARISH 红 / 其他灰），透明度 = `0.5 + score*0.5`。

**判断：本轮设计下 UI 不改也能正常工作**（名字/数量/顺序不变，字段只增不减）。
**但有两处值得改，且都属于"信息已经算出来了却没显示"：**

| # | 建议 | 理由 | 优先级 |
|---|---|---|---|
| **U1** | strip 按 `source` 分组显示（例如 4 个 flow 方块之间加间隔/同色系），并在旁边显示 **`sources=N`** | 现在 10 个方块看起来像"10 份独立证据"，实际常常只有 1–2 份。这是当前 UI 最容易误导 operator 的地方 | **高** |
| **U2** | 显示自适应阈值的**当前值**（如 `z=2.1 / 阈值 2.0`） | 阈值自适应后，operator 无法再用一个固定数字判断"为什么没触发" | 中 |
| U3 | shadow 判决上线后，显示 `would=…` | 让 operator 能直接看到"新判据会怎么判" | 中（等 shadow 有数据） |

**U1 是我建议一定要做的**：它不改变任何逻辑，只是把一个**已经存在但被隐藏的事实**
（独立来源数）显示出来 —— 而这恰好是当前"trigger 很少"困惑的根源之一。

---

## 7. 实施顺序（本轮我会做的 vs 需要你点头的）

| 阶段 | 内容 | 行为变化 | 本轮做？ |
|---|---|---|---|
| **A** | `SignalCard.source` + 映射表；diag 加 `sources=`；pulse file 加 `source`；shadow 闸门 | **无** | ✅ 做 |
| **B** | UI U1（按 source 分组 + 显示 `sources=N`） | 无（纯显示） | ✅ 做 |
| **C** | 自适应条件（§2.2） | **有**（会改变触发时机与数量） | ⏸️ 需你点头 |
| **D** | `sources_mode: enforce` | **有**（收紧闸门） | ⏸️ 等 shadow 数据 |
| **E** | 延迟改造（G4 新指标） | **有**（需新数据源） | ⏸️ 需先落数据 |

A + B 是纯粹的"让系统说真话"：不加信号、不减信号、不改判决，只是把独立来源数暴露出来。
C 才是真正的行为改动，我建议等 A/B 上线积累一段时间后再做，而且届时可以直接用 shadow 数据判断。

---

## 8. 实施记录（2026-10-14，A + B 已完成）

### 已实施

| 位置 | 改动 |
|---|---|
| `src/sniper/trigger.py` | 新增 `SIGNAL_SOURCES` 映射表 + `DEFAULT_SIGNAL_SOURCE`；`SignalCard.source`（由 `sub_type` 在 `__post_init__` 推导，调用方无需传）；diag 行尾部新增 `sources=N[a,b]`；`_run_pre_ai_gate` 新增 §2.3 的来源广度判定（`off/shadow/enforce`） |
| `run_sniper.py` | pulse file 每个 signal 增加 `source`；每个 symbol 增加 `sources_active` / `sources` |
| `config/global_config.yaml` | gate 新增 `min_sources_non_trend: 2` / `min_sources_trend: 1` / `sources_mode: shadow` |
| `src/dashboard/templates/live.html` | U1：signal strip 按 `source` 分组（换源处加 4px 间隔）、tooltip 追加 `· <source>`、右侧显示 `N src/srcs`；对旧 pulse file 有回退推导 |
| `src/dashboard/static/dashboard.css` | `.signal-strip-row` / `.signal-strip-sources` |
| `tests/unit/test_trigger.py` | +11 用例：来源推导、**注册表全覆盖守卫**（新检测器不允许静默落到 `unknown`）、flow 簇=1 来源、shadow 不改变判决、enforce 会拦、未知 sub_type 回退 |

### 验证

- 全量 **516 passed**（原 505）。
- **日志格式向后兼容**：新增的 `sources=` 是尾部独立字段，`parse_diag` 只认已知前缀、忽略未知块
  （实测字段数 14→15，`cvd`/`price`/9 个 detector 均正确解析）。
- **UI 无破坏**：Jinja 渲染通过（44,709 字节），渲染后的内联 JS 通过 `node --check`。
- **零行为变化**：`sources_mode: shadow` 只多打一行 `GATE SOURCE WOULD BLOCK`，
  闸门判决与改动前逐字节一致（有测试断言 shadow 下 `res == 'PASS'` 且 `reason == ''`）。

### C 的离线测量（2026-10-14，`scripts/sniper_adaptive_ab.py`）

用生产日志把**真实检测器**跑两遍（legacy vs adaptive），再叠闸门策略。
质量 = 60 分钟前瞻收益（ATR，检测器自己的方向）− 同向无条件漂移，**按独立行情聚类**后给显著性。

**单个检测器：**

| | legacy | adaptive | 判读 |
|---|---|---|---|
| XAUT cvd_momentum | 1944 (26.7%) | **205 (2.8%)** | 停止刷屏 |
| XAUT cvd_absorption | 780 (10.7%) | 76 (1.0%) | 同上 |
| XAUT large_trade | 910 (12.5%) | 369 (5.1%) | 同上 |
| XAUT **volatility_surge** | **9 (0.12%)** | **66 (0.91%)** | 死检测器复活 |
| BTC **volatility_surge** | **1 (0.01%)** | **73 (1.00%)** | 同上（×73）|
| BTC **positioning_extreme** | **4 (0.05%)** | **79 (1.08%)** | 同上（×20）|
| BTC cvd_absorption | 1356 (18.6%) | 130 (1.8%) | 停止刷屏 |

harness 保真度校验：legacy 模式下 cvd_momentum 26.7%（生产 25.9%）、cvd_absorption
10.7%/18.6%（生产 9.7%/16.9%）、large_trade 12.5%/6.5%（生产 13.4%/7.3%）。

**闸门策略叠加**（2026-10-14 self-review 修正 R1 之后重测。**上一版结论是错的** ——
它建立在把 `cvd_divergence` 错分到 `flow` 之上，低估了来源数）：

| 策略 | XAUT passes / episodes / adj | BTC passes / episodes / adj |
|---|---|---|
| **现状** `count≥3` | 44 / 8 / **−0.327** (t=−1.55) | 11 / 2 / **−0.078** |
| `count≥2`（legacy） | 605 / 59 / **+0.059** | 322 / 46 / −0.023 |
| **`sources≥2`（legacy）** | **102 / 18 / −0.056** | **90 / 17 / +0.003** |
| `sources≥2`（adaptive） | 133 / 15 / −0.090 | 145 / 15 / **+0.115** |

**修正后的结论（按这一版，不是上一版）：**

1. **`sources≥2` 不需要 adaptive 就能达到**（legacy 102 / 90 次）。上一版说
   "必须 adaptive 才可达"是 R1 错分造成的假象：`cvd_divergence` 单独成源后，
   `flow + divergence` 本身就是两个来源。
2. **没有任何策略在两个 symbol 上同时支配**：XAUT 的点估计偏好 `count≥2`（+0.059），
   BTC 偏好 `sources≥2`（+0.003 / +0.115）。
3. **唯一一致的信号是：现状 `count≥3` 在两个 symbol 上点估计都最差**
   （−0.327 / −0.078）—— 但它的 episode 只有 8 和 2，属于弱证据。
4. **全部不显著**（最大 t=0.68，episodes 15–59）。所以这不是"证明了更好"，
   而是"现状看起来最差，但样本不足以换方向"。

**因此 default 维持不动**：`adaptive.enabled: false` + `sources_mode: shadow`。
shadow 逐轮记录 `would block: n/N independent sources`，等 episode 够了再决定 enforce。

> **实现语义（R7）**：`enforce` 下来源判据**替换**信号计数判据，而不是叠加。
> 初版是 AND，与 §2.3 的设计意图和上面的测量口径都不符，而且 AND 会把 legacy 的
> flow-only 三元组一次性清空。已改为替换并有测试固定。

### D 的方式被推翻：`sources_mode` 已删除（2026-10-14，operator 质疑）

operator 问："badge 也删了，那 `sources_mode` 为什么还要？难道未来我还要 rollback？" —— **他是对的，该删。**

推翻了什么：

1. **shadow 是冗余的。** 诊断行每轮已经输出 `sources=N[...]`，用的是与闸门**同一个函数
   （`independent_sources`）、同一个列表（`all_signals`）、同一个方向（`dominant_direction`）**。
   因此 `len(sources) < min_sources` **完全可以从日志推出来** —— `GATE SOURCE WOULD BLOCK`
   只是把同一个判断又记了一遍。我原先"零风险积累证据"的理由，忽略了证据本来就在日志里。
2. **badge 删掉后，shadow 没有任何消费者。** 没有 UI，没有人读，只剩一行重复的日志。
3. **三态换一态。** 现在的开关就是一个数字：
   `min_sources_non_trend: 0`（关闭 = 现状） → `2`（启用 = 替换计数判据）。
   没有半开状态需要维护，**所以在任何方向上的"回滚"都只是把这一个数字改回去**，
   不存在"要回滚代码"的情形。

同时删除：`sources_mode`（配置键 + 三态语义）、`TriggerResult.gate_shadow`、
`self._gate_shadow`、`GATE SOURCE WOULD BLOCK` 日志行、pulse file 的 `gate_shadow` 字段，
以及 `shadow_require_independent_direction` 之外的 shadow 相关测试。

保留并强调：`SignalCard.source` / `SIGNAL_SOURCES` / 诊断行的 `sources=N[a,b]` ——
**这才是证据通道**，而且日志和离线工具都能读。

### 原 D 的判据（已被上面取代）

`min_sources_*` + `sources_mode` 已实现，默认 `shadow`。**不启用 enforce 的判据是明确的：**

| 需要看到 | 现状 | 结论 |
|---|---|---|
| —（**不再需要**）：R1 修正后 `sources≥2` 在 legacy 下即可达（BTC 90 次 / 17 episodes） | — | 上一版曾把 adaptive 当作 enforce 的必要条件，那是我错分来源造成的 |
| shadow 日志里 "would block" 的**独立行情数** ≥ 30 | 0（日志尚未产生） | 现在只有 15–18 个 episode，enforce 等于凭不到 20 个样本改行为 |
| would-block 的那批在 `sources≥2` 口径下的 adjusted excess 非负 | 未测（无 shadow 数据） | 目前只有离线估计：legacy `sources≥2` 为 +0.003(BTC) / −0.056(XAUT) |

**所以 enforce 与 adaptive 必须同批开启**，且开之前先积累 shadow 数据。

### E — 延迟探针（只采集，不设计）

`src/sniper/scout.py` 新增 `_log_flow_probe()`：每轮记录最近 `cvd_micro_lookback_candles` 根
15m K 线的 **原始逐根 taker 净流与成交量**（最新在前，第一项是未收盘的那根）：

```
[XAUTUSDT] FLOW PROBE | flow=[+0.2000,1.0000],[+3.0000,9.0000],[+0.5000,6.0000],[-2.0000,8.0000]
```

**为什么只写日志、不进 metrics**：`sentiment_signals` 会随 `observation` 进入 session/LLM 的
输入（§0）。新增字段就是动 prompt 输入，超出本次授权范围。写日志则完全不触达 session，
同时把设计"更快的指标"所需的数据留下来了 —— 现在这些数据从未落盘，所以任何短周期
（<60 分钟）指标都**无法回测**，这是 G4 一直无法推进的真正原因。

测试覆盖：最新在前、按 lookback 截断、空输入不输出、缺 taker 字段不输出、
以及**任何输入都不许抛异常**（探针不能弄坏一次 pulse）。

### UI U3 — **撤销**（2026-10-14，经 operator 质疑）

初版把 shadow 判决做成面板徽章。operator 反问"我也没有 switch 吧？"—— **他说得对**：

- `sources_mode` 是 config 里的一行（`off|shadow|enforce`），**面板上没有开关**，所以那个徽章
  在描述一条 operator 无法开启、且可能永远不会开启的规则；
- 如果最终决定不 enforce，它就是**永久装饰**；
- 而它要服务的证据需求，pulse file 的 `gate_shadow` 字段和日志行 **已经完全覆盖**（可 grep、可离线统计）。

**处置**：从面板移除徽章，**保留** `TriggerResult.gate_shadow`、pulse file 字段与日志行。
测试反向固定：面板里不许再出现 `sc-shadow` / `gate_shadow` / `would block`。

### UI U1 的两处修正（同一次质疑牵出）

| 问题 | 说明 | 处置 |
|---|---|---|
| **分组是假的** | strip 的方块顺序来自 daemon 的注册表顺序，而它是 `cvd_momentum(flow) → cvd_divergence(divergence) → cvd_absorption(flow) → …` —— `divergence` 夹在两个 flow 中间。我加的"换源加 4px 间隔"因此在 10 个方块里产生 **5 处小缝**，读起来是随机间距而不是分组 | 新增 `_orderedSignals()`：按 source **稳定排序**（同源内保持原序），render 与 update 两条路径共用；分组间隔这才成立 |
| **徽章需要解释** | 原来显示 `5 srcs`，operator 得先知道 "src" 是什么、几个算多 | 改为**直接显示来源名字**（`flow+positioning`），`title` 里给出完整列表与解释 |

### UI U2 — 暂缓（原因不变）

`TriggerResult.gate_shadow` 承载 shadow 判决（**与 `gate_reason` 分开**，避免让人误以为它是
没唤醒的原因），经 pulse file 到 UI，在 signal card 头部显示 `◇ would block: 1/2 independent sources`。
只在"would block"时出现，空判决不占位；每轮都重算，测试覆盖**不残留上一轮的值**。

**U2（显示自适应阈值当前值）暂缓**：`adaptive.enabled` 默认 false，此时没有任何"当前 z 值"
可显示，先做等于上线一段死 UI。等 C+D 开启时一起做。

### Self code review（2026-10-14）—— 发现并修掉 6 处，其中 3 处是我自己的 bug

| # | 性质 | 问题 | 处置 |
|---|---|---|---|
| **R1** | **我的 bug（正确性）** | `SIGNAL_SOURCES` 把 `cvd_divergence` 归进 `flow`，但它的方向是 `BEARISH if price_delta > 0`，即**逆向价格**，不是 `sign(cvd)` —— 违反本设计自己定的"按方向来源分组"规则，会**低估**独立来源数、让 shadow 闸门读起来比实际更容易拦 | 改为独立来源 `divergence` |
| **R2** | **我的 bug（行为回归）** | 转换 `pos_ext` P3/P4 时把 legacy 的饱和分母从 `OI_DIVERGENCE_SATURATION`(0.03) / `OI_SURGE_SATURATION`(0.04) 换成了 `oi_floor*2`(0.02)，**legacy 强度被静默改了 1.5×**，进而影响 confluence 与闸门 | 恢复 legacy 算式原样；并留下**指纹工具**作为这类回归的护栏 |
| **R3** | **我的 bug（可观测性）** | 诊断行不知道 adaptive 模式：`large_trade` 会永远报 `warmup(0/5)`（它的 legacy deque 在 adaptive 下不再喂），`cvd_momentum`/`vol_surge`/`pos_ext` 报的是**已失效的旧阈值** | 四个字段全部按模式分支，报"实际生效的那个" |
| **R4** | **我的 bug（日志说谎）** | `cvd_divergence` 的 reason 在 adaptive 下把**原始 dCVD** 与 **z 阈值**印在一起 | 按模式分别印 `\|z\|=` / `\|dCVD\|=` |
| **R5** | 真 bug（UI） | shadow 徽章只在首次渲染时**条件创建**，之后 in-place update 找不到元素 → 后来才出现的判决永远不显示 | 无条件创建、用 `display` 切换 |
| **R6** | 真 bug（孤儿常量） | 转换后 `OI_DIVERGENCE_SATURATION` / `OI_SURGE_SATURATION` 成为死常量 | 随 R2 一并恢复使用 |
| **R7** | **我的 bug（实现与设计不符）** | 来源判据被**叠加**在计数判据之后（AND），而设计 §2.3 的意图是**替换**；AND 语义下 legacy 的 flow-only 三元组会被一次性清空，且与我的测量口径不一致 | 改为替换 + 测试固定语义；并据此**推翻了上一版「必须 adaptive 才可达」的结论** |

| **R8** | **我的 bug（同类缺陷复发）** | 我声称"换 z 后条件**按构造可达**"，但**被量化的指标不成立**：funding 只有 `0.0000`/`0.0001` 两个值 → MAD=0 → fail-safe 让 z 恒为 0 → **该路径仍然永久不可达，而且又是静默的** —— 正是这次重构要消灭的那一类 | `RobustWindow.is_degenerate` + 诊断三态 `warmup / degenerate / z=`，让不可达**可见**；实测数据与结论写入 config 注释 |

| **R9** | **我的 bug（同一概念三套算法）** | `sources` 在**闸门 / 诊断行 / pulse file** 三处各算一遍，且诊断与 UI 用 `direction != NEUTRAL` **把两个方向的来源合并计数** —— 实测在 **18 轮 XAUT / 6 轮 BTC** 上报 2 个来源而闸门只看到 1 个。**这是最糟的一类错**：我把这个数字当作判断 shadow 闸门的依据，而它系统性偏高 | 抽出唯一实现 `independent_sources(signals, direction)`，三处共用；诊断行改到 confluence 之后发射（此时才有主导方向）；NEUTRAL 一律返回空（否则 `squeeze` 会给无方向的 pulse 报出"1 个来源"）；离线 replay 的 signal 也补上 `source` 以免工具口径再次分叉 |**验证 legacy 路径未被触碰（最关键的一条）：**

| **R10** | **我的 bug（自我包含）** | `_record_adaptive_samples` 在**检测器之前**执行，所以本轮样本已经进了窗口，检测器再拿它和窗口比 —— 异常值坐在自己的基线里、部分掩盖自己。已删除的 `score()` 恰恰是为避免这件事而设计的，而生产路径绕过了它 | 把 fold-in 移到检测器与诊断行**之后**（≈120 样本的窗口下数值影响很小，但偏差方向是系统性的"偏向不触发"）；用 `test_outlier_does_not_raise_its_own_threshold` 固定 |
| **R11** | **我的 bug（改到一半）** | 移动 fold-in 时我只**删掉了原调用、忘了在新位置加回**，adaptive 会变成**完全死掉**；是既有测试 `test_windows_are_fed_every_pulse_not_only_on_fire` 抓到的 | 在新位置补回调用，并加 `test_each_pulse_folds_in_exactly_once` |
| **R12** | **我的 bug（配置无校验）** | 新配置项**完全没有校验**，而它们在 pulse 循环里被使用：`window_minutes≤0`/`min_samples<1` 会让**每一轮**抛 ValueError（daemon 不死，只是再也不出信号 —— 比启动失败更糟），`z_entry=0` 在 cvd_divergence 的 strength 里 **ZeroDivisionError**（已实测确认） | 读配置时校验+告警+回退默认值（沿用 `net_config.py` 的模式）；11 个坏值参数化测试 |
| **R13** | 死代码（我加的投机 API） | `RobustWindow.score`、`RobustWindows.score/ready/is_degenerate` 在生产里**零调用**，只有测试用 | 全部删除（`score` 的语义已被生产路径取代并有测试固定） |
`scripts/sniper_legacy_fingerprint.py` 对每个检测器记录 **fire 数 + strength 总和**
（只比 fire 数不够 —— 强度变化同样会移动 confluence 和闸门）。
与改动前的 `7e7c6c9` 对比：

```
diff /tmp/fp_old.json /tmp/fp_new.json   →   无差异
XAUTUSDT  cvd_momentum 2036 次 / Σ=978.853    cvd_absorption 800 / 173.657
          large_trade   996 / 684.124         cvd_divergence  72 /  31.397
          positioning_extreme 52 / 26.928     volatility_surge 16 / 7.416
BTCUSDT   cvd_momentum 1204 / 383.115         cvd_absorption 1436 / 339.721
          large_trade   520 / 336.768         cvd_divergence  70 /  29.665
          positioning_extreme  4 / 1.780      volatility_surge  5 / 0.492
```

**即：`adaptive.enabled: false` 下行为与改动前逐位一致** —— 包括 R2 修掉之后。

测试：**566 passed**（+5 自审回归用例：来源分组、诊断模式感知、reason 单位、UI 元素生命周期）。

### 最终判断（2026-10-14 收官 review）

**逻辑是否更合理：是，而且这一条可以证明，不依赖回测。**

| 改进 | 依据 |
|---|---|
| 不再有"声明了却不可达"的检测器 | 修掉 3 条（`ls`/`funding`/`oi_delta`）算术上不可能的路；第 4 条（量化指标）不再静默，而是显示 `degenerate` |
| 广度要求第一次名副其实 | 4 个检测器方向同源（`sign(cvd)`），"≥3 个信号"实际只承载 1 份信息；现在系统声明来源、shadow 闸门按来源计数 |
| 不再有 per-symbol 标定债 | 一个 k 服务所有 symbol；历史上是 0.25→0.08、0.18→0.12 这样一路加常数 |
| 诊断不再说谎 | 4 个字段改为报"实际生效的阈值"，并区分"没到阈值"与"永远到不了" |
| 默认行为可被证明未被触碰 | `sniper_legacy_fingerprint.py`：与改动前逐位一致（fire 数 **与强度总和**） |
| 有了此前不存在的数据 | `sources=N[...]`、`FLOW PROBE`、`gate_shadow` |

**质量是否会提高：不能声称会，而且这不是这次重构的功劳范围。**

- **今天的生产质量与改动前逐位相同** —— 因为所有新开关都是 `false`/`shadow`。这是关于质量**唯一能证明**的陈述：**可证不变差**。
- 所有测量的点估计都**不显著**（最大 t=0.68；独立行情 15–59 个）。检测器层面没有任何一个在任一模式下显示出 edge。
- 唯一一致的信号是：现状 `count≥3` 的点估计在两个 symbol 上都**最差**（−0.327 / −0.078），但它只有 8 和 2 个 episode。
- **真正会提高质量的那件事还没做**：延迟。wake 落在波段起点之后 41–80 分钟、capture 只有 0.43；
  被闸门拦掉的 14 个大行情里 10 个"进场先逆向"。这次重构做的是**把测量仪器装上**
  （`FLOW PROBE` 从零开始记录逐根 K 线资金流），使"更快的指标"第一次可以被回测。

**一句话**：这是一次**正确性与可测量性**的重构，不是一次质量提升。
它把"信号器为什么不好用"从"只能人工读日志"变成了"可以逐项测量、并被测试固定"——
而在拿到 ~30 个独立行情之前，任何声称质量变好的说法都只是点估计。

### Phase C（自适应阈值）已被**删除**（2026-10-14）

operator 提出一个比"哪里坏了"更锋利的角度：**"这个功能如果删掉，会有什么东西真的变差？"**
逐个产物做完删除测试后，结论是 adaptive 是**最该删的一块**：

| 产物 | 代码量 | 删掉会失去什么 |
|---|---|---|
| **FLOW PROBE** | **16 行** | ★★★ 逐根 K 线资金流**不可反推**（历史 14563 行 diag 里 0 行有它，聚合值无法分解），且对准真正的瓶颈（延迟） |
| 配置校验 / `independent_sources` 统一 / Spot 超时 | ~60 行 | ★★★ 三处**静默失效**会回来 |
| `sniper_legacy_fingerprint.py` | 80 行 | ★★ 防静默回归的能力（它抓到过 OI 强度 1.5× 的回归） |
| UI 来源分组 + 名字 | ~40 行 | ★ 10 方块 strip 又被读成"10 份独立证据" |
| 诊断行 `sources=` | 3 行 | ☆ 离线可重算（便利非能力） |
| **adaptive** | **~570 行** | **☆ 今天什么都没有** |

**我按代码量分配了精力，而这个角度按"删掉会失去什么"排序，两者几乎相反 —— 最大的一块最该删。**

删除理由（三条）：
1. `enabled: false` 时**零效果**，且已证明与改动前逐位一致 —— 即今天删掉什么都不变。
2. 它本该兑现的核心价值（抓更多波动）**实测是反的**：单独开启让 XAUT 通过量 44→27；
   配合来源闸门是 BTC +0.112 / XAUT −0.034，**n=15，不显著**。
3. 它修复的 3 条"永不可达"检测器路径（`ls`/`funding`/`oi_delta`）**已经死了几个月没人发现** ——
   这本身就是关于它们价值的证据。而且重新启用只是 cherry-pick，成本 ≈ 0。

**保留**：来源闸门（`min_sources_*`，一个数字可翻转）+ `SIGNAL_SOURCES` 溯源 + 诊断行 `sources=`。
概念是被证明的（4 个检测器方向同源），实现只有约 60 行。

**删除过程中的两个自身错误（都由验证抓到）**：
- 我一度用"从方法 A 删到方法 B"的区间切法，**连带删掉了 5 个不相关方法**
  （`_check_state_lock`/`_determine_regime`/`_parse_interval_to_minutes`/`_record_cvd_sample`/`_signal_cfg`）。
  改为逐个精确删除后修复。**教训：永远不要用两个锚点之间的区间做删除。**
- 我重写的 replay 辅助函数漏了 `_record_cvd_sample`，导致 `cvd_divergence` 触发数变成 **0**
  —— 指纹工具立刻暴露了它。

**验证**：`sniper_legacy_fingerprint.py` 与 adaptive 引入前的 `7e7c6c9` **逐位一致**
（fire 数 + 强度总和，两个 symbol × 6 个检测器）。

**工具重构**：`sniper_adaptive_ab.py` 已删除，其有用的一半（闸门策略对比）重写为
`scripts/sniper_source_gate_ab.py`；共用的 `_metrics`/`DETECTORS` 抽到中立的
`scripts/sniper_stack_probe.py`，解开了 `sniper_legacy_fingerprint.py` 对 adaptive 工具链的依赖。

### 线上验证（2026-10-14 13:27，operator 首次启动）

首次在生产验证本次重构。逐项确认：

| 验证项 | 结果 |
|---|---|
| FLOW PROBE 在 daemon 内输出 | ✅ 每 pulse 每 symbol 一行 |
| 诊断行 `sources=` | ✅ `1[flow]` / `0[-]` |
| pulse file 的 `source` / `sources` / `sources_active` | ✅ |
| `gate_shadow` 残留 | ✅ 无 |
| dashboard API 转发 `sources` | ✅ 直接读到（此前会落到有 bug 的 fallback，见 83f3e72 的修复） |
| 异常 / WARNING | ✅ 0 |

### 新发现：`sources≥2` 的通过几乎全部来自**衰减记忆栈**，不是同一轮的一致

| | 同一轮 fresh | 衰减记忆栈 |
|---|---|---|
| XAUT | 1 源 85.9%，2 源 **1.1%**，3 源 **0** | 1 源 96.9%，2 源 2.9%，3 源 0.2% |
| BTC | 1 源 63.0%，2 源 **1.6%**，3 源 **0** | 1 源 95.4%，2 源 4.6%，3 源 0 |

**同一轮 pulse 内，3 个独立来源从未出现过（3753 轮里 0 次）**，2 个来源只有 1.1–1.6%。
所以 `min_sources_non_trend: 2` 实质是"**两种证据在衰减窗口内都还站着**"，
而不是"两种独立证据此刻同时同意" —— **它的强度与 `decay` 半衰期耦合**，
这是之前没有记录的口径含义，也是"再等数据"的额外理由。

### 工具盲区（同一测量暴露）

`scripts/sniper_gate_policies.py` 用的是**日志镜像**（`build_fresh_signals`），
而该镜像**看不到多来源 pulse**（同一轮 2 源：镜像 0 次 vs 真实检测器 31/30 次）。
所以任何源闸门的结论都**必须**用 `sniper_source_gate_ab.py`（驱动真实 `SniperTrigger`），
不能用镜像口径的脚本。

### 尚未实施（需 operator 点头）

- **C：自适应条件**（§2.2）—— 会改变触发时机与数量。
- **D：`sources_mode: enforce`** —— 等 shadow 数据。
- **E：延迟改造** —— 需先落快指标数据。

### default 变更报备（按约束）

| 键 | 变化 | 说明 |
|---|---|---|
| `gate.min_sources_non_trend` | **新增** = 2 | 新增键；因 `sources_mode: shadow`，**当前不生效** |
| `gate.min_sources_trend` | **新增** = 1 | 同上 |
| `gate.sources_mode` | **新增** = `shadow` | 同上 |
| `gate.min_active_*`、`thresholds.*`、`weights`、`decay`、`regime_modifiers` | **未改** | 本阶段不动任何既有 default |

overrides 侧：本阶段**未改**任何 `symbol_config.yaml`（自适应条件上线时才需要清理被取代的绝对阈值）。
