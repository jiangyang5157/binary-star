# Audit Remediation Tracker — Impact × Effort Matrix

**基于**: `docs/audit_report_20260626_030000.md` (74 findings)  
**更新**: 2026-06-26 (本次会话已修复 7 项)

---

## 已修复 ✓ (本次会话)

| # | Finding | Effort |
|---|---------|--------|
| D3-F6 | 信号 detector 异常日志 DEBUG→WARNING | 1行 |
| D1-F2 | NaN 穿透 `if atr` 守卫 (market_observer) | 3行 |
| D1-F3 | NaN 进入 scipy find_peaks (volume_profile) | 2行 |
| D1-F5 | Keltner ATR NaN squeeze_factor (market_regime) | 3行 |
| D1-F7 | NaN 穿透 trailing stop 守卫 (order_executor) | 4行+import |
| D1-F1 | TriggerResult 解包崩溃 (simulation_sampler) | 3行 |
| - | 新增每脉冲信号诊断日志 SIGNAL_DIAG | ~100行 |

---

## 待修复 — Impact × Effort 矩阵

**Effort 定义**:
- **1L** = 一行代码 (<5 min)
- **S** = Small，单文件小改动 (<30 min)
- **M** = Medium，多文件或需要测试 (<2 hr)
- **L** = Large，架构级改动或大量测试 (<1 day)
- **XL** = 需要数天的新测试/重构

### 🔴 CRITICAL (还剩 4 项)

| # | Finding | File | Effort | 改动 |
|---|---------|------|--------|------|
| D4-F1 | 初始 OCO 失败不紧急平仓，仓位裸露 | `order_executor.py:367` | **1L** | 加一行 `execute_market_close` + `return {}` |
| D4-F2 | TP/SL 缺失静默返回，仓位裸露 | `order_executor.py:321` | **1L** | 同上 |
| D3-F1 | `except: pass` 吞掉 shutdown 异常 | `run_session.py:158,181` | **1L** | 改成 `except Exception as e: logger.warning(...)` |
| D5-F1 | Dashboard 写端点零认证 | `dashboard/api/*.py` + `server.py` | **M** | 加 FastAPI dependency auth guard；改 host=127.0.0.1；降 anonymous 权限 |

### 🟠 HIGH (17 项，已修 4 项 NaN 相关，剩 13 项)

| # | Finding | Effort | 改动 |
|---|---------|--------|------|
| D1-F4 | `find_nodes` bin width 用错分母 | **1L** | `len(prices)` → `resolution_bins` |
| D2-F1 | Prompt 矛盾：counter-trend vs Sweep&Fade | **1L** | `session.md` 加一行 exception clause |
| D2-F2 | 价格输出无数值校验 | **S** | `math_fact_checker.py` + `order_executor.py` 加 `math.isfinite()` |
| D3-F2 | BinanceFuturesClient.close() 是空函数 | **S** | 实现 `close()` 调用 SDK cleanup |
| D3-F3 | 裸 bracket config 访问会 KeyError | **M** | 8+ 处改 `.get()` + startup validation |
| D3-F4 | 止损突破用 float 比较无 epsilon | **S** | `abs(price - sl) < epsilon` |
| D3-F5 | 5 处 `datetime.now()` 无 timezone | **S** | 全改成 `.now(timezone.utc)` |
| D3-F7 | 数据 fetch 失败返回 `[]` 掩藏根因 | **S** | raise KeyboardInterrupt；return None |
| D4-F3 | cancel→replace 未重新验证仓位数量 | **S** | 加一个 `get_symbol_position` 调用 |
| D4-F4 | cancel 后 get_position 返回 None 不平仓 | **1L** | 加 `execute_market_close` |
| D4-F5 | cancel-replace 异常处理不平仓 | **1L** | 加 `execute_market_close` |
| D5-F2 | 整个 `data/` 目录作为静态文件暴露 | **S** | 改为只 mount 特定子目录 |
| D5-F3 | `data_root` 参数可任意目录遍历 | **S** | allowlist + `.resolve()` 前缀检查 |

### 🟡 MEDIUM 高价值项 (31 项中挑出最值得修的 10 项)

| # | Finding | Effort | 为什么值得修 |
|---|---------|--------|-------------|
| D4-F9 | NaN 静默抑制所有 trigger | **1L** | `confluence_score` 包一层 `math.isnan()` 检查 |
| D4-F7 | 订单数量不遵守 Binance step size | **S** | `round(qty)` → `floor(qty/step)*step` |
| D4-F8 | 缺少 min_notional 校验 | **S** | 下单前验证 `qty*price >= min_notional` |
| D1-F6 | last_trigger_score 永不清零 | **S** | cooldown 过期时 reset |
| D4-F6 | 市场结构缺失时 gate 被绕过 | **S** | 无 HVN 时 fallback 到 LVN/POC 或 FAIL |
| D4-F10 | 尾随止损 level 无序校验 | **1L** | __init__ 中 `assert l1 < l2 < l3` |
| D2-F7 | 三个 prompt 都缺 few-shot example | **M** | 各加一个样本 JSON，降低 malformed-JSON 率 |
| D3-F9 | warmup 验证失败 DEBUG only | **1L** | `logger.debug` → `logger.warning` |
| D3-F11 | evolver bare `except: continue` | **1L** | 加 `logger.warning` |
| D2-F3 | opinion 枚举无代码校验 | **S** | `_parse_and_validate_response` 加 enum check |

