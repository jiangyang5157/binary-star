# SessionProgress Component — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a shared SessionProgress component that visualizes 0-100% session progress with 5 stages, activity feed, and error display, then integrate it into New Session, Sniper, and Backtest dashboard panes.

**Architecture:** Frontend component (`SessionProgress` JS class) renders into a container DOM element using data from existing 2s polling APIs. Backend `progress_callback` injected through `SessionEngine` → `BinaryStarOrchestrator` writes stage/activity to status JSON files. The component handles 4 states (idle/running/completed/failed) and 3 sizes (full/compact/mini).

**Tech Stack:** Vanilla JS (no framework), CSS custom properties (existing dark theme), Python/FastAPI backend, atomic JSON file writes for IPC.

## Global Constraints

- Continue using 2s HTTP polling — no WebSocket/SSE
- No "View details" link from completed state
- No "Run Again" button variant — Run button always shows "Run Session"
- No per-sample retry in backtest
- No sniper failure warning after N consecutive failures
- No time-percentage prediction — bar segments mark stage transitions only
- Respect `prefers-reduced-motion` for all animations
- All color tokens extend existing dashboard dark theme
- Run button is always "▶ Run" / "⏹ Stop" — never "Run Again"

---

### Task 1: CSS Styles for SessionProgress

**Files:**
- Modify: `src/dashboard/static/dashboard.css` — append new styles section

**Interfaces:**
- Produces: CSS classes `.session-progress`, `.sp-bar`, `.sp-anchor`, `.sp-labels`, `.sp-activity`, `.sp-log`, animations `@keyframes sp-breathe`, `@keyframes sp-pulse-glow`

- [ ] **Step 1: Add SessionProgress CSS at end of dashboard.css**

Append after the last existing rule:

```css
/* ============================================================
   SessionProgress — shared progress component
   ============================================================ */

/* ── Container ── */
.session-progress {
  margin-top: 12px;
  padding: 14px 16px;
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: var(--radius);
  font-size: 0.82rem;
  transition: opacity 0.5s ease-out;
}
.session-progress.sp-fading {
  opacity: 0;
  pointer-events: none;
}
.session-progress.sp-hidden {
  display: none;
}

/* ── Bar row ── */
.sp-bar-row {
  position: relative;
  height: 32px;
  display: flex;
  align-items: center;
}
.sp-bar {
  position: relative;
  width: 100%;
  height: 6px;
  background: var(--border-color);
  border-radius: 3px;
  overflow: visible;
}
.sp-bar-fill {
  position: absolute;
  left: 0;
  top: 0;
  height: 100%;
  background: var(--accent-green);
  border-radius: 3px;
  transition: width 0.6s ease-out;
  z-index: 1;
}
.sp-bar-fill.sp-stage-3 {
  background: linear-gradient(90deg, var(--accent-teal), #14b8a6);
  animation: sp-breathe 2s ease-in-out infinite;
}

/* ── Anchor dots ── */
.sp-anchor {
  position: absolute;
  top: 50%;
  transform: translate(-50%, -50%);
  width: 10px;
  height: 10px;
  border-radius: 50%;
  background: var(--border-color);
  border: 2px solid var(--bg-card);
  z-index: 2;
  transition: background 0.4s, box-shadow 0.4s;
}
.sp-anchor.done {
  background: var(--accent-green);
}
.sp-anchor.active {
  background: var(--accent-teal);
  box-shadow: 0 0 8px 2px rgba(84, 160, 168, 0.5);
  animation: sp-pulse-glow 2s ease-in-out infinite;
}
.sp-anchor.failed {
  background: var(--accent-red);
  box-shadow: 0 0 6px 2px rgba(224, 85, 74, 0.4);
}

/* Anchor positions — 5 stages */
.sp-anchor.s1 { left: 0%; }
.sp-anchor.s2 { left: 18%; }
.sp-anchor.s3 { left: 62.5%; }
.sp-anchor.s4 { left: 87.5%; }
.sp-anchor.s5 { left: 100%; }

/* ── Labels row ── */
.sp-labels {
  display: flex;
  justify-content: space-between;
  margin-top: 2px;
  margin-bottom: 8px;
  padding: 0;
  font-size: 0.7rem;
  color: var(--text-muted);
}
.sp-label {
  text-align: center;
  white-space: nowrap;
  transition: color 0.4s;
}
.sp-label.done { color: var(--accent-green); }
.sp-label.active { color: var(--accent-teal); }
.sp-label.failed { color: var(--accent-red); }

/* ── Activity row ── */
.sp-activity {
  display: flex;
  align-items: center;
  gap: 6px;
  cursor: pointer;
  user-select: none;
  padding: 4px 0;
}
.sp-activity-toggle {
  font-size: 0.65rem;
  color: var(--text-muted);
  width: 12px;
  flex-shrink: 0;
}
.sp-activity-text {
  flex: 1;
  color: var(--text-secondary);
  font-size: 0.78rem;
}
.sp-activity-text.sp-error {
  color: var(--accent-red);
}
.sp-elapsed {
  color: var(--text-muted);
  font-size: 0.72rem;
  font-family: "SF Mono", "Fira Code", "Consolas", monospace;
}

/* ── Activity log (expandable) ── */
.sp-log {
  margin-top: 6px;
  padding: 8px 10px;
  background: var(--bg-primary);
  border-radius: var(--radius-sm);
  font-size: 0.72rem;
  font-family: "SF Mono", "Fira Code", "Consolas", monospace;
  max-height: 300px;
  overflow-y: auto;
  transition: max-height 0.3s ease-out, padding 0.3s, margin 0.3s;
}
.sp-log.collapsed {
  max-height: 0;
  padding-top: 0;
  padding-bottom: 0;
  margin-top: 0;
  overflow: hidden;
}
.sp-log-entry {
  padding: 2px 0;
  display: flex;
  gap: 6px;
  align-items: baseline;
}
.sp-log-entry .sp-log-icon {
  width: 14px;
  flex-shrink: 0;
  text-align: center;
}
.sp-log-entry .sp-log-time {
  color: var(--text-muted);
  flex-shrink: 0;
}
.sp-log-entry .sp-log-msg {
  color: var(--text-secondary);
}
.sp-log-entry.complete .sp-log-icon { color: var(--accent-green); }
.sp-log-entry.active .sp-log-icon { color: var(--accent-teal); }
.sp-log-entry.error .sp-log-icon,
.sp-log-entry.error .sp-log-msg { color: var(--accent-red); }

/* ── Completed state ── */
.sp-completed {
  display: flex;
  align-items: center;
  gap: 8px;
  color: var(--accent-green);
  font-size: 0.82rem;
  flex-wrap: wrap;
}
.sp-completed .sp-completed-dir {
  font-weight: 600;
}
.sp-completed .sp-completed-meta {
  color: var(--text-secondary);
  font-size: 0.78rem;
}
.sp-completed .sp-completed-debate {
  color: var(--text-muted);
  font-size: 0.72rem;
}

/* ── Failed state ── */
.sp-error-msg {
  display: flex;
  align-items: flex-start;
  gap: 6px;
  padding: 8px 0;
  color: var(--accent-red);
  font-size: 0.82rem;
  font-weight: 500;
}

/* ── Sniper IDLE view ── */
.sniper-idle {
  margin-top: 12px;
  padding: 14px 16px;
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: var(--radius);
  font-size: 0.82rem;
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.sniper-idle-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  background: var(--accent-teal);
  flex-shrink: 0;
  animation: sp-pulse-glow 2s ease-in-out infinite;
}
.sniper-idle-info {
  color: var(--text-secondary);
}
.sniper-idle-info strong {
  color: var(--text-primary);
}
.sniper-idle-recent {
  color: var(--text-muted);
  font-size: 0.76rem;
}

/* ── Sniper signal trigger banner ── */
.sp-signal-banner {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 4px 0 8px;
  font-size: 0.78rem;
  color: var(--accent-orange);
  font-weight: 500;
}

/* ── Backtest global bar ── */
.bt-global-bar {
  margin-top: 12px;
  padding: 10px 16px;
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: var(--radius);
}
.bt-global-bar .sp-bar-row {
  height: 24px;
}
.bt-global-bar .sp-bar {
  height: 8px;
  border-radius: 4px;
}
.bt-global-summary {
  display: flex;
  gap: 16px;
  font-size: 0.76rem;
  color: var(--text-secondary);
  margin-top: 4px;
}
.bt-global-summary .done-count { color: var(--accent-green); }
.bt-global-summary .failed-count { color: var(--accent-red); }
.bt-global-summary .running-count { color: var(--accent-teal); }

/* ── Backtest sample row with compact progress ── */
.bt-sample-row {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 8px 12px;
  border-bottom: 1px solid var(--border-muted);
}
.bt-sample-row:last-child { border-bottom: none; }
.bt-sample-info {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 0.8rem;
}
.bt-sample-idx { color: var(--text-muted); width: 28px; flex-shrink: 0; }
.bt-sample-ts { color: var(--text-secondary); min-width: 140px; }
.bt-sample-status-icon { width: 16px; text-align: center; flex-shrink: 0; }
.bt-sample-status-icon.ok { color: var(--accent-green); }
.bt-sample-status-icon.err { color: var(--accent-red); }
.bt-sample-status-icon.running { color: var(--accent-teal); }
.bt-sample-status-icon.pending { color: var(--text-muted); }
.bt-sample-result { color: var(--text-primary); font-weight: 500; }
.bt-sample-meta { color: var(--text-muted); font-size: 0.76rem; }
.bt-sample-error { color: var(--accent-red); font-size: 0.76rem; }

/* ── Animations ── */
@keyframes sp-breathe {
  0%, 100% { opacity: 0.7; }
  50% { opacity: 1; }
}
@keyframes sp-pulse-glow {
  0%, 100% { box-shadow: 0 0 4px 1px rgba(84, 160, 168, 0.3); }
  50% { box-shadow: 0 0 10px 3px rgba(84, 160, 168, 0.55); }
}

/* ── Reduced motion ── */
@media (prefers-reduced-motion: reduce) {
  .sp-bar-fill { transition: none; }
  .sp-bar-fill.sp-stage-3 { animation: none; }
  .sp-anchor.active { animation: none; }
  .sniper-idle-dot { animation: none; }
  .sp-log { transition: none; }
  .session-progress { transition: none; }
}
```

