# Audit Round 2 — Impact × Effort (剩余待修复)

**基于**: Round 1 已修复 21 项（NaN守卫×4 + logging×4 + 紧急平仓×5 + TriggerResult解包 + signal诊断日志 + 其他1-liner×7）  
**剩余**: 53 项（CRITICAL 1 | HIGH 13 | MEDIUM 24 | LOW 15）

---

## 先看还剩什么 CRITICAL

| # | Finding | Effort | 说明 |
|---|---------|--------|------|
| D5-F1 | Dashboard 写端点零认证，`0.0.0.0:8080` | **M** | 唯一剩下的 CRITICAL。加 FastAPI dependency guard + 改 host=127.0.0.1 |

---

## HIGH 项 Impact × Effort 排序

按「每单位努力的收益」从高到低：

| 优先级 | # | Finding | Impact | Effort | 理由 |
|--------|---|---------|--------|--------|------|
| 🔴1 | D4-F3 | cancel→replace 未重取仓位量 | 订单拒单/超卖 | **S** | 加一行 `get_symbol_position` |
| 🔴2 | D3-F4 | 止损突破 float 比较无 epsilon | 止损漏触发 | **S** | `abs(price-sl) < 1e-8` |
| 🔴3 | D3-F5 | 5处 `datetime.now()` 无时区 | 审计链断裂 | **S** | 全改 `.now(timezone.utc)` |
| 🔴4 | D5-F2 | 整个 `data/` 目录暴露 | 策略泄露 | **S** | 改为只 mount 安全子目录 |
| 🔴5 | D5-F3 | `data_root` 目录遍历 | 文件系统攻击 | **S** | allowlist + `.resolve()` |
| 🟠6 | D1-F4 | VP bin width 分母错误 | 虚假 HVN/LVN | **S** | `len(prices)`→`resolution_bins` |
| 🟠7 | D2-F1 | Prompt: counter-trend 矛盾 | AI 决策混乱 | **1L** | session.md 加一行 |
| 🟠8 | D2-F2 | 价格无 finite 校验 | NaN/Inf 到交易所 | **S** | math_fact_checker + order_executor |
| 🟠9 | D3-F2 | `close()` 空函数 → 连接泄漏 | socket 耗尽 | **S** | 实现 SDK cleanup |
| 🟠10 | D3-F7 | fetch 失败返回 `[]` 掩藏根因 | 静默数据降级 | **S** | return None + 日志 |
| 🟡11 | D3-F3 | 裸 bracket config 访问 | KeyError 崩溃 | **M** | 8+处改 `.get()` |
| 🟡12 | D6-F1 | 59%模块零测试 | 无回归保护 | **L** | 逐步补 |
| 🟡13 | D6-F2 | NaN/Inf 边界测试缺失 | 已知bug漏网 | **L** | 参数化测试 |

---

## Round 2 建议：先扫 10 个 Small（约 3hr）

```
D4-F3  order_executor:572   重取position               ← 防订单拒单
D3-F4  order_executor:328   float eps                  ← 防止损漏触
D3-F5  5处 datetime.now     → timezone.utc            ← 防审计断裂  
D5-F2  server:32            data mount 收窄           ← 防策略泄露
D5-F3  dashboard/api        data_root allowlist       ← 防目录遍历
D1-F4  volume_profile:184   bin width 修正            ← 防虚假结构
D2-F1  session.md:39        prompt 矛盾修正           ← 防LLM困惑
D2-F2  math_fact_checker    价格 finite 校验          ← 防NaN到交易所
D3-F2  client:344           close() 实现              ← 防socket泄漏
D3-F7  client:146           错误返回None(非[])        ← 防静默降级
```

## Round 3 建议：2 个 Medium（约 4hr）

```
D5-F1  dashboard auth       FastAPI dependency guard  ← 安全红线
D3-F3  config .get()        8+文件加固+startup校验     ← 防KeyError
```

---

## 按类别总览

### 仓位保护 (order_executor.py) — Round 1 已大幅加固

| 状态 | # | 问题 |
|------|---|------|
| ✓ | D4-F1 | 初始OCO失败不紧急平仓 |
| ✓ | D4-F2 | TP/SL缺失不紧急平仓 |
| ✓ | D4-F4 | cancel后position=None不平仓 |
| ✓ | D4-F5 | 异常处理不平仓 |
| ✓ | D1-F7 | NaN穿透trailing stop守卫 |
| ✓ | D4-F10 | 尾随止损level单调性校验 |
| → | D4-F3 | cancel→replace 未重取仓位量 |
| → | D3-F4 | 止损突破float比较无epsilon |

### 数据/信号安全

| 状态 | # | 问题 |
|------|---|------|
| ✓ | D1-F2 | NaN穿透 if atr 守卫 |
| ✓ | D1-F3 | NaN进入scipy find_peaks |
| ✓ | D1-F5 | Keltner ATR NaN squeeze_factor |
| ✓ | D4-F9 | NaN静默抑制所有trigger |
| ✓ | D3-F6 | detector异常 DEBUG→WARNING |
| → | D1-F4 | VP bin width分母错误 |
| → | D3-F7 | fetch失败返回[]掩藏根因 |

### 基础设施

| 状态 | # | 问题 |
|------|---|------|
| ✓ | D3-F1 | bare except:pass ×2 |
| ✓ | D3-F11 | evolver bare except:continue |
| ✓ | D3-F13 | KeyboardInterrupt被吞 |
| → | D3-F2 | close()空函数 |
| → | D3-F3 | 裸bracket config |
| → | D3-F5 | datetime.now()无时区 |

### Security

| 状态 | # | 问题 |
|------|---|------|
| → | D5-F1 | Dashboard零认证 (唯一CRIT) |
| → | D5-F2 | data/目录暴露 |
| → | D5-F3 | data_root目录遍历 |

---

*注：✓ = Round 1 已修。→ = 待修。Effort: S=<30min, M=<2hr, L=<1day。*
