# 建议 review + 修改计划（BTC / XAUT pre-AI gate）

本文分两部分：
**Part A** 逐条 review 我上一轮给出的全部建议（含**撤回**与**降级**）；
**Part B** 给出可执行的修改计划（精确到文件/行/预期效果/验证/回滚）。

review 用的新证据来自 `scripts/sniper_gate_policy_experiments.py`
（输出见 `docs/sniper_gate_policy_experiments_20260917.md`）：在同一个已验证的 replay 上，
把 10 种候选策略跑同一段 12.5 天，比较 **wake 数（LLM 成本）** 与
**1h ATR 游程质量**（MFE/MAE 中位、先摸 +1ATR / 先摸 −1ATR 比例）
以及 **去漂移超额收益**（候选的 30-pulse 定向收益 − 同 run 同方向全体 pulse 的均值，用于剔除行情单边漂移）。

---

## Part A — 逐条 review

| # | 上一轮建议 | review 结论 | 依据 |
|---|---|---|---|
| R1 | XAUT `min_active_non_trend` **保持 3**，不要降到 2/1 | ✅ **保留，但理由必须改写** | 结论对，理由错。见 A.1 |
| R2 | XAUT `min_active_trend` 保持 1 | ✅ 保留 | 12.5 天 0 次 trending wake，无数据可标定 |
| R3 | BTC `min_active_non_trend` 保持 3 | ⚠️ **降级为"不要动它"** | 非趋势 wake 只有 2 次/12.5 天，任何取值都不可标定；"保持 3"和"保持 2"都谈不上有证据 |
| R4 | BTC `min_active_trend` 1 → **2** | ❌ **撤回** | 见 A.2 |
| R5 | 修正 `symbol_config.yaml` 的注释 | ✅ 保留（零风险，性价比最高） | 注释与取值不符，git 可证 |
| R6 | 把"信号个数"换成"跨类别 ≥2" | ✅ **保留并具体化**，但先影子模式 | 见 A.3 |
| R7 | emergency 0.80 → 0.90 | ⚠️ **降级为可选**，我上一轮夸大了 | 见 A.4 |
| R8 | 收紧 confluence 阈值（"入口太松"） | ❌ **撤回** | 见 A.5 |
| R9 | 补 gate FAIL / cooldown 拦截日志 | ✅ **升为第一优先** | 无此日志则一切评估只能靠 replay |
| R10 | （新增）阻止演化循环继续自动改写该参数 | ✅ 新增 | git 显示 7 月以来 2↔3 反复横跳 ≥6 次 |

### A.1 `min_active_non_trend: 3` 不是质量过滤器，只是限流阀

策略回测（XAUT，12.5 天）：

| 策略 | wakes | wakes/天 | MFE 中位 | MAE 中位 | 先摸 +1ATR | 先摸 −1ATR | 去漂移超额 1h |
|---|---|---|---|---|---|---|---|
| P0 gate=3（现状） | 16 | 1.28 | +0.03 | **−1.47** | 6% | **56%** | **−0.207%** |
| P1 gate=2 | 121 | 9.68 | +0.07 | −0.36 | 11% | 36% | −0.052% |
| P4 ≥2 且含非 sign(cvd) 信号 | 55 | 4.40 | +0.12 | −0.61 | 20% | 38% | −0.101% |
| P8 去 gate + 阈值 +0.12 | 247 | 19.76 | +0.08 | −0.29 | 14% | 32% | −0.033% |

**gate=3 那一组在所有质量指标上都是最差的一组**（MAE −1.47 ATR、56% 会先打掉 −1ATR、
超额 −0.207%），每一档更宽松的策略质量都更好。所以：

* "保持 3" 的**正确理由**只有一个：**它把 wake 量压到 1.28/天**。降到 2 是 ×7.6 的
  AI 成本，而边际候选的超额收益仍是负的（−0.052%）——不是"更差"，而是"不值这个钱"。
* 上一轮我写"3 是唯一有效的过滤器 / 它筛出的是更干净的那一类"是**错的**：
  它筛出的是**同一轮 CVD 冲击里堆得最高的那批**（MAE 最大）。
* 同理 "≥3 的 cohort 表现更差" 不能推出 "应该降到 2"，因为降下去仍然 ≤0 期望。

### A.2 BTC `min_active_trend: 1 → 2` 应当撤回