- [ ] **Step 2: Verify no CSS syntax errors**

Run: `grep -c '{' src/dashboard/static/dashboard.css && grep -c '}' src/dashboard/static/dashboard.css`
Expected: Both numbers match

---

### Task 2: SessionProgress JS Component

**Files:**
- Create: `src/dashboard/static/session-progress.js`

**Interfaces:**
- Produces: `class SessionProgress` with `constructor(containerEl, {size, context})`, `update(data)`, `destroy()`
- Consumes: `SessionProgressData` interface (see spec §5.1)

- [ ] **Step 1: Create session-progress.js**

Write `src/dashboard/static/session-progress.js`:

```javascript
/**
 * SessionProgress — shared progress component for session execution.
 *
 * Usage:
 *   const sp = new SessionProgress(document.getElementById('container'), {
 *     size: 'full',        // 'full' | 'compact' | 'mini'
 *     context: 'session',  // 'session' | 'sniper' | 'backtest'
 *   });
 *   sp.update(progressData);
 */

const STAGE_ANCHOR_POSITIONS = [0, 18, 62.5, 87.5, 100]; // % left for stages 1-5
const STAGE_LABELS = ['采集数据', '准备分析', '辩论', '最终决策', '归档'];

class SessionProgress {
  constructor(containerEl, opts = {}) {
    this.el = containerEl;
    this.size = opts.size || 'full';
    this.context = opts.context || 'session';
    this.expanded = false;
    this._lastData = null;
    this.el.classList.add('session-progress');
    this.el.style.display = 'none';
  }

  update(data) {
    if (!data) { this.hide(); return; }
    this._lastData = data;

    switch (data.status) {
      case 'running': this._renderRunning(data); break;
      case 'completed': this._renderCompleted(data); break;
      case 'failed': this._renderFailed(data); break;
      default: this.hide(); break;
    }
  }

  destroy() {
    this.el.innerHTML = '';
    this.el.classList.remove('session-progress', 'sp-fading', 'sp-hidden');
    this.el.style.display = 'none';
  }

  hide() {
    this.el.style.display = 'none';
    this.el.classList.add('sp-hidden');
  }

  show() {
    this.el.style.display = 'block';
    this.el.classList.remove('sp-hidden', 'sp-fading');
  }

  // ── Running state ──

  _renderRunning(data) {
    this.show();
    const stage = data.current_stage || 1;
    const label = data.stage_label || STAGE_LABELS[stage - 1];
    const activity = data.activity || '';
    const elapsed = this._fmtElapsed(data.elapsed_seconds || 0);
    const activities = data.activities || [];
    const fillPct = this._barPct(stage);

    let html = '';

    // Signal banner (sniper only)
    if (this.context === 'sniper' && data._triggered_at) {
      html += `<div class="sp-signal-banner">⚡ 信号触发 · ${data._symbol || ''} · ${data._triggered_at}</div>`;
    }

    // Bar row
    html += '<div class="sp-bar-row">';
    html += '<div class="sp-bar">';
    html += `<div class="sp-bar-fill${stage === 3 ? ' sp-stage-3' : ''}" style="width:${fillPct}%"></div>`;
    for (let i = 1; i <= 5; i++) {
      let cls = 'sp-anchor s' + i;
      if (i < stage) cls += ' done';
      else if (i === stage) cls += ' active';
      html += `<div class="${cls}" style="left:${STAGE_ANCHOR_POSITIONS[i-1]}%"></div>`;
    }
    html += '</div></div>';

    // Label row (full only)
    if (this.size === 'full') {
      html += '<div class="sp-labels">';
      for (let i = 1; i <= 5; i++) {
        let cls = 'sp-label';
        if (i < stage) cls += ' done';
        else if (i === stage) cls += ' active';
        let lbl = STAGE_LABELS[i - 1];
        if (i === 3 && label && label !== '辩论') lbl = label;
        html += `<span class="${cls}">${lbl}</span>`;
      }
      html += '</div>';
    }

    // Activity row (full/compact)
    if (this.size !== 'mini') {
      const toggleIcon = this.expanded ? '▾' : '▸';
      html += '<div class="sp-activity">';
      html += `<span class="sp-activity-toggle">${toggleIcon}</span>`;
      html += `<span class="sp-activity-text">${this._esc(activity)}</span>`;
      html += `<span class="sp-elapsed">${elapsed}</span>`;
      html += '</div>';
    }

    // Activity log
    if (this.size === 'full') {
      const logCls = 'sp-log' + (this.expanded ? '' : ' collapsed');
      html += `<div class="${logCls}">`;
      for (const entry of activities) {
        let icon = '◉', cls = 'active';
        if (entry.type === 'complete') { icon = '✓'; cls = 'complete'; }
        else if (entry.type === 'error') { icon = '✗'; cls = 'error'; }
        html += `<div class="sp-log-entry ${cls}">`;
        html += `<span class="sp-log-icon">${icon}</span>`;
        html += `<span class="sp-log-time">${this._esc(entry.time || '')}</span>`;
        html += `<span class="sp-log-msg">${this._esc(entry.message || '')}</span>`;
        html += '</div>';
      }
      html += '</div>';
    }

    this.el.innerHTML = html;

    // Bind click for expand/collapse
    if (this.size === 'full') {
      const activityRow = this.el.querySelector('.sp-activity');
      if (activityRow) {
        activityRow.onclick = () => {
          this.expanded = !this.expanded;
          this._renderRunning(data);
        };
      }
    }
  }

  // ── Completed state ──

  _renderCompleted(data) {
    this.show();
    const result = data.result || {};
    const dir = result.direction || 'NEUTRAL';
    const conf = result.confidence != null ? result.confidence : 0;
    const elapsed = this._fmtElapsed(data.elapsed_seconds || 0);
    const debatePath = result.debate_path || '';

    if (this.size === 'compact') {
      // Compact: just a short summary line
      let meta = `✓ ${dir} ${conf}% · ${elapsed}`;
      if (debatePath) meta += ` · ${debatePath}`;
      this.el.innerHTML = `<div class="bt-sample-result" style="color:var(--accent-green)">${meta}</div>`;
      return;
    }

    if (this.size === 'mini') { this.hide(); return; }

    // Full size
    let html = '<div class="sp-completed">';
    html += `<span>✓</span>`;
    html += `<span class="sp-completed-dir">${this._esc(dir)}</span>`;
    html += `<span class="sp-completed-meta">· 置信度 ${conf}% · 用时 ${elapsed}</span>`;
    if (debatePath) {
      html += `<span class="sp-completed-debate">· ${this._esc(debatePath)}</span>`;
    }
    html += '</div>';
    this.el.innerHTML = html;

    // Fade out after 3s (session + sniper, not backtest)
    if (this.context !== 'backtest') {
      setTimeout(() => {
        this.el.classList.add('sp-fading');
        setTimeout(() => this.hide(), 500);
      }, 3000);
    }
  }

  // ── Failed state ──

  _renderFailed(data) {
    this.show();
    const stage = data.current_stage || 1;
    const errorMsg = data.error || '未知错误';
    const activities = data.activities || [];
    const fillPct = this._barPct(stage);

    let html = '';

    // Bar with failed anchor
    html += '<div class="sp-bar-row">';
    html += '<div class="sp-bar">';
    html += `<div class="sp-bar-fill" style="width:${fillPct}%"></div>`;
    for (let i = 1; i <= 5; i++) {
      let cls = 'sp-anchor s' + i;
      if (i < stage) cls += ' done';
      else if (i === stage) cls += ' failed';
      html += `<div class="${cls}" style="left:${STAGE_ANCHOR_POSITIONS[i-1]}%"></div>`;
    }
    html += '</div></div>';

    // Labels (full only)
    if (this.size === 'full') {
      html += '<div class="sp-labels">';
      for (let i = 1; i <= 5; i++) {
        let cls = 'sp-label';
        if (i < stage) cls += ' done';
        else if (i === stage) cls += ' failed';
        html += `<span class="${cls}">${STAGE_LABELS[i - 1]}</span>`;
      }
      html += '</div>';
    }

    // Error message
    html += `<div class="sp-error-msg"><span>⚠</span><span>${this._esc(errorMsg)}</span></div>`;

    // Activity log (auto-expanded for failure)
    if (this.size === 'full' && activities.length > 0) {
      html += '<div class="sp-log">';
      for (const entry of activities) {
        let icon = '◉', cls = 'active';
        if (entry.type === 'complete') { icon = '✓'; cls = 'complete'; }
        else if (entry.type === 'error') { icon = '✗'; cls = 'error'; }
        html += `<div class="sp-log-entry ${cls}">`;
        html += `<span class="sp-log-icon">${icon}</span>`;
        html += `<span class="sp-log-time">${this._esc(entry.time || '')}</span>`;
        html += `<span class="sp-log-msg">${this._esc(entry.message || '')}</span>`;
        html += '</div>';
      }
      html += '</div>';
    }

    this.el.innerHTML = html;

    // Bind expand/collapse
    if (this.size === 'full') {
      const activityRow = this.el.querySelector('.sp-activity');
      if (activityRow) {
        activityRow.onclick = () => {
          this.expanded = !this.expanded;
          this._renderFailed(data);
        };
      }
    }
  }

  // ── Helpers ──

  _barPct(stage) {
    // Return approximate fill percentage for a given stage
    if (stage <= 0) return 0;
    if (stage >= 5) return 100;
    return STAGE_ANCHOR_POSITIONS[stage - 1];
  }

  _fmtElapsed(seconds) {
    const m = Math.floor(seconds / 60);
    const s = seconds % 60;
    return m > 0 ? `${m}:${String(s).padStart(2, '0')}` : `0:${String(s).padStart(2, '0')}`;
  }

  _esc(s) {
    if (!s) return '';
    const div = document.createElement('div');
    div.textContent = s;
    return div.innerHTML;
  }
}
```

