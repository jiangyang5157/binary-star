# SessionProgress Component — Design Spec

**Date:** 2026-06-27
**Status:** Draft — pending review
**Author:** yangjiang

---

## 1. Overview

### 1.1 Problem

Users currently stare at a text status message ("running…") for 6-10 minutes during session execution, with no visibility into what's happening or how far along the process is. The dashboard has no progress bars anywhere.

### 1.2 Goal

A shared `SessionProgress` component that visualizes 0-100% session progress across three contexts:

| Context | Session Model | Idle Behavior |
|---------|-------------|---------------|
| **New Session** (live.html) | Single run, 0-100% | Component hidden, Run button visible |
| **Sniper** (live.html) | Signal trigger → session runs → back to idle | Observation pulse view |
| **Backtest** (development.html) | Multiple samples, each 0-100% + global overview | No progress (preview mode only) |

### 1.3 Key UX Principle

**Backend reports facts; frontend animates the space between them.** No time-percentage prediction. Progress bar segments mark stage transitions (deterministic events), and within each stage a subtle breathing animation provides the feeling of forward motion without claiming precision.

---

## 2. Session Phase Model

### 2.1 Five Stages (derived from `BinaryStarOrchestrator.execute_flow()`)

| # | Stage | Anchor Label | Weight (visual) | Key Activity Messages |
|---|-------|-------------|-----------------|----------------------|
| 1 | **数据采集** | 采集数据 | 18% | 获取 K 线数据… → 计算波动率指标… → 渲染图表… → 采集完成 · N 条 K 线 |
| 2 | **准备分析** | 准备分析 | 7% | 计算市场体制… → 准备 AI 上下文… |
| 3 | **辩论中** | 辩论 · RN/M | 50% | Session Agent 思考中… → Math 验证… → Critic 审计中… → Critic: WEAK/PASS/CONSTRUCTIVE/TERMINAL |
| 4 | **最终决策** | 最终决策 | 17% | 综合决策… → 参数验证完成 |
| 5 | **归档** | 归档 | 8% | 保存会话… → 发送通知… → 完成 |

### 2.2 Stage 3 (Debate) Detail

Stage 3 is the dominant phase (~50% wall-clock time). It internally contains 1-3 rounds of:
1. Session Agent (thesis generation, 20-60s)
2. Math Fact Check (Python-native verification, <1s)
3. Critic Agent (adversarial audit, 10-30s)

Each round's Critic vote is shown as an activity message. The stage label updates per round (`辩论 · Round 1/3` → `辩论 · Round 2/3`). Early exit on PASS or WEAK vote shortens the stage.

### 2.3 What is NOT tracked as a stage

- **Tool calls** (MathTools: `calculate_risk_reward`, `calculate_atr_metrics`): conditional, unpredictable. Shown as transient activity messages within the Session Agent sub-step, not as discrete stages.
- **Cache creation/cleanup**: too fast to be meaningful as stages. Appear as activity messages at boundaries.

---

## 3. Component Design

### 3.1 States

| State | Trigger | Visual |
|-------|---------|--------|
| `idle` | Initial / waiting | Varies by context (see §4) |
| `running` | Session started | Progress bar + anchor dots + activity text |
| `completed` | Session success | 100% filled bar → summary line → fade out (context-dependent) |
| `failed` | Exception | Bar frozen at failure point, red ✗ mark, error message, activity log auto-expanded |

### 3.2 Visual Layout (running, `full` size, collapsed)

```
┌─────────────────────────────────────────────────────────┐
│  ●━━━━●━━━━━━━━●━━━━━━━━━━━━━━●━━━━━●━━ 辩论 · Round 2/3  │
│  采集   准备    辩论                     最终   归档        │
│  数据   分析    R1  R2  R3              决策             │
│                                                         │
│  ▸ Critic 审计中…                                 3:24  │
└─────────────────────────────────────────────────────────┘
```

- **Row 1:** Anchor dots + continuous progress bar. Completed segments filled (`#22c55e`), current segment breathing gradient (`#2dd4bf` ↔ `#14b8a6`), future segments dark (`#334155`).
- **Row 2:** Anchor labels. Stage name + dynamic suffix for stage 3 (round counter). Current stage label highlighted.
- **Row 3:** Current activity text (left) + elapsed time mm:ss (right). Activity text updates each time the backend reports a new activity.