* 收益：12.5 天里只拦掉 1 次 wake（01:43:25，same_dir=1，只有 `boundary_test`）＝ **0.08 次/天**。
* 样本：该结论建立在 **n=4** 的 trending wake 上，且这 4 次全部 NEUTRAL —— 但 BTC 同期
  2 次 ranging wake **也全部 NEUTRAL**。也就是说 **BTC 的问题不是 gate**，
  任何取值都会得到 NEUTRAL。用 gate 去修 BTC 是找错了层。
* 成本：改动会被演化循环再次翻转（见 R10），属于制造 churn 而无收益。
* **结论：不动。** 若一定要动 BTC，应该动 A.3 的规则，或去查 session 层为何 6/6 NEUTRAL。

> 补充发现（值得单独跟进，但不属于本次 gate 议题）：BTC 日志区间价格
> 79605 → 76108（−4.4%），6 次 wake 里 5 次是 BEARISH，方向是对的，
> **session 层 6 次全部返回 NEUTRAL、0 笔交易**。这是 session/prompt 侧的问题，
> 不是 gate 能解决的。

### A.3 规则改造：从"跨类别"改成"方向来源独立"

上一轮我建议"按 FLOW/SIZE/ENERGY/STRUCTURAL/POSITIONING 类别"——**这个分类不成立**，
因为配置把 `large_trade` 归到 SIZE，但它的**方向**取的是 `sign(cvd)`，
与 `cvd_momentum` 100% 同向（XAUT 91/91、BTC 62/62）。
按类别判会把这"同源的两个"当成两票。

**可用的判据是"方向来源"**：`cvd_momentum / large_trade / volatility_surge`
的方向都是 `sign(cvd)`，只应算一票；`cvd_divergence`（`cvd_delta` vs `price_delta`）、
`boundary_test`（VAH/VAL）、`liquidation_hunt`（清算簇）、`positioning_extreme`（ls/funding/oi）
才是独立方向来源。

实测规则 **"同向 ≥2 且其中至少 1 个不是 sign(cvd) 派生"**（P4）：

| symbol | wakes | wakes/天 | MAE 中位 | 先摸 +1ATR | 先摸 −1ATR | 去漂移超额 1h |
|---|---|---|---|---|---|---|
| XAUT（现状 P0） | 16 | 1.28 | −1.47 | 6% | 56% | −0.207% |
| XAUT（P4） | 55 | 4.40 | −0.61 | 20% | 38% | −0.101% |
| BTC（现状 P0） | 2 | 0.16 | −1.87 | 50% | 50% | +0.165%（n=2） |
| BTC（P4） | 16 | 1.28 | −0.34 | 25% | 25% | **+0.134%（n=16）** |

**但有两点必须诚实标注**：

1. **样本时间聚集**：XAUT 的 16 次 wake 里 14 次落在 run 0-2，run 3-5 只有 2 次；
   P4 在下半段只有 2 个样本。所以"P4 更好"主要来自前半段那一个行情片段。
2. **XAUT 的 P4 超额收益仍然是负的（−0.101%）**，只是比现状好；它降低"每次 session 的浪费"，
   但**不构成可交易的正期望**。BTC 的 P4 是本次唯一测到正超额的策略，但 n=16。

→ 因此 R6 **不该直接上线**，应走**影子模式**（Part B Phase 2）。

### A.4 emergency 0.80 → 0.90：我上一轮夸大了

上一轮我写"emergency 是常态入口，16 次 wake 里 7 次靠它绕过 cooldown"。核实后：

* "6.6% 的 pulse 携带 raw ≥0.8 信号" 是 **confluence 越阈层面**的统计，不是 wake 层面。
* wake 层面：XAUT 16 次里 7 次 `emergency=True`，但**真正因 cooldown 生效、只能靠 emergency 绕过的只有 3 次**；
  BTC 是 **0 / 6**。
* 把 emergency 提到 0.90（P3）：XAUT 16 → 14 次 wake，超额 −0.207% → −0.106%。
  变化方向是好的但幅度在噪声内（n=14）。

→ **降级为可选清理项**，不列入本轮必做。

### A.5 "收紧 confluence 阈值" 应当撤回

在 gate=3 保持不变、只抬阈值的扫描下（XAUT）：