- [ ] **Step 2: Verify JS syntax**

Run: `node --check src/dashboard/static/session-progress.js`
Expected: No output (success)

---

### Task 3: Progress Callback in Orchestrator + SessionEngine + DebateLoop

**Files:**
- Modify: `src/agent/binary_star_orchestrator.py:309` — add `progress_callback` param to `execute_flow()`
- Modify: `src/agent/debate_loop.py:29` — add `progress_callback` param to `run()`, emit per-round
- Modify: `run_session.py:79` — add `progress_callback` param to `execute_cycle()`, pass to orchestrator

**Interfaces:**
- Produces: `progress_callback` signature `fn(stage: int, activity: str, **kwargs)` threaded through execution path
- Consumes: (none — this is the foundation)

- [ ] **Step 1: Add progress_callback to DebateLoop.run()**

Edit `src/agent/debate_loop.py:29` — add parameter and emission points:

```python
# In DebateLoop.run(), change signature from:
def run(self, observation: dict, symbol: str) -> dict[str, Any]:
# To:
def run(self, observation: dict, symbol: str,
        progress_callback=None) -> dict[str, Any]:
```

Inside the while loop, add progress emissions. After line 47 (`last_plan = self.session_agent.execute_session_cycle(...)`):

No, the emission should be BEFORE each sub-step. Add at the start of each round (before line 47):