### 3.3 Visual Layout (running, `full` size, expanded)

```
┌─────────────────────────────────────────────────────────┐
│  ●━━━━●━━━━━━━━●━━━━━━━━━━━━━━●━━━━━●━━ 辩论 · Round 2/3  │
│  采集   准备    辩论                     最终   归档        │
│  数据   分析    R1  R2  R3              决策             │
│                                                         │
│  ▾ 活动详情                                      3:24    │
│  ┌─────────────────────────────────────────────────────┐│
│  │ ✓ 14:23:01  采集数据完成 · 45 条 K 线, 12 个指标     ││
│  │ ✓ 14:23:04  准备分析完成 · 趋势体制, ATR=0.83%       ││
│  │ ✓ 14:23:38  辩论 R1 · Critic: WEAK                  ││
│  │ ◉ 14:23:42  Critic 审计中…                          ││
│  └─────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────┘
```

- Activity log: max 10 recent entries, oldest auto-fade. Each entry: status icon (✓ complete / ◉ active / ✗ error), timestamp, message.
- Toggle via ▸/▾ click on activity text row or progress bar.

### 3.4 Completed State

```
┌──────────────────────────────────────────────────────────┐
│  ✓ BUY · 置信度 78% · 用时 4:12  ·  R1 WEAK → R2 PASS     │
└──────────────────────────────────────────────────────────┘
```

- One-line summary: direction, confidence, elapsed time, debate path.
- No "view details" link — the new session appears in the Active Sessions table below. For backtest, results are reviewed in Performance → Audit.
- **New Session:** 3s after completion, the summary fades out. Run button shows "Run Session" (same as before — no "Run Again").
- **Sniper:** 3s after completion, fades back to observation pulse view. Recent signals list appends this entry.
- **Backtest:** All rows persist. No auto-fade. Global bar shows 100% + summary stats.

### 3.5 Failed State

```
┌─────────────────────────────────────────────────────────┐
│  ●━━━━●━━━━✗  采集数据 · 失败                            │
│                                                         │
│  ⚠ Binance API 超时 (30s) · 已重试 3 次                  │
│                                                         │
│  ▾ 活动详情（自动展开）                                   │
│  ┌─────────────────────────────────────────────────────┐│
│  │ ◉ 14:23:01  获取 K 线数据中…                         ││
│  │ ◉ 14:23:15  重试 1/3…                               ││
│  │ ◉ 14:23:30  重试 2/3…                               ││
│  │ ✗ 14:23:45  重试 3/3 失败 · Binance API 超时         ││
│  └─────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────┘
```

- Progress bar freezes at the failed stage, anchor turns red ✗.
- Error message replaces activity text row, red highlight.
- Activity log **auto-expands** to show the failure chain.
- **New Session:** Button remains "Run Session" — user clicks again to retry.
- **Sniper:** 3s after failure, fades back to observation pulse view. No warning unless subsequent failures also occur.
- **Backtest:** Failed sample row remains with error reason. No retry button per sample.

### 3.6 Size Variants

| Size | Content | Use |
|------|---------|-----|
| `full` | Bar + anchors + labels + activity + elapsed | New Session main view, Sniper triggered view |
| `compact` | Bar + anchors (no labels row, no activity) | Backtest per-sample row |
| `mini` | Bar only (single line, no anchors visible) | Backtest global overview bar |

### 3.7 Color Tokens

| Element | Color | Hex |
|---------|-------|-----|
| Completed segment fill | Green | `#22c55e` |
| Current segment breathing | Teal gradient | `#2dd4bf` → `#14b8a6` |
| Future segment | Dark slate | `#334155` |
| Anchor dot pulse glow | Teal | `#2dd4bf` + `box-shadow` |
| Failed anchor | Red | `#ef4444` |
| Activity log background | Slate-800 | `#1e293b` |
| Text default | Slate-400 | `#94a3b8` |
| Text emphasis | Slate-200 | `#e2e8f0` |
| Error text | Red | `#ef4444` |