| 阈值增量 | wakes | MAE 中位 | 先摸 −1ATR | 超额 1h |
|---|---|---|---|---|
| +0.00 | 16 | −1.47 | 56% | −0.207% |
| +0.06 | 16 | −1.47 | 56% | −0.207% |
| +0.12 | 16 | −1.47 | 56% | −0.207% |
| +0.18 | 16 | −1.47 | 56% | −0.207% |
| +0.24 | 15 | −1.52 | 60% | −0.216% |
| +0.30 | 14 | −1.65 | 64% | −0.218% |

**+0.18 以内 wake 集合一字不变**，+0.30 只少 2 次而且质量更差。
原因：wake 由"cooldown 窗口内第一个越阈 pulse"决定，而那些 pulse 的 conf 都远高于阈值
（XAUT 最低的 wake conf 是 0.53/0.54，ranging 阈值 0.34、squeeze 0.255）。

→ **阈值和 gate 不是独立杠杆**：只要 gate=3 在，抬高阈值只会砍掉本来就不触发的那部分。
我上一轮"入口太松，该收紧入口"的建议在本配置下**无效**，撤回。

---

## Part B — 修改计划

**总原则：本轮不改任何 gate 数值。** 先补齐可观测性 → 冻结参数 → 影子验证规则改造。
所有改动都在 Phase 3 才允许影响交易行为。

### Phase 0 — 可观测性与文档（零行为变更，当天可完成）

#### M1. 修正误导性注释

文件：`config/symbol_config.yaml` 第 50、91 行（`config/global_config.yaml` 167-168 行同步）。

```yaml
# 改前
          min_active_non_trend: 3   # 从 3 降回 2。XAUT 双信号触发频繁，放宽到 ≥2 个同向信号即放行，在非趋势行情保留更多 wake。

# 改后
          min_active_non_trend: 3   # 限流阀（非质量阀）：非趋势 regime 要求 ≥3 个同向活跃信号。
                                    # 2026-09-05~09-17 实测：改 2 → wake 1.28/天→9.7/天，边际候选 1h 超额仍为负；
                                    # 改 1 → 22/天。故保持 3。改动须附 A/B 证据，见 docs/sniper_gate_review_and_plan_20260917.md
```

* 验证：`python3 -c "import yaml;yaml.safe_load(open('config/symbol_config.yaml'))"` 通过；
  `git diff` 只动了注释。
* 回滚：`git checkout -- config/symbol_config.yaml`。

#### M2. 补 gate FAIL 与 cooldown 拦截日志（**本计划第一优先**）

文件：`src/sniper/trigger.py`

1. **gate 拦截**（约 1332-1339 行）：现在 `gate_result, _ = self._run_pre_ai_gate(...)`
   把原因丢掉了，且 FAIL 后静默。改为保留 reason 并打 INFO：

```python
        if should_trigger:
            gate_reason = ""
            try:
                gate_result, gate_reason = self._run_pre_ai_gate(
                    current_metrics, all_signals, dominant_direction, regime
                )
            except Exception as e:
                logger.warning(f"pre-AI gate crashed | error={e}")
                gate_result, gate_reason = "FAIL", f"crashed:{e}"
            if gate_result == "FAIL":
                logger.info(
                    "[%s] PRE-AI GATE FAIL | %s | conf=%.2f | dir=%s | regime=%s | fresh=%d",
                    self.symbol, gate_reason, confluence_score,
                    dominant_direction.value, regime, len(fresh_signals),
                )
                should_trigger = False
```

2. **cooldown 拦截**（约 1322-1326 行）：`engine.evaluate()` 会把 cooldown 的影响藏进
   `should_trigger`，导致"本来该醒但被冷却压住"完全不可见。在 `effective_cooldown` 为真时补一条：

```python
        effective_cooldown = cooldown_active and not cooldown_break
        self.cooldown_active = effective_cooldown
        confluence_score, dominant_direction, should_trigger = self.engine.evaluate(
            all_signals, regime, is_cooldown_active=effective_cooldown
        )
        if effective_cooldown:
            threshold = self.engine.effective_threshold
            if confluence_score >= threshold:
                logger.info(
                    "[%s] COOLDOWN BLOCK | %s | conf=%.2f >= thr=%.3f | dir=%s | regime=%s",
                    self.symbol, cooldown_reason, confluence_score, threshold,
                    dominant_direction.value, regime,
                )
```