```python
# Before session agent call (line 47):
if progress_callback:
    progress_callback(stage=3, activity=f"辩论 R{current_round} · Session Agent 思考中…",
                      stage_label=f"辩论 · Round {current_round}/{self.max_rounds}")

# Before math check (after session agent, before line 72):
if progress_callback:
    progress_callback(stage=3, activity=f"辩论 R{current_round} · Math 验证…")

# Before critic call (after math check, before line 76):
if progress_callback:
    progress_callback(stage=3, activity=f"辩论 R{current_round} · Critic 审计中…")

# After critic vote (after line 89):
if progress_callback:
    progress_callback(stage=3, activity=f"辩论 R{current_round} · Critic: {veto_level}")
```

- [ ] **Step 2: Add progress_callback to BinaryStarOrchestrator.execute_flow()**

Edit `src/agent/binary_star_orchestrator.py:309` — change signature:

```python
def execute_flow(self, observation: Dict[str, Any], symbol: str,
                 progress_callback=None) -> Dict[str, Any]:
```

Add emissions at key points. After `_inject_regime_benchmarks(observation)` (line 318):

```python
if progress_callback:
    progress_callback(stage=2, activity="计算市场体制…")
```

After `_prepare_agent_tools(...)` (line 329, before DebateLoop):

```python
if progress_callback:
    progress_callback(stage=2, activity="准备 AI 上下文…")
```

When calling DebateLoop (line 345):

```python
debate_result = self.debate_loop.run(observation, symbol,
                                     progress_callback=progress_callback)
```

Before `_finalize_and_sanitize(...)` (line 348):

```python
if progress_callback:
    progress_callback(stage=4, activity="综合决策…")
```

After `_finalize_and_sanitize(...)` returns (line 348):

```python
if progress_callback:
    progress_callback(stage=4, activity="参数验证完成")
```

Before return (line 355, inside the packaging section):

```python
if progress_callback:
    progress_callback(stage=5, activity="保存会话…")
```

Actually, stage 5 (notification + archive) happens in SessionEngine.execute_cycle(), NOT in execute_flow(). So move stage 5 emissions to SessionEngine.

- [ ] **Step 3: Add progress_callback to SessionEngine.execute_cycle()**

Edit `run_session.py:79` — change signature:

```python
def execute_cycle(self, timestamp_str: Optional[str] = None,
                  situation_brief: Optional[Dict[str, Any]] = None,
                  progress_callback=None) -> Dict[str, Any]:
```

Emit stage 1 around MarketObserver.observe() (around line 98):

```python
if progress_callback:
    progress_callback(stage=1, activity="获取 K 线数据…")

logger.info(f"Observer: Mapping structural topography for {self.symbol}...")
observation = self.orchestrator.observer.observe(timestamp=target_dt, persist=False)

if progress_callback:
    metrics = observation.get('quantitative_metrics', {})
    kline_count = "N"  # we don't know exact count at this level
    progress_callback(stage=1, activity="采集数据完成")

# ... after error check ...

# Pass progress_callback to execute_flow (line 120):
session_result = self.orchestrator.execute_flow(observation, self.symbol,
                                                  progress_callback=progress_callback)

# Stage 5 — after execute_flow returns (before line 123):
if progress_callback:
    progress_callback(stage=5, activity="保存会话…")

# After notification + archive (after line 137):
if progress_callback:
    progress_callback(stage=5, activity="发送通知…")

# On completion (after line 140):
if progress_callback:
    direction = session_result.get('final_decision', {}).get('opinion', 'NEUTRAL')
    confidence = session_result.get('final_decision', {}).get('confidence_score', 0)
    progress_callback(status="completed", result={
        "direction": direction,
        "confidence": confidence,
        # debate_path computed from debate_history
    })
```

On exception (in the except block, before line 143):

```python
if progress_callback:
    progress_callback(status="failed", error=str(e))
```

- [ ] **Step 4: Handle the Observation sub-steps more granularly**

Since `MarketObserver.observe()` is a single method call, but we want finer-grained activity messages, add the callback inside the observe method too. Edit `src/analyzer/market_observer.py:659`:

```python
def observe(self, timestamp=None, data_root=None, persist=True,
            progress_callback=None):
    # ... existing code ...
    
    # 1. Data collection
    if progress_callback:
        progress_callback(stage=1, activity="获取 K 线数据…")
    raw = self.loader.collect(self.symbol, at_time)
    
    # 2. Quality validation
    # ... existing validation ...
    
    # 3. Metric distillation
    if progress_callback:
        progress_callback(stage=1, activity="计算波动率指标…")
    metrics, m_df, n_df = self.refiner.refine(raw)
    
    # 4. Chart generation
    if progress_callback:
        progress_callback(stage=1, activity="渲染图表…")
    snapshots = self._generate_snapshots(...)
    
    # 5. Done
    if progress_callback:
        kline_count = len(raw.macro_klines) if hasattr(raw, 'macro_klines') else '?'
        progress_callback(stage=1, activity=f"采集数据完成 · {kline_count} 条 K 线")
```

