/**
 * SessionProgress — single component reused across New Session, Sniper, and Backtest.
 *
 * Two display modes controlled by `.collapsed`:
 *   collapsed=false ("expanded"): vertical stage timeline + full activity log
 *   collapsed=true  ("collapsed"): pulse indicator + one-line activity / result
 *
 * Usage:
 *   const sp = new SessionProgress(document.getElementById('container'), {
 *     collapsed: false,    // default
 *     context: 'session',  // 'session' | 'sniper' | 'backtest'
 *   });
 *   sp.update(progressData);
 *
 *   // Toggle at runtime:
 *   sp.collapsed = true;
 *   sp.update(data);
 *
 *   sp.destroy();  // cleanup
 */

const ACTIVITY_COMPLETE = 'complete';
const ACTIVITY_ERROR = 'error';

class SessionProgress {
  constructor(containerEl, opts) {
    opts = opts || {};
    this.el = containerEl;
    this.collapsed = opts.collapsed === true;
    this.context = opts.context || 'session';
    this.el.classList.add('session-progress');
    this.el.style.display = 'none';
  }

  // ── Shared helpers ─────────────────────────────
  _groupActivities(activities) {
    var stageGroups = {};
    var unassigned = [];
    for (var j = 0; j < activities.length; j++) {
      var entry = activities[j];
      var s = entry.stage || 0;
      if (s === 0) { unassigned.push(entry); }
      else {
        if (!stageGroups[s]) stageGroups[s] = [];
        stageGroups[s].push(entry);
      }
    }
    return { stageGroups, unassigned };
  }

  _renderSignalBanner(data) {
    if (this.context === 'sniper' && data._triggered_at) {
      return '<div class="sp-signal-banner">' +
        this._esc(data._symbol || '') + ' · ' +
        formatLocalTimeShort(data._triggered_at) + '</div>';
    }
    return '';
  }

  update(data) {
    if (!data) { this.hide(); return; }

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
    this.el.classList.remove('session-progress', 'sp-hidden');
    this.el.style.display = 'none';
  }

  hide() {
    this.el.style.display = 'none';
    this.el.classList.add('sp-hidden');
  }

  show() {
    this.el.style.display = 'block';
    this.el.classList.remove('sp-hidden');
  }

  // ── Running ────────────────────────────────────────────────

  _renderRunning(data) {
    this.show();
    if (this.collapsed) { this._renderRunningCollapsed(data); return; }
    this._renderRunningExpanded(data);
  }

  _renderRunningCollapsed(data) {
    var activity = data.activity || '';
    var elapsed = this._fmtElapsed(data.elapsed_seconds || 0);

    var html = '';

    html += this._renderSignalBanner(data);

    // Activity line with pulse indicator
    html += '<div class="sp-activity sp-activity-compact">';
    html += '<span class="sp-activity-icon sp-pulse">◉</span>';
    html += '<span class="sp-activity-text">' + this._esc(activity) + '</span>';
    html += '<span class="sp-elapsed">⏱ ' + elapsed + '</span>';
    html += '</div>';

    this.el.innerHTML = html;
  }

  _renderRunningExpanded(data) {
    var stage = data.current_stage || 1;
    var stages = data.stages || [];
    var stageLabel = data.stage_label || '';
    var elapsed = this._fmtElapsed(data.elapsed_seconds || 0);
    var activities = data.activities || [];

    var html = '';

    html += this._renderSignalBanner(data);

    // Group activities by stage so they nest under the correct stage row
    var grouped = this._groupActivities(activities);

    // Vertical stage timeline with nested step lists
    html += '<div class="sp-timeline">';
    for (var i = 0; i < stages.length; i++) {
      var stg = stages[i];
      var isDone = stg.stage < stage;
      var isActive = stg.stage === stage;
      var icon, rowCls;
      if (isDone) { icon = '✓'; rowCls = 'stage-done'; }
      else if (isActive) { icon = '◉'; rowCls = 'stage-active'; }
      else { icon = '○'; rowCls = 'stage-pending'; }

      html += '<div class="sp-stage ' + rowCls + '">';
      html += '<span class="sp-stage-icon">' + icon + '</span>';
      html += '<span class="sp-stage-label">' +
        this._esc(isActive && stageLabel ? stageLabel : stg.label) + '</span>';
      html += '</div>';

      // Steps belonging to this stage
      html += this._renderStepList(grouped.stageGroups[stg.stage]);
    }
    html += '<div class="sp-timeline-elapsed">⏱ ' + elapsed + '</div>';
    html += '</div>';

    // Unassigned activities (fallback for old data without stage field)
    html += this._renderStepList(grouped.unassigned);

    this.el.innerHTML = html;
  }

  // ── Completed ──────────────────────────────────────────────

  _renderCompleted(data) {
    this.show();
    if (this.collapsed) { this._renderCompletedCollapsed(data); return; }
    this._renderCompletedExpanded(data);
  }