* **规模预估**：XAUT 606 次 gate 拦截 + 43 次 cooldown 拦截 / 12.5 天 ≈ **52 行/天**，可接受。
* 验证：`pytest tests/unit/test_trigger.py -q` 全绿（日志不改变返回值）；
  重启 daemon 后 `grep "PRE-AI GATE FAIL" data/prod/sniper.log | wc -l` > 0，
  且数量与本文 §4 的 606/280 同一量级（±20%）。
* 回滚：`git revert` 该 commit（纯日志，无状态影响）。

### Phase 1 — 冻结参数 + 让它别再被自动改回去

#### N1. 写下"冻结"决定

在 `config/symbol_config.yaml` 两个 symbol 的 `gate` 段上方各加一行注释：

```yaml
        gate:
          # FROZEN 2026-09-18：本轮不改数值（依据 docs/sniper_gate_review_and_plan_20260917.md）。
```

验证：`git diff` 仅注释。

#### N2. 阻止演化循环继续改写这两个 key（需你确认是否接受）

现状：`run_patch.py` 读演化提案的 `config_patch`，经
`src/config/symbol_resolver.patch_config()` 写进 `symbol_config.yaml` 的 overrides。
git `-L` 追踪显示该值 **7/18 引入为 2 之后被改写 5 次**
（7/25 2→3、7/27 3→2、7/28 2→3、8/25 3→2、8/26 2→3），
**每次都没有 A/B 证据**，注释也一直没跟着更新——这才是注释骗人的根因。

建议在 `run_patch.py` 的应用循环里加一条 denylist（约 6 行）：

```python
FROZEN_KEYS = {
    ("sniper.signal_stack.gate", "min_active_non_trend"),
    ("sniper.signal_stack.gate", "min_active_trend"),
}
...
    if (t_path, key) in FROZEN_KEYS and not os.environ.get("BS_ALLOW_FROZEN_PATCH"):
        logger.warning(f"patch SKIPPED (frozen) | key={key} | path={t_path}")
        continue
```

* 验证：新增单测 `tests/unit/test_run_patch_frozen.py`——喂一个含冻结 key 的 proposal，
  断言 `symbol_config.yaml` 未被修改、日志出现 SKIPPED；再设 `BS_ALLOW_FROZEN_PATCH=1` 断言可写入。
* 回滚：删掉该常量与判断。
* **权衡（需要你拍板）**：这会改变演化管线的行为，好处是参数不再随机漂移，
  代价是以后想调也必须走人工。若你更希望保持演化自由，可只做 N1 不做 N2。

### Phase 2 — 影子模式验证"方向来源独立"规则（2 周，不影响交易）

#### S1. 加配置开关，默认关闭

`config/global_config.yaml` 的 `sniper.signal_stack.gate` 下新增：

```yaml
      require_independent_direction: false   # true = 同向信号中至少 1 个方向不来自 sign(cvd)
      shadow_require_independent_direction: true   # 只记录"若开启会怎样"，不影响触发
```

`src/sniper/trigger.py::_run_pre_ai_gate()` 中，在现有 `same_dir_active` 计算之后（约 610-626 行）。
先在模块级常量区（`MIN_STACK_STRENGTH` 附近，第 157 行）加一个常量，**不要**放进函数体（每 pulse 都会调用）：

```python
# Signals whose direction is literally sign(cvd) — they carry one vote, not N.
CVD_DERIVED_SUBTYPES = frozenset({'cvd_momentum', 'large_trade', 'volatility_surge'})
```

再在 gate 内插入：

```python
        # 方向来源：sign(cvd) 派生的信号只算一票
        has_independent = any(s.sub_type not in CVD_DERIVED_SUBTYPES for s in same_dir_active)
        if gate_cfg.get('shadow_require_independent_direction', False):
            if min_active > 0 and len(same_dir_active) >= min_active and not has_independent:
                logger.info(
                    "[%s] GATE SHADOW | independent-direction rule WOULD BLOCK | "
                    "regime=%s | dir=%s | active=%s",
                    self.symbol, regime, direction.value,
                    [s.sub_type for s in same_dir_active],
                )
        if min_active > 0 and len(same_dir_active) < min_active:
            return "FAIL", (...)
        if gate_cfg.get('require_independent_direction', False) and not has_independent:
            return "FAIL", (
                f"MIN_ACTIVE_INDEPENDENT: regime={regime} has {len(same_dir_active)} "
                f"signals in {direction.value} but all derive direction from sign(cvd)"
            )
```