And update SessionEngine to pass progress_callback to observe():

```python
observation = self.orchestrator.observer.observe(
    timestamp=target_dt, persist=False,
    progress_callback=progress_callback
)
```

---

### Task 4: New Session API — Progress Reporting

**Files:**
- Modify: `src/dashboard/api/session_run.py:104` — `_run_session_in_thread()` to create and pass progress callback
- Modify: `src/dashboard/api/session_run.py:231` — `get_run_status()` to include `progress` field

- [ ] **Step 1: Create progress callback in _run_session_in_thread()**

Edit `src/dashboard/api/session_run.py`. In `_run_session_in_thread()` (line 104), add the progress callback before calling execute_cycle:

```python
def _run_session_in_thread(symbol: str, data_root: str, run_id: int) -> None:
    try:
        from run_session import SessionEngine

        engine = SessionEngine(symbol=symbol, data_root=data_root)

        # ── Progress callback: write to status file ──
        def _on_progress(stage=None, activity=None, status="running",
                         stage_label=None, result=None, error=None):
            current = _read_status(data_root)
            if not current or current.get("run_id") != run_id:
                return
            now_utc = datetime.now(timezone.utc)
            elapsed = round((now_utc - datetime.fromisoformat(
                current["started_at"].replace("Z", "+00:00")
            )).total_seconds())

            progress = current.get("progress", {})
            if status == "running":
                activities = progress.get("activities", [])
                activities.append({
                    "time": now_utc.strftime("%H:%M:%S"),
                    "type": "complete" if "完成" in (activity or "") or (
                        activity and activity.startswith("辩论") and ":" in activity
                    ) else "active",
                    "message": activity or "",
                })
                if len(activities) > 10:
                    activities = activities[-10:]

                progress.update({
                    "status": "running",
                    "current_stage": stage or progress.get("current_stage", 1),
                    "stage_label": stage_label or progress.get("stage_label", ""),
                    "activity": activity or progress.get("activity", ""),
                    "elapsed_seconds": elapsed,
                    "activities": activities,
                })
            elif status == "completed":
                progress = {
                    "status": "completed",
                    "current_stage": 5,
                    "stage_label": "归档",
                    "elapsed_seconds": elapsed,
                    "result": result or {},
                    "activities": progress.get("activities", []),
                }
            elif status == "failed":
                activities = progress.get("activities", [])
                if activity:
                    activities.append({
                        "time": now_utc.strftime("%H:%M:%S"),
                        "type": "error",
                        "message": activity,
                    })
                progress = {
                    "status": "failed",
                    "current_stage": stage or progress.get("current_stage", 1),
                    "elapsed_seconds": elapsed,
                    "error": error or activity or "未知错误",
                    "activities": activities,
                }

            current["progress"] = progress
            _write_status(data_root, current)

        result = engine.execute_cycle(timestamp_str=None,
                                      progress_callback=_on_progress)
        # ... rest of existing function unchanged ...
```

- [ ] **Step 2: Update get_run_status() to include progress**

Edit `src/dashboard/api/session_run.py:231`. In the `get_run_status()` function, the running response (around line 257):

```python
return {
    "running": True,
    "symbol": status.get("symbol", ""),
    "started_at": started_str,
    "elapsed_seconds": round(elapsed),
    "progress": status.get("progress"),
}
```

And the idle response (line 264):

```python
return {
    "running": False,
    "last_run": status.get("last_run"),
    "progress": status.get("progress"),
}
```

---

### Task 5: Sniper API + Daemon Progress

**Files:**
- Modify: `src/dashboard/api/sniper_run.py:189` — `sniper_status()` add `active_session`, `recent_signals`, `pulse_count`
- Modify: `run_sniper.py:101` — `run_forever()` maintain pulse_count, write active_session progress

- [ ] **Step 1: Extend sniper_status() response**

Edit `src/dashboard/api/sniper_run.py:189`. After the existing response dict, add:

```python
# Read active_session from status file
active_session = status.get("active_session")
recent_signals = status.get("recent_signals", [])
pulse_count = status.get("pulse_count", 0)
next_scout = None
if active_session is None and status.get("running"):
    # Compute next scout time from pulse interval
    try:
        from src.utils.pipeline_utils import load_global_config
        gcfg = load_global_config()
        pulse_mins = int(gcfg.get('sniper', {}).get('heartbeat', {}).get('pulse_interval_minutes', 2))
        pulse_secs = _read_pulse_seconds(data_root, fallback_elapsed=0)
        next_scout = max(0, pulse_mins * 60 - pulse_secs)
    except Exception:
        next_scout = None

return {
    "running": True,
    # ... existing fields ...
    "pulse_count": pulse_count,
    "next_scout_in_seconds": next_scout,
    "active_session": active_session,
    "recent_signals": recent_signals,
}
```

- [ ] **Step 2: Add pulse_count and progress writing to sniper daemon**

Edit `run_sniper.py`. In `run_forever()`, add a pulse counter. At the top of the pulse loop (before line 108):

```python
pulse_count = 0
```

After the lightweight heartbeat (line 116):

```python
pulse_count += 1
# Write pulse count to status file
_sniper_status = _read_sniper_status_file(args.path)
if _sniper_status:
    _sniper_status["pulse_count"] = pulse_count
    _write_sniper_status_file(args.path, _sniper_status)
```

Before calling `execute_cycle()` for a triggered symbol (around line 217), write `active_session` to status:

```python
# Write active_session progress
_status_path = os.path.join(resolve_project_root(), args.path, ".sniper_daemon_status.json")

def _sniper_progress_callback(stage=None, activity=None, status="running",
                               stage_label=None, result=None, error=None):
    import json as _json
    try:
        s = _json.loads(open(_status_path).read())
        now_utc = datetime.now(timezone.utc)
        elapsed = round((now_utc - datetime.fromisoformat(
            s.get("active_session", {}).get("triggered_at_iso", s.get("started_at", now_utc.isoformat()))
        )).total_seconds()) if s.get("active_session") else 0

        progress = s.get("active_session", {}).get("progress", {})
        if status == "running":
            activities = progress.get("activities", [])
            activities.append({
                "time": now_utc.strftime("%H:%M:%S"),
                "type": "complete" if (activity and ":" in activity and activity.startswith("辩论")) else "active",
                "message": activity or "",
            })
            if len(activities) > 10:
                activities = activities[-10:]
            progress = {
                "status": "running",
                "current_stage": stage or progress.get("current_stage", 1),
                "stage_label": stage_label or progress.get("stage_label", ""),
                "activity": activity or progress.get("activity", ""),
                "elapsed_seconds": elapsed,
                "activities": activities,
            }
        elif status == "completed":
            progress = {
                "status": "completed",
                "current_stage": 5,
                "elapsed_seconds": elapsed,
                "result": result or {},
                "activities": progress.get("activities", []),
            }
        elif status == "failed":
            progress = {
                "status": "failed",
                "current_stage": stage or progress.get("current_stage", 1),
                "elapsed_seconds": elapsed,
                "error": error or activity or "未知错误",
                "activities": progress.get("activities", []),
            }

        s["active_session"] = {
            "symbol": sym,
            "triggered_at": now_utc.strftime("%H:%M:%S"),
            "triggered_at_iso": now_utc.isoformat(),
            "progress": progress,
        }
        with open(_status_path + ".tmp", "w") as f:
            _json.dump(s, f, default=str)
        os.replace(_status_path + ".tmp", _status_path)
    except Exception:
        pass

# Wire callback to session engine
session_result = self.session_engines[sym].execute_cycle(
    situation_brief=result.situation_brief,
    progress_callback=_sniper_progress_callback,
)
```

After session completes (or fails), update `recent_signals` and clear `active_session`:

```python
# After execute_cycle returns:
try:
    s = json.loads(open(_status_path).read())
    if s.get("active_session"):
        direction = session_result.get('final_decision', {}).get('opinion', 'NEUTRAL') if session_result and "error" not in session_result else "ERROR"
        confidence = session_result.get('final_decision', {}).get('confidence_score', 0) if session_result and "error" not in session_result else 0
        recent = s.get("recent_signals", [])
        recent.insert(0, {
            "time": datetime.now(timezone.utc).strftime("%H:%M"),
            "direction": direction,
            "confidence": confidence,
        })
        s["recent_signals"] = recent[:5]
        s["active_session"] = None
        with open(_status_path + ".tmp", "w") as f:
            json.dump(s, f, default=str)
        os.replace(_status_path + ".tmp", _status_path)
except Exception:
    pass
```

Note: The sniper daemon needs helper functions to read/write the status file from within the daemon process. The existing `_write_sniper_status` and `_read_sniper_status` functions are in `sniper_run.py` (dashboard API module), not accessible from `run_sniper.py`. We'll add inline helpers.

Actually, looking at the sniper daemon code, it already writes heartbeat files directly. Let me add minimal helpers in run_sniper.py for reading/writing `.sniper_daemon_status.json`.

---

### Task 6: Backtest API — Progress Reporting

**Files:**
- Modify: `src/dashboard/api/backtest.py:261` — `_run_backtest_in_thread()` create and pass progress callback
- Modify: `src/dashboard/api/backtest.py:486` — `get_status()` include `overall` field

- [ ] **Step 1: Add progress callback in _run_backtest_in_thread()**

Edit `src/dashboard/api/backtest.py:261`. Before calling `engine.execute_cycle()` (line 294), add:

```python
# ── Progress callback for this sample ──
def _bt_progress(stage=None, activity=None, status="running",
                 stage_label=None, result=None, error=None):
    current = _read_status(data_root)
    if not current or current.get("run_id") != run_id:
        return
    now_utc = datetime.now(timezone.utc)
    samples = current.get("samples") or []
    if i >= len(samples):
        return

    started_str = current.get("started_at", "")
    elapsed = 0
    if started_str:
        try:
            started = datetime.fromisoformat(started_str.replace("Z", "+00:00"))
            elapsed = round((now_utc - started).total_seconds())
        except Exception:
            pass

    progress = samples[i].get("progress", {})
    if status == "running":
        activities = progress.get("activities", [])
        activities.append({
            "time": now_utc.strftime("%H:%M:%S"),
            "type": "complete" if (activity and ":" in activity and activity.startswith("辩论")) else "active",
            "message": activity or "",
        })
        if len(activities) > 10:
            activities = activities[-10:]
        progress = {
            "status": "running",
            "current_stage": stage or progress.get("current_stage", 1),
            "stage_label": stage_label or progress.get("stage_label", ""),
            "activity": activity or progress.get("activity", ""),
            "elapsed_seconds": elapsed,
            "activities": activities,
        }
    elif status == "completed":
        progress = {
            "status": "completed",
            "current_stage": 5,
            "elapsed_seconds": elapsed,
            "result": result or {},
            "activities": progress.get("activities", []),
        }
    elif status == "failed":
        progress = {
            "status": "failed",
            "current_stage": stage or progress.get("current_stage", 1),
            "elapsed_seconds": elapsed,
            "error": error or activity or "未知错误",
            "activities": progress.get("activities", []),
        }

    samples[i]["progress"] = progress
    _write_status(data_root, {**current, "samples": samples})
```

Then call execute_cycle with the callback:

```python
result = engine.execute_cycle(timestamp_str=ts,
                              progress_callback=_bt_progress)
```

- [ ] **Step 2: Add overall field to get_status()**

Edit `src/dashboard/api/backtest.py:486`. In `get_status()`, compute `overall` from samples before returning:

```python
# In get_status(), after reading status:
if status and status.get("samples"):
    samples = status["samples"]
    overall = {
        "total": len(samples),
        "completed": sum(1 for s in samples if s.get("status") == "completed"),
        "running": sum(1 for s in samples if s.get("status") == "running"),
        "failed": sum(1 for s in samples if s.get("status") == "failed"),
        "pending": sum(1 for s in samples if s.get("status") == "pending"),
    }
    status["overall"] = overall

return status  # already includes elapsed_seconds computation
```

Also update the running response path (around line 506) to include `overall`:

```python
return {
    **status,  # already has overall from above
    "elapsed_seconds": elapsed,
}
```

And the stopped/idle response (line 512) should also include `overall`:

```python
return status  # already computed overall above
```

---

### Task 7: live.html Integration — New Session + Sniper

**Files:**
- Modify: `src/dashboard/templates/live.html` — replace run-status-box with SessionProgress, add sniper IDLE view

- [ ] **Step 1: Add SessionProgress script tag**

In `<head>` (after dashboard.css link, line 7):

```html
<script src="/static/session-progress.js"></script>
```

- [ ] **Step 2: Replace New Session run status with SessionProgress**