### 🟢 LOW — 快速修 (挑 5 个)

| # | Finding | Effort | 改动 |
|---|---------|--------|------|
| D3-F12 | balance fetch 失败 DEBUG only | **1L** | → WARNING |
| D4-F12 | retail_extreme fallback weight 0.43≠0.42 | **1L** | 对齐 config 值 |
| D3-F13 | fetch_klines 吞掉 KeyboardInterrupt | **1L** | 改 `except Exception` |
| D2-F9 | confidence_score 无 range clamp | **1L** | `max(0, min(100, score))` |
| D2-F14 | Evolver NO-OP schema 歧义 | **1L** | 文档明确 `[]` vs `null` |

---

## 按 Effort 分组的修复路线

### 🔨 1-Liner 快速扫荡 (每个 <5 min，共 ~20 项)

优先级从高到低：

```
1. D4-F1  [CRIT] order_executor:367  OCO失败不平仓           ← 仓位风险
2. D4-F2  [CRIT] order_executor:321  TP/SL缺失不平仓         ← 仓位风险
3. D3-F1  [CRIT] run_session:158,181 except:pass             ← 进程hang
4. D4-F4  [HIGH] order_executor:494  取消后position=None     ← 仓位风险
5. D4-F5  [HIGH] order_executor:519  异常处理不紧急平仓       ← 仓位风险
6. D4-F9  [MED]  trigger.py          NaN静默抑制所有trigger  ← 信号失效
7. D3-F9  [MED]  market_observer:654 warmup DEBUG→WARNING
8. D3-F11 [MED]  run_evolution:91    except:continue→WARNING
9. D4-F10 [MED]  order_executor:446  尾随止损level校验
10. D3-F12 [LOW] run_sniper:418      balance fetch→WARNING
11. D4-F12 [LOW] trigger:1106        weight 0.43→0.42
12. D3-F13 [LOW] client:112          KeyboardInterrupt
13. D2-F9  [LOW] base_agent          confidence clamp
14. D2-F14 [LOW] evolver.md          NO-OP schema
```

### 📦 Small 改动 (<30 min 每个，共 ~12 项)

```
1. D1-F4  [HIGH] volume_profile:184  bin width分母修正
2. D2-F1  [HIGH] session.md:39       加exception clause
3. D2-F2  [HIGH] math_fact_checker   价格finite校验
4. D3-F2  [HIGH] client:344          close()实现
5. D3-F4  [HIGH] order_executor:328  float eps
6. D3-F5  [HIGH] 5处 datetime.now    → timezone.utc
7. D3-F7  [HIGH] client:146等        raise KeyboardInterrupt
8. D4-F3  [HIGH] order_executor:572  重取position
9. D5-F2  [HIGH] server:32           限制data mount
10. D5-F3 [HIGH] dashboard/api        data_root allowlist
11. D4-F7 [MED]  margin_client:246   step size
12. D4-F8 [MED]  order_executor:647  min_notional
```

### 🏗 Medium 及以上 (<2hr ~ <1day)

```
1. D5-F1 [CRIT] dashboard auth      FastAPI dependency guard  ← 安全
2. D3-F3 [HIGH] config .get()        8+文件改+startup validation
3. D2-F7 [MED]  few-shot examples    三个prompt文件各加示例
4. D4-F6 [MED]  gate bypass          市场结构缺失时的fallback
5. D1-F6 [MED]  cooldown reset       逻辑改动需验证
6. D2-F3 [MED]  opinion enum check   parse层加校验
```

### 📚 测试债务 (需数天)

```
1. D6-F1  59%模块零测试 — 优先 sniper/trigger.py
2. D6-F2  NaN/Inf/None边界测试 — 所有math函数
3. D6-F9  ConfluenceEngine零测试
4. D6-F8  交易所API错误模拟测试
5. D6-F6  辩论异常路径测试
```

---

## 建议修复顺序

```
本次会话剩余时间 → 扫完所有 1-Liner (14项, ~1hr)
下次工作       → Small改动 (12项, ~4hr)
本周内         → Medium: dashboard auth + config加固 + prompt few-shot
本月内         → 测试债务 (从 sniper/trigger.py 开始)
```

*注：标注 ✓ 的项目已在本会话修复。Effort 假设不写新测试（测试债务单独列）。*
