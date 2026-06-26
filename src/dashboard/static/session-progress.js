/**
 * SessionProgress — shared progress component for session execution.
 *
 * Visualizes 0-100% session progress with 5 stages, activity feed, and
 * error display. Reused across New Session, Sniper, and Backtest panels.
 *
 * Usage:
 *   const sp = new SessionProgress(document.getElementById('container'), {
 *     size: 'full',        // 'full' | 'compact' | 'mini'
 *     context: 'session',  // 'session' | 'sniper' | 'backtest'
 *   });
 *   sp.update(progressData);  // called every 2s poll cycle
 *   sp.destroy();             // cleanup
 */

const STAGE_ANCHOR_POSITIONS = [0, 18, 62.5, 87.5, 100]; // % left for stages 1-5
const STAGE_LABELS = ['采集数据', '准备分析', '辩论', '最终决策', '归档'];

class SessionProgress {
  constructor(containerEl, opts) {
    opts = opts || {};
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
      case 'running':
        this._renderRunning(data);
        break;
      case 'completed':
        this._renderCompleted(data);
        break;
      case 'failed':
        this._renderFailed(data);
        break;
      default:
        this.hide();
        break;
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

  // ── Running state ──────────────────────────────────────────────

  _renderRunning(data) {
    this.show();
    var stage = data.current_stage || 1;
    var label = data.stage_label || STAGE_LABELS[stage - 1];
    var activity = data.activity || '';
    var elapsed = this._fmtElapsed(data.elapsed_seconds || 0);
    var activities = data.activities || [];
    var fillPct = this._barPct(stage);

    var html = '';

    // Signal banner (sniper only)
    if (this.context === 'sniper' && data._triggered_at) {
      html += '<div class="sp-signal-banner">⚡ 信号触发 · ' +
        this._esc(data._symbol || '') + ' · ' +
        this._esc(data._triggered_at) + '</div>';
    }

    // Bar row
    html += '<div class="sp-bar-row">';
    html += '<div class="sp-bar">';
    html += '<div class="sp-bar-fill' + (stage === 3 ? ' sp-stage-3' : '') +
      '" style="width:' + fillPct + '%"></div>';
    for (var i = 1; i <= 5; i++) {
      var cls = 'sp-anchor s' + i;
      if (i < stage) cls += ' done';
      else if (i === stage) cls += ' active';
      html += '<div class="' + cls + '" style="left:' +
        STAGE_ANCHOR_POSITIONS[i - 1] + '%"></div>';
    }
    html += '</div></div>';

    // Label row (full only)
    if (this.size === 'full') {
      html += '<div class="sp-labels">';
      for (var j = 1; j <= 5; j++) {
        var lblCls = 'sp-label';
        if (j < stage) lblCls += ' done';
        else if (j === stage) lblCls += ' active';
        var lblText = STAGE_LABELS[j - 1];
        if (j === 3 && label && label !== '辩论') lblText = label;
        html += '<span class="' + lblCls + '">' + this._esc(lblText) + '</span>';
      }
      html += '</div>';
    }

    // Activity row (full and compact)
    if (this.size !== 'mini') {
      var toggleIcon = this.expanded ? '▾' : '▸';
      html += '<div class="sp-activity">';
      html += '<span class="sp-activity-toggle">' + toggleIcon + '</span>';
      html += '<span class="sp-activity-text">' + this._esc(activity) + '</span>';
      html += '<span class="sp-elapsed">' + elapsed + '</span>';
      html += '</div>';
    }

    // Activity log (full size, expandable)
    if (this.size === 'full') {
      var logCls = 'sp-log' + (this.expanded ? '' : ' collapsed');
      html += '<div class="' + logCls + '">';
      for (var k = 0; k < activities.length; k++) {
        var entry = activities[k];
        var icon = '◉', entryCls = 'active';
        if (entry.type === 'complete') { icon = '✓'; entryCls = 'complete'; }
        else if (entry.type === 'error') { icon = '✗'; entryCls = 'error'; }
        html += '<div class="sp-log-entry ' + entryCls + '">';
        html += '<span class="sp-log-icon">' + icon + '</span>';
        html += '<span class="sp-log-time">' + this._esc(entry.time || '') + '</span>';
        html += '<span class="sp-log-msg">' + this._esc(entry.message || '') + '</span>';
        html += '</div>';
      }
      html += '</div>';
    }

    this.el.innerHTML = html;

    // Bind click for expand/collapse
    if (this.size === 'full') {
      var self = this;
      var activityRow = this.el.querySelector('.sp-activity');
      if (activityRow) {
        activityRow.onclick = function () {
          self.expanded = !self.expanded;
          self._renderRunning(data);
        };
      }
    }
  }

  // ── Completed state ────────────────────────────────────────────

  _renderCompleted(data) {
    this.show();
    var result = data.result || {};
    var dir = result.direction || 'NEUTRAL';
    var conf = result.confidence != null ? result.confidence : 0;
    var elapsed = this._fmtElapsed(data.elapsed_seconds || 0);
    var debatePath = result.debate_path || '';

    if (this.size === 'compact') {
      var meta = '✓ ' + dir + ' ' + conf + '% · ' + elapsed;
      if (debatePath) meta += ' · ' + debatePath;
      this.el.innerHTML = '<div class="bt-sample-result" style="color:var(--accent-green)">' +
        this._esc(meta) + '</div>';
      return;
    }

    if (this.size === 'mini') { this.hide(); return; }

    // Full size
    var html = '<div class="sp-completed">';
    html += '<span>✓</span>';
    html += '<span class="sp-completed-dir">' + this._esc(dir) + '</span>';
    html += '<span class="sp-completed-meta">· 置信度 ' + conf + '% · 用时 ' + elapsed + '</span>';
    if (debatePath) {
      html += '<span class="sp-completed-debate">· ' + this._esc(debatePath) + '</span>';
    }
    html += '</div>';
    this.el.innerHTML = html;

    // Fade out after 3s (session + sniper, not backtest)
    if (this.context !== 'backtest') {
      var self = this;
      setTimeout(function () {
        self.el.classList.add('sp-fading');
        setTimeout(function () { self.hide(); }, 500);
      }, 3000);
    }
  }

  // ── Failed state ───────────────────────────────────────────────

  _renderFailed(data) {
    this.show();
    var stage = data.current_stage || 1;
    var errorMsg = data.error || '未知错误';
    var activities = data.activities || [];
    var fillPct = this._barPct(stage);

    var html = '';

    // Bar with failed anchor
    html += '<div class="sp-bar-row">';
    html += '<div class="sp-bar">';
    html += '<div class="sp-bar-fill" style="width:' + fillPct + '%"></div>';
    for (var i = 1; i <= 5; i++) {
      var cls = 'sp-anchor s' + i;
      if (i < stage) cls += ' done';
      else if (i === stage) cls += ' failed';
      html += '<div class="' + cls + '" style="left:' +
        STAGE_ANCHOR_POSITIONS[i - 1] + '%"></div>';
    }
    html += '</div></div>';

    // Labels (full only)
    if (this.size === 'full') {
      html += '<div class="sp-labels">';
      for (var j = 1; j <= 5; j++) {
        var lblCls = 'sp-label';
        if (j < stage) lblCls += ' done';
        else if (j === stage) lblCls += ' failed';
        html += '<span class="' + lblCls + '">' + STAGE_LABELS[j - 1] + '</span>';
      }
      html += '</div>';
    }

    // Error message
    html += '<div class="sp-error-msg"><span>⚠</span><span>' +
      this._esc(errorMsg) + '</span></div>';

    // Activity log (auto-expanded for failure)
    if (this.size === 'full' && activities.length > 0) {
      html += '<div class="sp-log">';
      for (var k = 0; k < activities.length; k++) {
        var entry = activities[k];
        var icon = '◉', entryCls = 'active';
        if (entry.type === 'complete') { icon = '✓'; entryCls = 'complete'; }
        else if (entry.type === 'error') { icon = '✗'; entryCls = 'error'; }
        html += '<div class="sp-log-entry ' + entryCls + '">';
        html += '<span class="sp-log-icon">' + icon + '</span>';
        html += '<span class="sp-log-time">' + this._esc(entry.time || '') + '</span>';
        html += '<span class="sp-log-msg">' + this._esc(entry.message || '') + '</span>';
        html += '</div>';
      }
      html += '</div>';
    }

    this.el.innerHTML = html;
  }

  // ── Helpers ────────────────────────────────────────────────────

  _barPct(stage) {
    if (stage <= 0) return 0;
    if (stage >= 5) return 100;
    return STAGE_ANCHOR_POSITIONS[stage - 1];
  }

  _fmtElapsed(seconds) {
    var m = Math.floor(seconds / 60);
    var s = seconds % 60;
    return m > 0 ? m + ':' + (s < 10 ? '0' : '') + s : '0:' + (s < 10 ? '0' : '') + s;
  }

  _esc(s) {
    if (!s) return '';
    var div = document.createElement('div');
    div.textContent = s;
    return div.innerHTML;
  }
}