In the New Session section (around line 44), replace:

```html
<div id="run-status" class="run-status-box" style="display:none"></div>
```

With:

```html
<div id="run-progress-container"></div>
```

In the JavaScript New Session section, add a `SessionProgress` instance variable. After `let runPollInterval = null;`:

```javascript
let runProgress = null;
```

In `triggerRun()`, after successfully starting (after line 332 `const data = await resp.json();`), initialize the progress component:

```javascript
if (!runProgress) {
  runProgress = new SessionProgress(
    document.getElementById('run-progress-container'),
    { size: 'full', context: 'session' }
  );
}
```

Replace the polling function `checkRunStatus()` to use `runProgress.update()`:

```javascript
async function checkRunStatus() {
  try {
    const resp = await fetch(apiUrl('/api/session/run-status'));
    const data = await resp.json();

    if (data.running) {
      updateRunUI('running');
      if (runProgress && data.progress) {
        // Augment with symbol info if needed
        const p = data.progress;
        p._symbol = data.symbol || '';
        runProgress.update(p);
      }
    } else {
      if (runPollInterval) {
        clearInterval(runPollInterval);
        runPollInterval = null;

        if (runProgress && data.progress) {
          runProgress.update(data.progress);
        }
        if (typeof loadActive === 'function') { loadActive(); }

        // Keep completed/failed status visible briefly
        setTimeout(() => {
          updateRunUI('idle');
          if (runProgress) runProgress.hide();
        }, data.progress && data.progress.status === 'completed' ? 3500 : 0);
      }
    }
  } catch (e) { /* polling failed silently */ }
}
```

In the stop path (in `triggerRun()`, after successful stop), add:

```javascript
if (runProgress) { runProgress.hide(); }
```

- [ ] **Step 3: Add sniper IDLE view + SessionProgress for triggered state**

Replace:

```html
<div id="sniper-status" class="run-status-box" style="display:none"></div>
```

With:

```html
<div id="sniper-progress-container"></div>
```

In the sniper JavaScript section, add:

```javascript
let sniperProgress = null;
```

Rewrite `checkSniperStatus()`:

```javascript
async function checkSniperStatus() {
  try {
    const resp = await fetch(apiUrl('/api/sniper/status'));
    const data = await resp.json();

    if (data.running) {
      updateSniperUI('running');
      const container = document.getElementById('sniper-progress-container');

      // Check if there's an active session
      if (data.active_session && data.active_session.progress) {
        // Show SessionProgress for triggered session
        if (!sniperProgress) {
          sniperProgress = new SessionProgress(container, {
            size: 'full', context: 'sniper'
          });
        }
        const p = data.active_session.progress;
        p._symbol = data.active_session.symbol || '';
        p._triggered_at = data.active_session.triggered_at || '';
        sniperProgress.update(p);
      } else {
        // IDLE view — observation pulse
        if (sniperProgress) {
          sniperProgress.destroy();
          sniperProgress = null;
        }
        _renderSniperIdle(container, data);
      }

      // Guardian table (trade mode) — keep existing behavior
      if (data.trade_enabled && data.guardian && data.guardian.symbols) {
        _renderGuardianTable(data);
      }
    } else {
      if (sniperPollInterval) {
        clearInterval(sniperPollInterval);
        sniperPollInterval = null;
        updateSniperUI('idle');
        const container = document.getElementById('sniper-progress-container');
        container.innerHTML = '<div class="run-status-box run-ok" style="display:block">✓ Stopped</div>';
        if (sniperProgress) { sniperProgress.destroy(); sniperProgress = null; }
        setTimeout(() => { container.innerHTML = ''; }, 5000);
      }
    }
  } catch (e) { /* polling failed silently */ }
}
```

Add the `_renderSniperIdle()` helper function:

```javascript
function _renderSniperIdle(container, data) {
  const symbols = (data.symbols || []).map(s => s.replace(new RegExp(QUOTE + '$', 'i'), '')).join(', ');
  const pulseCount = data.pulse_count || 0;
  const nextScout = data.next_scout_in_seconds;
  const health = pulseHealthAge(data.pulse_seconds);
  const recentSignals = data.recent_signals || [];

  let nextScoutText = '';
  if (nextScout != null && nextScout >= 0) {
    const m = Math.floor(nextScout / 60);
    const s = nextScout % 60;
    nextScoutText = ` · 下次侦查 ${m}:${String(s).padStart(2, '0')}`;
  }

  let recentHtml = '';
  if (recentSignals.length > 0) {
    const items = recentSignals.map(s => {
      const dir = s.direction === 'BUY' || s.direction === 'BULLISH' ? 'BUY' :
                 s.direction === 'SELL' || s.direction === 'BEARISH' ? 'SELL' : s.direction;
      return `${s.time} ${dir} ${s.confidence}%`;
    }).join('  ·  ');
    recentHtml = `<span class="sniper-idle-recent">最近：${items}</span>`;
  }

  container.innerHTML = `
    <div class="sniper-idle">
      <span class="sniper-idle-dot"></span>
      <span class="sniper-idle-info">观察 <strong>${symbols}</strong> 中… · 脉冲 #${pulseCount}${nextScoutText}</span>
      ${recentHtml}
    </div>`;
}
```

- [ ] **Step 4: Update initRunStatus and initSniperStatus to create progress components**

In `initRunStatus()`, after confirming running state, create the progress component and update:

```javascript
if (!runProgress) {
  runProgress = new SessionProgress(
    document.getElementById('run-progress-container'),
    { size: 'full', context: 'session' }
  );
}
```

In `initSniperStatus()`, the existing check will call `sniperPollInterval = setInterval(checkSniperStatus, 2000)` and `checkSniperStatus()` which will render the appropriate view.

- [ ] **Step 5: Handle Stop path — destroy progress**

In `triggerRun()` stop path, after stop succeeds, add:

```javascript
if (runProgress) { runProgress.destroy(); runProgress = null; }
document.getElementById('run-progress-container').innerHTML = '';
```

Similarly for sniper stop path:

```javascript
const container = document.getElementById('sniper-progress-container');
container.innerHTML = '';
if (sniperProgress) { sniperProgress.destroy(); sniperProgress = null; }
```

---

### Task 8: development.html Integration — Backtest

**Files:**
- Modify: `src/dashboard/templates/development.html` — replace sample list rendering with progress bars

- [ ] **Step 1: Add SessionProgress script**

In `<head>`, same as Task 7 Step 1:

```html
<script src="/static/session-progress.js"></script>
```

- [ ] **Step 2: Rewrite renderSampleList() to use SessionProgress rows**