  _renderCompletedCollapsed(data) {
    var result = data.result || {};
    var dir = result.direction || 'NEUTRAL';
    var conf = result.confidence != null ? result.confidence : 0;
    var elapsed = this._fmtElapsed(data.elapsed_seconds || 0);
    var debatePath = result.debate_path || '';
    var meta = '✓ ' + dir + ' ' + conf + '% · ⏱ ' + elapsed;
    if (debatePath) meta += ' · ' + debatePath;
    this.el.innerHTML = '<span class="sp-result">' + this._esc(meta) + '</span>';
  }

  _renderCompletedExpanded(data) {
    var result = data.result || {};
    var dir = result.direction || 'NEUTRAL';
    var conf = result.confidence != null ? result.confidence : 0;
    var elapsed = this._fmtElapsed(data.elapsed_seconds || 0);
    var debatePath = result.debate_path || '';
    var stages = data.stages || [];

    var html = '';

    // Full stage timeline (all done)
    html += '<div class="sp-timeline">';
    for (var i = 0; i < stages.length; i++) {
      var stg = stages[i];
      html += '<div class="sp-stage stage-done">';
      html += '<span class="sp-stage-icon">✓</span>';
      html += '<span class="sp-stage-label">' + this._esc(stg.label) + '</span>';
      html += '</div>';
    }
    html += '</div>';

    // Result summary
    html += '<div class="sp-completed">';
    html += '<span>✓</span>';
    html += '<span class="sp-completed-dir">' + this._esc(dir) + '</span>';
    html += '<span class="sp-completed-meta">· ' + t('sniper.confidence_label') + ' ' + conf + '% · ⏱ ' + elapsed + '</span>';
    if (debatePath) {
      html += '<span class="sp-completed-debate">· ' + this._esc(debatePath) + '</span>';
    }
    html += '</div>';

    this.el.innerHTML = html;
  }

  // ── Failed ─────────────────────────────────────────────────

  _renderFailed(data) {
    this.show();
    if (this.collapsed) { this._renderFailedCollapsed(data); return; }
    this._renderFailedExpanded(data);
  }

  _renderFailedCollapsed(data) {
    var errorMsg = data.error || t('error.unknown');
    this.el.innerHTML = '<span class="sp-result sp-result-error">✗ ' +
      this._esc(errorMsg) + '</span>';
  }

  _renderFailedExpanded(data) {
    var stage = data.current_stage || 1;
    var stages = data.stages || [];
    var stageLabel = data.stage_label || '';
    var errorMsg = data.error || t('error.unknown');
    var activities = data.activities || [];

    var html = '';

    var grouped = this._groupActivities(activities);

    // Vertical stage timeline — current stage marked failed
    html += '<div class="sp-timeline">';
    for (var i = 0; i < stages.length; i++) {
      var stg = stages[i];
      var isDone = stg.stage < stage;
      var isActive = stg.stage === stage;
      var icon, rowCls;
      if (isActive) { icon = '✗'; rowCls = 'stage-failed'; }
      else if (isDone) { icon = '✓'; rowCls = 'stage-done'; }
      else { icon = '○'; rowCls = 'stage-pending'; }

      html += '<div class="sp-stage ' + rowCls + '">';
      html += '<span class="sp-stage-icon">' + icon + '</span>';
      html += '<span class="sp-stage-label">' +
        this._esc(isActive && stageLabel ? stageLabel : stg.label) + '</span>';
      html += '</div>';

      // Steps belonging to this stage
      html += this._renderStepList(grouped.stageGroups[stg.stage]);
    }
    html += '<div class="sp-timeline-elapsed">⏱ ' + this._fmtElapsed(data.elapsed_seconds || 0) + '</div>';
    html += '</div>';

    // Error message
    html += '<div class="sp-error-msg"><span>⚠</span><span>' +
      this._esc(errorMsg) + '</span></div>';

    // Unassigned activities (fallback for old data without stage field)
    html += this._renderStepList(grouped.unassigned);

    this.el.innerHTML = html;
  }

  // ── Shared helpers ─────────────────────────────────────────

  /** Render a list of activity entries as a .sp-step-list block. */
  _renderStepList(entries) {
    if (!entries || entries.length === 0) return '';
    var html = '<div class="sp-step-list">';
    for (var j = 0; j < entries.length; j++) {
      var entry = entries[j];
      var isLast = (j === entries.length - 1);
      var stepIcon, stepCls;
      if (entry.type === ACTIVITY_ERROR) {
        stepIcon = '✗'; stepCls = 'step-error';
      } else if (entry.type === ACTIVITY_COMPLETE || !isLast) {
        stepIcon = '✓'; stepCls = 'step-done';
      } else {
        stepIcon = '◉'; stepCls = 'step-active';
      }
      html += '<div class="sp-step ' + stepCls + '">';
      html += '<span class="sp-step-icon">' + stepIcon + '</span>';
      html += '<span class="sp-step-msg">' + this._esc(entry.message || '') + '</span>';
      html += '</div>';
    }
    html += '</div>';
    return html;
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