These extend the existing dark theme; all are already present in `dashboard.css`.

### 3.8 Motion

- **Progress bar fill:** CSS `transition: width 0.6s ease-out` when stage advances.
- **Current segment breathing:** `@keyframes breathe` — opacity 0.7 ↔ 1.0 over 2s, infinite.
- **Anchor pulse:** `@keyframes pulse-glow` — `box-shadow` expand/contract 2s, infinite, on current anchor only.
- **Activity text update:** Instant replace (no animation — it's a text swap).
- **Expand/collapse:** `max-height` transition 0.3s for the activity log.
- **Complete fade-out:** `opacity` 0.5s ease-out after 3s delay (New Session and Sniper only).
- **Respect `prefers-reduced-motion`:** disable breathing and pulse; progress bar uses instant snap instead of transition.

---

## 4. Integration by Context

### 4.1 New Session (live.html)

**Location:** Below the symbol input and Run button, above the Active Sessions table. Replaces the current `.run-status-box`.

```
┌──────────────────────────────────────────────────┐
│  New Session                          [权限标签] │
│                                                  │
│  BTC ──────────────┐  [Run Session]              │
│                    │                             │
│  ┌─ SessionProgress (full) ───────────────────┐  │
│  │ (shown when running/completed/failed)       │  │
│  └────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────┘
```

**Data source:** `GET /api/session/run-status` — extended with `progress` field (see §5).

**Lifecycle:**
1. User clicks [Run Session] → POST `/api/session/run`
2. 2s polling starts → component receives `status: "running"`, renders full progress bar
3. Session completes → component receives `status: "completed"` + `result` → shows summary line
4. 3s delay → summary fades out, component returns to hidden state
5. Active Sessions table refreshes (existing `loadActive()` call)

**Error:** Component stays visible with error state. User clicks [Run Session] again to retry.

### 4.2 Sniper (live.html)

**Location:** Below the symbol input and Start/Stop buttons, above the Guardian table.

```
┌──────────────────────────────────────────────────┐
│  Sniper Control                       [权限标签] │
│                                                  │
│  BTC, XAUT ──────┐  [Start Sniper] [Stop]       │
│                  │                               │
│  ┌─ IDLE view ─────────────────────────────────┐ │
│  │ ◎ 观察 BTC, XAUT 中…  ·  脉冲 #47  ·  1:32   │ │
│  │ 最近：14:03 BUY 82%  ·  13:28 SELL 68%       │ │
│  └──────────────────────────────────────────────┘ │
│                                                  │
│  — OR —                                          │
│                                                  │
│  ┌─ SessionProgress (full) ────────────────────┐ │
│  │ ⚡ 信号触发 · BTC · 14:35                     │ │
│  │ ●━━━━━━━━●━━━━━━ 辩论 · Round 1/3            │ │
│  └──────────────────────────────────────────────┘ │
│                                                  │
│  ┌─ Guardian table (trade mode only) ──────────┐ │
│  └──────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────┘
```

**Data source:** `GET /api/sniper/status` — extended with `active_session` field. When `active_session` is null → IDLE view. When not null → SessionProgress.

**Lifecycle:**
1. Sniper started → IDLE view: pulse counter, countdown to next scout, recent signals list
2. Signal triggers → `active_session` populates → IDLE view replaced by SessionProgress (full)
3. Session completes → shows summary → 3s fade → back to IDLE view, recent signals updated
4. Session fails → shows error → 3s fade → back to IDLE view

**IDLE view details:**
- `◎` breathing dot — proves the daemon is alive
- Pulse counter increments each scout cycle (every ~2 min)
- "下次侦查" countdown based on `pulse_seconds`
- Recent signals: last 3-5 signal entries, compact format
- Pulse health: Healthy (<60s), Slow (60-180s), Stale (>180s) based on Sniper heartbeat

### 4.3 Backtest (development.html)

**Location:** Below the Preview/Run/Stop buttons, replacing the current sample status list.

```
┌──────────────────────────────────────────────────┐
│  Backtest                                        │
│                                                  │
│  ○ Single  ○ Range    BTC ────┐                  │
│  ...                                            │
│  [Preview]  [Run]  [Stop]                       │
│                                                  │
│  ┌─ Global bar (mini) ─────────────────────────┐ │
│  │ ████████████░░░░░░░░░░░░  7/14  ·  1 运行中  │ │
│  │ ✓ 5  ·  ✗ 1  ·  ◉ 1  ·  ○ 7                 │ │
│  └──────────────────────────────────────────────┘ │
│                                                  │
│  ┌─ Sample rows (compact) ──────────────────────┐ │
│  │ #1  06-20 14:00  ◉ 辩论 · R2/3  2:18         │ │
│  │     ██████████████████████░░░░░░░░░░░░        │ │
│  │ #2  06-20 18:00  ✓ BUY 78%  3:52             │ │
│  │     ██████████████████████████████████         │ │
│  │ #3  06-21 09:30  ✗ 采集失败 · API 超时         │ │
│  │     ████░░░░░░░░░░░░░░░░░░░░░░░░░░░░          │ │
│  │ #4  06-22 16:15  ○ 等待中                     │ │
│  │     ░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░          │ │
│  └──────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────┘
```

**Data source:** `GET /api/backtest/status` — each sample object extended with `progress` field. New `overall` summary field.

**Lifecycle:**
1. Preview → sample list renders, all rows `○ 等待中`
2. Run → global bar appears, current sample shows compact progress bar
3. Each sample completes → row updates to summary, next sample starts
4. All complete → global bar 100% + summary stats. All rows persist.
5. Error on a sample → row shows error, moves to next sample

**Sample row states:**
| Sample Status | Row Display |
|--------------|-------------|
| `pending` | `○ 等待中` — muted progress bar (all dark) |
| `running` | `◉ <stage_label> <elapsed>` — active compact bar |
| `completed` | `✓ <direction> <confidence>% <elapsed>` — full green bar |
| `failed` | `✗ <error summary>` — partial bar frozen at failure point |

---

## 5. Data Contract

### 5.1 `SessionProgressData` (frontend interface)

```typescript
interface SessionProgressData {
  status: 'idle' | 'running' | 'completed' | 'failed';

  // running state
  current_stage?: number;         // 1-5
  stage_label?: string;           // "辩论 · Round 2/3"
  activity?: string;              // "Critic 审计中…"
  elapsed_seconds?: number;
  activities?: ActivityEntry[];   // max 10, newest last

  // completed state
  result?: {
    direction: string;            // "BUY" | "SELL" | "NEUTRAL"
    confidence: number;           // 0-100
    debate_path: string;          // "R1 WEAK → R2 PASS" or "R1 PASS"
    entry?: number;
    tp?: number;
    sl?: number;
    session_file?: string;        // filename for backtest tracking
  };

  // failed state
  error?: string;                 // human-readable, e.g. "Binance API 超时 (30s)"
}

interface ActivityEntry {
  time: string;                   // "14:23:38" (UTC)
  type: 'complete' | 'active' | 'error';
  message: string;
}
```

### 5.2 Backend Status File Extensions

**A. `.session_run_status.json` (New Session)**

```json
{
  "running": true,
  "symbol": "BTCUSDT",
  "run_id": 3,
  "started_at": "2026-06-27T14:23:01Z",
  "progress": {
    "status": "running",
    "current_stage": 3,
    "stage_label": "辩论 · Round 2/3",
    "activity": "Critic 审计中…",
    "elapsed_seconds": 204,
    "activities": [...]
  }
}
```

**B. `.sniper_daemon_status.json` (Sniper)**

New field `active_session`:
```json
{
  "running": true,
  "symbols": ["BTCUSDT", "XAUTUSDT"],
  "pulse_count": 48,
  "next_scout_in_seconds": null,
  "active_session": {
    "symbol": "BTCUSDT",
    "triggered_at": "14:35:22",
    "progress": { ... }
  },
  "recent_signals": [
    {"time": "14:03", "direction": "SELL", "confidence": 82},
    {"time": "13:28", "direction": "BUY", "confidence": 68}
  ]
}
```

- `active_session` is null when idle, populated when a session is running.
- `recent_signals` is updated after each session completes (appended to front, max 5).

**C. `.backtest_status.json` (Backtest)**

New `overall` field + `progress` per sample:
```json
{
  "running": true,
  "overall": {
    "total": 14,
    "completed": 5,
    "running": 1,
    "failed": 1,
    "pending": 7
  },
  "samples": [
    {
      "index": 1,
      "timestamp": "2026-06-20T14:00:00Z",
      "status": "completed",
      "progress": {
        "status": "completed",
        "elapsed_seconds": 232,
        "result": {
          "direction": "BUY",
          "confidence": 78,
          "debate_path": "R1 PASS",
          "session_file": "BTCUSDT_session_20260620T140000Z.json"
        }
      }
    }
  ]
}
```

### 5.3 API Endpoint Changes

| Endpoint | Change |
|----------|--------|
| `GET /api/session/run-status` | Response gains `progress` field (null when idle) |
| `GET /api/sniper/status` | Response gains `active_session`, `recent_signals`, `pulse_count` |
| `GET /api/backtest/status` | Response gains `overall`; each sample gains `progress` field |

No new endpoints. No polling interval changes (all remain 2s).

---

## 6. Backend Progress Emission Points

Progress is emitted via a `progress_callback(stage, activity, **kwargs)` injected into the execution path. The callback is provided by the caller (standalone thread, sniper daemon, backtest runner) and writes to the appropriate status file.

### 6.1 Emission Sites

Progress is emitted across two levels:

- **Stage 1** (数据采集) is emitted inside `SessionEngine.execute_cycle()` during `MarketObserver.observe()`.
- **Stages 2-5** are emitted inside `BinaryStarOrchestrator.execute_flow()`.

The `progress_callback` is passed through `SessionEngine` → both `MarketObserver` (for stage 1) and `BinaryStarOrchestrator` (for stages 2-5). The debate loop (`DebateLoop.run()`) receives it via the orchestrator.

```
SessionEngine.execute_cycle()
│
├── MarketObserver.observe()
│   ├── stage=1  activity="获取 K 线数据…"
│   ├── stage=1  activity="计算波动率指标…"
│   ├── stage=1  activity="渲染图表…"
│   └── stage=1  activity="采集数据完成 · N 条 K 线, M 个指标"
│
└── BinaryStarOrchestrator.execute_flow()
    │
    ├── stage=2  activity="计算市场体制…"            ← after _inject_regime_benchmarks
    ├── stage=2  activity="准备 AI 上下文…"          ← after _prepare_agent_tools
    │
    ├── DebateLoop.run() — per round:
    │   ├── stage=3  activity="辩论 R1 · Session Agent 思考中…"
    │   ├── stage=3  activity="辩论 R1 · Math 验证…"
    │   ├── stage=3  activity="辩论 R1 · Critic 审计中…"
    │   ├── stage=3  activity="辩论 R1 · Critic: <VETO>"
    │   ├── stage_label update: "辩论 · Round N/M"
    │   └── (repeat for subsequent rounds)
    │
    ├── stage=4  activity="综合决策…"                ← _finalize_and_sanitize start
    ├── stage=4  activity="参数验证完成"              ← after math sanitization
    │
    ├── stage=5  activity="保存会话…"                ← archive_strategy_result
    ├── stage=5  activity="发送通知…"                ← notify_session
    │
    └── status="completed"  result={...}
```

On exception at any point: `status="failed"`, `error="<message>"`, `current_stage` frozen.

### 6.2 Callback Signature

```python
def progress_callback(
    stage: int,
    activity: str,
    status: str = "running",        # "running" | "completed" | "failed"
    stage_label: str | None = None, # override auto-generated label
    result: dict | None = None,     # set on completion
    error: str | None = None,       # set on failure
) -> None:
    ...
```

### 6.3 Callback Wiring

| Context | Callback Writes To | Provided By |
|---------|-------------------|-------------|
| New Session | `.session_run_status.json` | `_run_session_in_thread()` in `session_run.py` |
| Sniper | `.sniper_daemon_status.json` → `active_session` field | SniperDaemon pulse loop |
| Backtest | `.backtest_status.json` → `samples[i].progress` | `_run_backtest_in_thread()` in `backtest.py` |

The callback writes atomically (write to `.tmp` → `os.replace`) to avoid partial reads by the polling API.

---

## 7. Frontend Implementation Notes

### 7.1 Component Module

A single `SessionProgress` JavaScript class/function, defined in a new file `src/dashboard/static/session-progress.js`, used by both `live.html` and `development.html`.

```javascript
// Minimal public API sketch
class SessionProgress {
  constructor(containerEl, { size = 'full', context = 'session' } = {})
  update(data: SessionProgressData)  // called every poll cycle
  destroy()
}
```

### 7.2 HTML Structure (full size, running)

```html
<div class="session-progress" data-status="running">
  <div class="sp-bar-row">
    <div class="sp-bar">
      <div class="sp-bar-fill" style="width: 55%"></div>
      <div class="sp-anchor active" style="left: 18%"></div>
      <div class="sp-anchor done" style="left: 25%"></div>
      <div class="sp-anchor active" style="left: 50%"></div>
      <div class="sp-anchor" style="left: 75%"></div>
      <div class="sp-anchor" style="left: 92%"></div>
    </div>
  </div>
  <div class="sp-labels">...</div>
  <div class="sp-activity">
    <span class="sp-activity-toggle">▸</span>
    <span class="sp-activity-text">Critic 审计中…</span>
    <span class="sp-elapsed">3:24</span>
  </div>
  <div class="sp-log collapsed">
    <div class="sp-log-entry complete">✓ 14:23:01 ...</div>
    <div class="sp-log-entry active">◉ 14:23:42 ...</div>
  </div>
</div>
```

### 7.3 CSS

New styles in `dashboard.css` under a `/* ── SessionProgress ── */` section. Key classes:

- `.session-progress` — container, transitions between states
- `.sp-bar`, `.sp-bar-fill` — bar and fill with `transition: width 0.6s ease-out`
- `.sp-anchor` — absolute-positioned dots; `.done` (green fill), `.active` (teal + `pulse-glow` animation), default (dark)
- `.sp-log` — `max-height` transition for expand/collapse
- `.sp-log.collapsed` — `max-height: 0; overflow: hidden`
- `@keyframes breathe`, `@keyframes pulse-glow`

---

## 8. Non-Goals (Explicitly Out of Scope)

- **WebSocket/SSE transport:** Continue using 2s HTTP polling. Progress data is small; adding real-time transport is unnecessary complexity for this feature.
- **"View details" link from completed state:** Not needed. Active Sessions table and Performance/Audit serve as the result browsers.
- **"Run Again" button variant:** Not needed. The Run button is always "Run Session".
- **Per-sample retry in backtest:** Not in scope. Failed samples remain in final state.
- **Sniper failure warning after N consecutive failures:** Not in scope.
- **Precise percentage prediction:** Explicitly avoided. Progress bar shows stage transitions, not time estimates.

---

## 9. Files Touched (Implementation Summary)

| File | Change |
|------|--------|
| `src/dashboard/static/session-progress.js` | **New.** SessionProgress component JS |
| `src/dashboard/static/dashboard.css` | **Edit.** Add SessionProgress styles |
| `src/dashboard/templates/live.html` | **Edit.** Integrate SessionProgress into New Session + Sniper sections, replace `.run-status-box` |
| `src/dashboard/templates/development.html` | **Edit.** Integrate SessionProgress into backtest sample list, add global bar |
| `src/dashboard/api/session_run.py` | **Edit.** Add progress callback, extend run-status response |
| `src/dashboard/api/sniper_run.py` | **Edit.** Extend status response with `active_session`, `recent_signals`, `pulse_count` |
| `src/dashboard/api/backtest.py` | **Edit.** Add progress callback, extend status response with `overall` + per-sample `progress` |
| `src/agent/binary_star_orchestrator.py` | **Edit.** Add `progress_callback` parameter to `execute_flow()`, emit at key points |
| `run_session.py` | **Edit.** Accept and wire progress callback through `SessionEngine` → `BinaryStarOrchestrator` |
| `run_sniper.py` | **Edit.** Write sniper progress to status file during session execution |