Replace the `renderSampleList()` function:

```javascript
function renderSampleList(data) {
  const list = $('bt-sample-list');
  const body = $('bt-sample-body');
  const countEl = $('bt-sample-count');

  list.style.display = 'block';
  countEl.textContent = `● ${data.count} timestamp${data.count !== 1 ? 's' : ''} selected`;

  body.innerHTML = data.timestamps.map((ts, i) => {
    const dt = formatTimestamp(ts);
    return `<div class="bt-sample-row" id="bt-sample-${i}">
      <div class="bt-sample-info">
        <span class="bt-sample-idx">${i + 1}</span>
        <span class="bt-sample-ts">${dt}</span>
        <span class="bt-sample-status-icon pending">○</span>
        <span class="bt-sample-result"></span>
        <span class="bt-sample-meta"></span>
        <span class="bt-sample-error"></span>
      </div>
      <div class="bt-sample-progress" id="bt-sp-${i}"></div>
    </div>`;
  }).join('');

  // Store SessionProgress instances
  window._btProgressInstances = {};
}
```

- [ ] **Step 3: Rewrite updateSampleStatuses() to update progress bars**

```javascript
function updateSampleStatuses(samples) {
  samples.forEach((s, i) => {
    const row = document.getElementById('bt-sample-' + i);
    if (!row) return;

    const iconEl = row.querySelector('.bt-sample-status-icon');
    const resultEl = row.querySelector('.bt-sample-result');
    const metaEl = row.querySelector('.bt-sample-meta');
    const errorEl = row.querySelector('.bt-sample-error');
    const progContainer = document.getElementById('bt-sp-' + i);

    const progress = s.progress;

    if (s.status === 'running') {
      if (iconEl) { iconEl.textContent = '◉'; iconEl.className = 'bt-sample-status-icon running'; }
      if (resultEl) resultEl.textContent = '';
      if (metaEl) metaEl.textContent = '';
      if (errorEl) errorEl.textContent = '';

      if (progress && progContainer) {
        if (!window._btProgressInstances[i]) {
          window._btProgressInstances[i] = new SessionProgress(progContainer, {
            size: 'compact', context: 'backtest'
          });
        }
        window._btProgressInstances[i].update(progress);
      }
    } else if (s.status === 'completed') {
      if (iconEl) { iconEl.textContent = '✓'; iconEl.className = 'bt-sample-status-icon ok'; }
      if (progContainer && window._btProgressInstances[i]) {
        window._btProgressInstances[i].update(progress || { status: 'completed', result: {} });
      }
      if (progress && progress.result) {
        const r = progress.result;
        if (resultEl) resultEl.textContent = `${r.direction || '?'} ${r.confidence || 0}%`;
        if (metaEl) {
          let meta = `${formatElapsed(progress.elapsed_seconds || 0)}`;
          if (r.debate_path) meta += ` · ${r.debate_path}`;
          metaEl.textContent = meta;
        }
      }
      if (errorEl) errorEl.textContent = '';
    } else if (s.status === 'failed') {
      if (iconEl) { iconEl.textContent = '✗'; iconEl.className = 'bt-sample-status-icon err'; }
      if (progContainer && window._btProgressInstances[i]) {
        window._btProgressInstances[i].update(progress || { status: 'failed', error: s.error || '失败' });
      }
      if (resultEl) resultEl.textContent = '';
      if (metaEl) metaEl.textContent = '';
      if (errorEl) errorEl.textContent = s.error || progress?.error || '失败';
    } else {
      // pending — no change to icon (already set in renderSampleList)
      if (progContainer && window._btProgressInstances[i]) {
        window._btProgressInstances[i].destroy();
        delete window._btProgressInstances[i];
        progContainer.innerHTML = '';
      }
    }
  });
}
```

- [ ] **Step 4: Add global progress bar**

Add a container for the global bar. After the Run status div (line 108):

```html
<div id="bt-global-bar-container" style="display:none"></div>
```

In `checkBacktestStatus()`, when running and `data.overall` is present:

```javascript
// Update global bar
const globalContainer = $('bt-global-bar-container');
if (data.overall) {
  globalContainer.style.display = 'block';
  const ov = data.overall;
  const donePct = ov.total > 0 ? Math.round((ov.completed / ov.total) * 100) : 0;
  const runningPct = ov.total > 0 ? Math.round((ov.running / ov.total) * 100) : 0;
  globalContainer.innerHTML = `
    <div class="bt-global-bar">
      <div class="sp-bar-row">
        <div class="sp-bar">
          <div class="sp-bar-fill" style="width:${donePct}%"></div>
        </div>
      </div>
      <div class="bt-global-summary">
        <span>${ov.completed + ov.failed}/${ov.total} 完成</span>
        ${ov.running > 0 ? `<span class="running-count">◉ ${ov.running} 运行中</span>` : ''}
        <span class="done-count">✓ ${ov.completed}</span>
        ${ov.failed > 0 ? `<span class="failed-count">✗ ${ov.failed}</span>` : ''}
        <span>○ ${ov.pending}</span>
      </div>
    </div>`;
} else {
  globalContainer.style.display = 'none';
}
```

- [ ] **Step 5: Remove old run-status text for backtest**

In `checkBacktestStatus()`, keep the `updateRunUI('running')` call but remove the old `statusEl.innerHTML = '⟳ Running...'` text since the global bar + sample rows now show all the information.

---

### Task 9: Commit and Code Review

- [ ] **Step 1: Run full syntax check**

```bash
node --check src/dashboard/static/session-progress.js
python -m py_compile src/agent/binary_star_orchestrator.py
python -m py_compile src/agent/debate_loop.py
python -m py_compile run_session.py
python -m py_compile run_sniper.py
python -m py_compile src/dashboard/api/session_run.py
python -m py_compile src/dashboard/api/sniper_run.py
python -m py_compile src/dashboard/api/backtest.py
python -m py_compile src/analyzer/market_observer.py
```

- [ ] **Step 2: CSS bracket check**

```bash
grep -c '{' src/dashboard/static/dashboard.css
grep -c '}' src/dashboard/static/dashboard.css
```

- [ ] **Step 3: Commit all changes**

```bash
git add -A
git commit -m "feat: SessionProgress component — progress bar for session/sniper/backtest"
```

- [ ] **Step 4: Run code review**

Use `/code-review` with effort level `medium` to review the full diff.

- [ ] **Step 5: Run existing tests**

```bash
python -m pytest tests/ -v --timeout=60 2>&1 | tail -30
```

Expected: All existing tests pass (no regressions).

---
