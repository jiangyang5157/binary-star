# Code Review — cvd_divergence 口径修正 + Binance HTTP 超时修复

审查日期：2026-10-06 ｜ 审查对象：未提交的工作区改动 ｜ 状态：**可以上生产**

审查方式：逐行读改动 + 对每一处可验证的断言做独立复算（replay 真实 pulse 序列 / 直接读第三方库源码 /
故意把 bug 改回去跑测试）。审查过程中发现 3 个缺陷（2 个在本次改动内部），已修复；
发现 1 块测试覆盖缺失，已补齐。

改动范围：7 个修改文件（+258/−32）+ 3 个新增文件。

```
config/global_config.yaml                   |  15 +++-
config/symbol_config.yaml                   |  25 +++++-
src/infrastructure/binance/margin_client.py |  12 +--
src/infrastructure/binance/net_config.py    |   5 +-
src/sniper/trigger.py                       |  88 +++++++++++++++++--
tests/unit/test_symbol_resolver.py          |  16 ++--
tests/unit/test_trigger.py                  | 129 +++++++++++++++++++++++++++-
新增: tests/unit/test_binance_timeouts.py
新增: scripts/sniper_signal_latency.py
新增: docs/sniper_signal_latency_20261005.md
```

---

## A. `src/sniper/trigger.py` — 正确性

| # | 项 | 结果 |
|---|---|---|
| A1 | `_cvd_reference` 选点逻辑（lag±tol、取最近、平手取先者） | ✅ |
| A2 | 缓冲区写入时机：`evaluate()` 在检测器**之前**记录本 pulse，所以当轮样本不会成为自己的参考（age=0 被 tol 排除） | ✅ |
| A3 | gap 后是否清缓冲：全仓只有一个 `reset_state()` 调用点（`run_sniper.py:282` 的 gap 分支），缓冲随之清空 | ✅ |
| A4 | 失败方向安全：跨重启/休眠的旧样本因 age 远超 tol 被拒 → 检测器**变暗而不是误触发**；系统时钟回拨同样只会变暗 | ✅ |
| A5 | **日志格式兼容**：3 条新 reason 字符串全部过一遍现有解析器（`LINE_RE` → `DIAG_RE` → `parse_diag`），字段数仍为 14，`" | "` 分隔未被破坏（`\|dCVD\|` 不含"空格-竖线-空格"） | ✅ |
| A6 | `prev` 参数变为未使用 —— 检测器注册表按位置传 3 个参数，删参数会破坏签名，保留是正确的 | ✅ |
| **A7** | **代码内默认值 `default=0.6` ≠ global config 的 `0.30`** —— config key 缺失时会静默落到另一个工作点 | ⚠️ **已修**（→ 0.30，与 global 一致） |
| **A8** | **`deque(maxlen=64)` 按"pulse 数"写死，而 lag 按"分钟"计算** —— 2 分钟 cadence 下 64 条 = 128 分钟够用；但若 micro 周期改成 ≥2h，64 条永远够不到 15 分钟前 → 检测器**永久变暗且无任何报错** | ⚠️ **已修**（`maxlen=max(64, lag*3)`；当前配置下仍为 64，生产行为零变化） |
| A9 | 检测器抛异常时 `_cvd_div_reason` 残留上一轮的值，diag 行显示过期原因 | ℹ️ **不处理**，见下 |
| A10 | 阈值 ≤ 0 的边界行为 | ℹ️ **不需要处理**，见下 |

### A9 — 陈旧的诊断原因（决定：不处理）

`_cvd_div_reason` 是一个**纯诊断用的旁路**：检测器的返回类型契约是
`Optional[SignalCard]`，没法回溯"为什么没触发"，所以它把原因存在实例上，
`_log_signal_diagnostics` 再读出来拼进 `cvd_divergence=R:<reason>`。

陈旧只发生在一种情况：检测器**抛异常**。`evaluate()` 的注册表循环是

```python
for detector in self._signal_detectors:
    try:
        card = detector(current_metrics, prev_metrics, now)
        ...
    except Exception as e:
        logger.warning(f"detector {detector.__name__} failed | error={e}")
```

异常被吞掉、card 不入列，但 `_cvd_div_reason` 还停在上一个 pulse 写下的值。
于是这一轮的 diag 行会打印**上一轮的**具体原因（例如
`|dCVD|=0.120<=0.35 (ref 15m ago)`），看上去像"检测器正常、只是没到阈值"，
而实际是它崩了。

**为什么不处理：**