* 验证：`pytest tests/unit/test_trigger.py -q`；
  新增 3 个单测覆盖 `require_independent_direction=False/True` 与影子日志。
* 影子开启后触发行为**完全不变**（`require_independent_direction` 仍为 false）。

#### S2. 验收（14 天后用现有 replay 复算）

```bash
python3 scripts/analyze_sniper_gate.py --json /tmp/gate.json --out docs/sniper_gate_evidence_YYYYMMDD.md
python3 scripts/sniper_gate_policy_experiments.py
```

**上线门槛（全部满足才把 `require_independent_direction` 打开）**：

| symbol | 门槛 |
|---|---|
| BTCUSDT | 影子期 wake ≥ 10 次；1h"先摸 −1ATR"比例 < 35%；去漂移超额 1h > 0 |
| XAUTUSDT | 影子期 wake ≥ 30 次；1h"先摸 −1ATR"比例从 56% 降到 < 45%；去漂移超额 1h > −0.05% |
| 两者 | 影子期内真实成交的审计结果中 TP_HIT ≥ 1 |

若 14 天后 BTC 达标 → **只对 BTC 打开**；XAUT 不达标则保持关闭（XAUT 目前没有正期望证据）。

#### S3. 回滚

把 `require_independent_direction` 设回 `false` 即可（配置级回滚，无需发版）。

### Phase 3 — 可选的低优先清理

| # | 项 | 说明 | 优先级 |
|---|---|---|---|
| C1 | `emergency_threshold` 0.80 → 0.85 | XAUT 实测 16→14 次 wake，方向正确但幅度在噪声内；仅在顺手时做 | 低 |
| C2 | 提高 `cvd_extreme_threshold`（XAUT 0.24）或重标定 strength 饱和 | 治本（emergency 命中率高是标定问题），但需要单独的标定分析 | 低 |
| C3 | 排查 BTC session 层 6/6 NEUTRAL | 方向正确却不下单，属 session/prompt 议题，另开 | 中（独立议题） |

---

## 本轮明确**不做**的事

| 不做 | 原因 |
|---|---|
| ❌ 把 XAUT/BTC `min_active_non_trend` 降到 2 | wake ×7.6 / ×18.5，边际候选超额仍为负（A.1） |
| ❌ 把 XAUT/BTC `min_active_non_trend` 降到 1 | wake 8.8~22/天，且 207 次/12.5 天由 emergency 通道驱动（A.1） |
| ❌ 把 BTC `min_active_trend` 提到 2 | 收益 0.08 次/天，样本 n=4，撤回（A.2） |
| ❌ 提高 confluence 阈值 | gate=3 时 +0.18 以内完全无效（A.5） |
| ❌ 直接上线"方向来源独立"规则 | 时间聚集、XAUT 超额仍为负；先影子（A.3 / Phase 2） |

---

## 执行顺序与工作量

| 顺序 | 项 | 改动量 | 影响面 | 依赖 |
|---|---|---|---|---|
| 1 | M2 补日志 | ~15 行 `trigger.py` | 无（纯日志） | — |
| 2 | M1 修注释 + N1 冻结注释 | 注释 | 无 | — |
| 3 | N2 冻结 denylist（**待你确认**） | ~8 行 + 1 个单测 | 演化管线 | 你的决定 |
| 4 | S1 影子开关 | ~15 行 + 配置 + 3 个单测 | 默认无 | M2 上线后 |
| 5 | S2 14 天复算 | 0 | — | S1 满 14 天 |
| 6 | S3 按门槛开关 | 1 行配置 | 交易行为 | S2 达标 |
| — | C1/C2/C3 | — | — | 另行安排 |

## 验证清单（每个 Phase 结束都跑）

```bash
pytest tests/unit/test_trigger.py tests/unit/test_sniper_daemon.py -q   # 回归
python3 scripts/analyze_sniper_gate.py --out docs/sniper_gate_evidence_$(date +%Y%m%d).md
python3 scripts/sniper_gate_policy_experiments.py
git diff --stat    # 确认改动范围与计划一致
```