1. **对交易决策零影响。** 抛异常时该检测器本来就不贡献任何信号；reason 只影响日志文本。
2. **日志里已经有真话。** 同一轮 `evaluate()` 紧接着就会打
   `WARNING detector _detect_cvd_divergence failed | error=...` ——
   崩溃是**自曝**的，只是不在同一行。扫 diag 行的人可能被误导，扫告警的人不会。
3. **修复要动共享代码。** 干净的修法是在上面那个通用 `except` 里按检测器名把 reason 置成
   "error"，但那属于为 9 个检测器共用的一条诊断旁路做改造，超出本次范围。
   把 reason 在函数开头重置成某个占位符，则会让"崩溃"和"未到阈值"在日志里更难区分。

**结论：记录在案，不修。** 若将来真的在日志里看到陈旧 reason，必定同时有一条
`detector ... failed` 告警 —— 那时再修也不迟，而且届时会知道是哪个输入导致的。

### A10 — 阈值 ≤ 0（决定：不需要处理，且原判断有误）

原以为 `threshold == 0` 会走到 `strength = |Δ| / (threshold × 3)` 的除零崩溃。
实测（直接改 config 后调用 `_signal_cfg`）**这条路不可达**：

```
config=   0.0 -> _signal_cfg returns 0.3     # 0 是 falsy，被当成"没配置"而替换成 default
config=     0 -> _signal_cfg returns 0.3
config=  -0.5 -> _signal_cfg returns -0.5    # 负数是 truthy，原样通过
config=  0.35 -> _signal_cfg returns 0.35
```

`_signal_cfg` 的收尾是 `return node if node else default`，所以配置成 `0` 会被
**静默替换成默认值**，永远到不了除零。

配置成**负数**也不会崩：`abs(cvd_delta) <= -0.5` 恒为假（abs ≥ 0），于是跳过阈值判断，
`strength` 变成负数，而下游 `_dir_score` 有 `strength >= MIN_STACK_STRENGTH (0.15)` 的过滤
→ 该信号被丢弃。即"安静地失效"，不是崩溃。

**顺带发现一个值得记住的配置层陷阱（先于本次改动存在，非回归）：**
**把阈值设成 0 不能关掉一个检测器** —— 它会静默回落到默认值（对 cvd_divergence 就是 0.30）。
要停用只能把 weight 设为 0 或从注册表移除。

同一性质适用于所有走 `_signal_cfg` 的阈值（`cvd_extreme_threshold`、`large_trade_zscore` 等），
且**没有任何一处做数值校验**。若要做校验，应该在 `_signal_cfg` 里统一拒绝非正数，
而不是给 cvd_divergence 打补丁 —— 属于独立议题。

---

## B. Config 合理性

| # | 项 | 结果 |
|---|---|---|
| B1 | 旧 key `cvd_divergence_tick_delta` 是否还有引用：全仓（含 json/md/data）只剩本次的说明注释 + `.superpowers/sdd/*.diff` 历史 diff | ✅ 干净 |
| B2 | 是否有地方在运行时加载历史/版本化 config 快照：全部经 `resolve_project_root()/config/...` | ✅ 无 |
| B3 | 解析后取值 XAUT 0.35 / BTC 0.16 / 兜底 0.30，经真实 `resolve_config` 验证 | ✅ |
| **B4** | **BTC 注释里我自己的数字写错了**：`thr=0.09 → 43 次/7.2d`（实际 **309 次 = 42.9/天**）、`~p97`（实际 **p91**） | ⚠️ **已修** |
| B5 | **接受带余量**（6–12 次/天/symbol）：XAUT 7.8、BTC 7.6，都在带内 —— 但 XAUT 到 0.299 就撞线（+15%），**BTC 到 0.147 就撞线（+8%），\|ΔCVD\| 尺度膨胀 2% 即变 14.2/天** | ⚠️ **已记录**，无护栏（见 E2） |
| B6 | 接受带 + 撞线阈值 + 复核方法已写进两个 symbol 的 config 注释 | ✅ |

最终验证（用真实 pulse 序列回放**已上线代码**，非离线近似）：

```
XAUTUSDT: thr=0.35  fires=56 ( 7.8/day, band 6-12: OK)  14% at candle start, Poisson p=0.340  -> 无偏置
BTCUSDT:  thr=0.16  fires=55 ( 7.6/day, band 6-12: OK)  29% at candle start, Poisson p=0.002  -> 残留偏置
```

对照：旧 2 分钟口径是 XAUT 63 次 / BTC 60 次（8.8 / 8.3 每天），也都在带内 ——
本次改动**没有把量级踢出接受带**。

---

## C. `margin_client.py` / `net_config.py`

| # | 项 | 结果 |
|---|---|---|
| C1 | 确认真实开关链路：`Spot(**kwargs)` → `API.__init__(timeout=)` → `self.timeout` → `send_request()` 内 `"timeout": self.timeout` → `_dispatch_request(...)(timeout=...)`。`send_request` 是签名/非签名请求的**唯一共同路径** | ✅ |
| C2 | `self.timeout` 为新增属性，类中原本没有，无命名冲突；`API.__init__` 不联网 | ✅ |
| C3 | 另两条构造路径（futures 认证 / 公开）本就走 `UMFutures(timeout=...)` | ✅ |
| C4 | **此前没有任何测试覆盖 HTTP 超时** —— 正是死代码得以存活的原因 | ⚠️ **已补** 11 个用例 |

**旧写法为什么是死代码：** `Spot` 上不存在 `REQUEST_TIMEOUT` 属性
（`hasattr(Spot, "REQUEST_TIMEOUT") == False`），赋值只是往实例上挂了个没人读的字段，
生产日志里持续出现 `Read timed out. (read timeout=None)` —— `None` 在 `requests` 里等于"永远等"。

**回归测试的有效性已反向验证**：把 `margin_client.py` 改回旧的死代码写法 → 2 条测试失败；
恢复 → 11 条全过。断言打在"timeout 是否真的进到 HTTP dispatch"，而不是"属性是否存在"，
因为前一次的教训正是"属性存在但没人读"。

---

## D. 测试

- 全量 **505 passed**（原 494 + 11 超时 + 12 candle-lag + 1 reset）。
- candle-lag 覆盖：参考点选择 / 容差边界 / 接近者优先 / **换手跳变不再触发**（核心回归）/
  真实漂移会触发 / warmup 期间变暗 / `evaluate()` 逐 pulse 记录 / 缺 price 不记录 /
  lag 从 micro 周期推导。
- 超时覆盖：三个客户端（futures 认证 / futures 公开 / margin）都把 config 值送到 dispatch，
  且永不为 `None`；config 非法值（garbage / None / 0 / 负数）回落默认。

---

## E. 残留风险（未解决）

- **E1 — BTC 尾部偏置**：55 次里 29% 落在 13% 的时间里，p=0.002。**有意接受的折中**（保量级），
  不是遗漏；替代方案（降到 0.09）会把量级推到 42.9/天，远超接受带。
- **E2 — fire 率没有护栏**：目前是"手动标定 + 注释记录"。波动率 regime 一变就可能越线。
  两条路：分析侧（给 `sniper_signal_latency.py` 加一条 band 断言，改动小、零生产风险）；
  生产侧（定期打点告警，属新行为，需单独批准）。
- **E3 — 每次启动/gap 之后 cvd_divergence 变暗约 15 分钟**：该修法不可避免的代价。
- **E4 — 样本量**：整个"检测器质量"问题仍建立在约 20 个独立行情上；本次改动没有、也无法解决它。
- **E5 — 配置层无数值校验**（见 A10）：影响所有 `_signal_cfg` 阈值，先于本次改动存在。

---

## F. 上生产前的检查清单

1. 当前运行的 daemon 仍是**旧代码**（2026-10-03 启动）→ **重启 sniper**（dashboard 不需要）。
2. 重启后前约 15 分钟，日志应出现 `cvd_divergence=R:warmup(no same-phase sample yet)`。
3. 之后应变成 `cvd_divergence=R:|dCVD|=...<=0.35 (ref 15m ago)` 或 `F:x.xx`
   （不再出现旧的 `R:no-prev/div-low`）。
4. 跑一两天后，**用生产新日志复跑一次** `scripts/sniper_signal_latency.py`，确认
   fire/天仍在 6–12 带内、且 XAUT 的边界占比仍贴近 13%。
   **本次所有验证都是在 replay 上完成的，生产实测尚未做。**

---

## 附：本次审查修复的缺陷清单

| # | 位置 | 缺陷 | 处置 |
|---|---|---|---|
| 1 | `src/sniper/trigger.py` | 代码内默认阈值 0.6 与 global config 0.30 不一致，key 缺失时静默落到另一工作点 | 已改为 0.30 |
| 2 | `src/sniper/trigger.py` | 采样缓冲按 pulse 条数写死，micro 周期变长时会永久变暗且无报错 | 已改为随 lag 缩放 |
| 3 | `config/symbol_config.yaml` | BTC 注释中 0.09 的 fire 量级写错（43 次/7.2d ← 实为 309 次），分位写错（p97 ← 实为 p91） | 已改正 |
| 4 | `tests/` | HTTP 超时零覆盖，导致"写了没人读"的死代码长期存活 | 新增 11 个用例，并反向验证其可失败 |
