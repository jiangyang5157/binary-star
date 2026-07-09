// Shared session detail rendering functions.
// Used by session.html and audit.html.
// NOTE: All color values are driven by dashboard.css — no hardcoded hex codes.
// Shared utilities (opinionBadge, formatPrice, formatLocalTime) are in dashboard-utils.js.

function escapeHtml(str) {
  if (str == null) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function renderDecisionCard(decision) {
  const tp = decision.tactical_parameters || {};
  return `
    <section class="card decision-card">
      <h2>${t('detail.final_decision')}</h2>
      <div class="decision-header">
        <div class="decision-opinion">${opinionBadge(decision.opinion || 'UNKNOWN')}</div>
        <div class="decision-confidence">
          <span class="confidence-value">${decision.confidence_score != null ? decision.confidence_score.toFixed(1) + '%' : '&mdash;'}</span>
          <span class="confidence-label">${t('detail.confidence')}</span>
        </div>
      </div>
      <div class="tactical-grid">
        <div class="tactical-item">
          <span class="tactical-label">${t('detail.current_price')}</span>
          <span class="tactical-value mono">${formatPrice(tp.current_price)}</span>
        </div>
        <div class="tactical-item">
          <span class="tactical-label">${t('detail.entry')}</span>
          <span class="tactical-value mono">${formatPrice(tp.entry)}</span>
        </div>
        <div class="tactical-item">
          <span class="tactical-label">${t('detail.take_profit')}</span>
          <span class="tactical-value mono profit">${formatPrice(tp.take_profit)}</span>
        </div>
        <div class="tactical-item">
          <span class="tactical-label">${t('detail.stop_loss')}</span>
          <span class="tactical-value mono loss">${formatPrice(tp.stop_loss)}</span>
        </div>
        <div class="tactical-item">
          <span class="tactical-label">${t('detail.rr_ratio')}</span>
          <span class="tactical-value mono">${tp.rr_ratio != null ? tp.rr_ratio.toFixed(2) : '&mdash;'}</span>
        </div>
        <div class="tactical-item">
          <span class="tactical-label">${t('detail.waiting_hours')}</span>
          <span class="tactical-value">${tp.projected_waiting_hours != null ? tp.projected_waiting_hours + 'h' : '&mdash;'}</span>
        </div>
        <div class="tactical-item">
          <span class="tactical-label">${t('detail.holding_hours')}</span>
          <span class="tactical-value">${tp.projected_holding_hours != null ? tp.projected_holding_hours + 'h' : '&mdash;'}</span>
        </div>
      </div>
      ${decision.reasoning_chain ? `
      <details class="reasoning-details">
        <summary>${t('detail.reasoning_chain')}</summary>
        <pre class="reasoning-text">${escapeHtml(decision.reasoning_chain)}</pre>
      </details>` : ''}
      ${decision.critic_impact ? `
      <details class="reasoning-details">
        <summary>${t('detail.critic_impact')}</summary>
        <pre class="reasoning-text">${escapeHtml(decision.critic_impact)}</pre>
      </details>` : ''}
    </section>`;
}

function renderMathCheck(math) {
  if (!math || !math.compliance_verdict) return '';
  if (typeof math.compliance_verdict === 'string') return `<p>${escapeHtml(math.compliance_verdict)}</p>`;
  return `<pre class="reasoning-text">${escapeHtml(JSON.stringify(math.compliance_verdict, null, 2))}</pre>`;
}

function calcRR(tp, opinion) {
  const entry = tp?.entry, takeProfit = tp?.take_profit, stopLoss = tp?.stop_loss;
  if (!entry || !takeProfit || !stopLoss || entry === stopLoss) return '&mdash;';
  const isBearish = opinion === 'BEARISH';
  const reward = isBearish ? entry - takeProfit : takeProfit - entry;
  const risk = isBearish ? stopLoss - entry : entry - stopLoss;
  if (risk <= 0) return '&mdash;';
  return (reward / risk).toFixed(2);
}

function renderDebateRounds(debateHistory) {
  if (!debateHistory || !debateHistory.length) return '';
  return `
    <section class="card">
      <h2>${t('detail.debate_rounds')} (${debateHistory.length})</h2>
      ${debateHistory.map((r, i) => `
        <details class="debate-round">
          <summary>
            <span class="round-label">${t('detail.round')} ${r.round || (i + 1)}</span>
            ${r.plan ? `<span class="round-plan-opinion">${opinionBadge(r.plan.opinion || '?')}</span>` : ''}
            ${r.plan && r.plan.confidence_score != null ? `<span class="round-confidence">${r.plan.confidence_score.toFixed(1)}%</span>` : ''}
            ${r.critic ? `<span class="round-veto veto-${(r.critic.veto_level || '').toLowerCase()}">${r.critic.veto_level || ''}</span>` : ''}
            ${r.math_fact_check ? `<span class="round-math math-${(r.math_fact_check.status || '').toLowerCase()}">${r.math_fact_check.status || ''}</span>` : ''}
          </summary>
          <div class="debate-body">
            ${r.plan ? `
            <div class="debate-section">
              ${r.plan.tactical_parameters ? `
              <div class="tactical-grid compact">
                <div class="tactical-item"><span class="tactical-label">${t('detail.entry')}</span><span class="tactical-value mono">${formatPrice(r.plan.tactical_parameters.entry)}</span></div>
                <div class="tactical-item"><span class="tactical-label">${t('th.tp')}</span><span class="tactical-value mono profit">${formatPrice(r.plan.tactical_parameters.take_profit)}</span></div>
                <div class="tactical-item"><span class="tactical-label">${t('th.sl')}</span><span class="tactical-value mono loss">${formatPrice(r.plan.tactical_parameters.stop_loss)}</span></div>
                <div class="tactical-item"><span class="tactical-label">${t('th.rr')}</span><span class="tactical-value mono">${calcRR(r.plan.tactical_parameters, r.plan.opinion)}</span></div>
              </div>` : ''}
              ${r.plan.reasoning_chain ? `<pre class="reasoning-text">${escapeHtml(r.plan.reasoning_chain)}</pre>` : ''}
            </div>` : ''}
            ${r.critic ? `
            <div class="debate-section">
              <h4>${t('detail.critic_review')} <span class="round-veto veto-${(r.critic.veto_level || '').toLowerCase()}">${r.critic.veto_level || ''}</span></h4>
              ${r.critic.critic_summary ? `<pre class="reasoning-text">${escapeHtml(r.critic.critic_summary)}</pre>` : ''}
              ${r.critic.audit_evidence ? `
              <h5>${t('detail.audit_evidence')}</h5>
              <pre class="reasoning-text">${escapeHtml(r.critic.audit_evidence)}</pre>` : ''}
            </div>` : ''}
            ${r.math_fact_check ? `
            <div class="debate-section">
              <h4>${t('detail.math_fact_check')} <span class="round-math math-${(r.math_fact_check.status || '').toLowerCase()}">${r.math_fact_check.status || ''}</span></h4>
              ${renderMathCheck(r.math_fact_check)}
            </div>` : ''}
          </div>
        </details>`).join('')}
    </section>`;
}

function renderCharts(visualContext) {
  if (!visualContext) return '';
  const charts = [];
  if (visualContext.macro_snapshot) charts.push({label: t('detail.chart_macro'), path: visualContext.macro_snapshot});
  if (visualContext.micro_snapshot) charts.push({label: t('detail.chart_micro'), path: visualContext.micro_snapshot});
  if (!charts.length) return '';
  return `
    <section class="card">
      <h2>${t('detail.charts')}</h2>
      <div class="chart-grid">
        ${charts.map(c => `
        <div class="chart-container">
          <h4>${c.label}</h4>
          <img src="/klines/${c.path.split('/').pop()}" alt="${c.label}" class="chart-img" loading="lazy"
               onerror="this.style.display='none'; this.nextElementSibling.style.display='block';">
          <div class="chart-fallback" style="display:none;">${t('detail.chart_unavailable')}</div>
        </div>`).join('')}
      </div>
    </section>`;
}

function renderMetadata(metadata) {
  if (!metadata) return '';
  const vc = metadata.version_control || {};
  return `
    <section class="card">
      <h2>${t('detail.metadata')}</h2>
      <div class="metadata-grid">
        ${vc.project_version ? `<div class="metadata-item"><span class="metadata-label">${t('detail.project_version')}</span><code>${escapeHtml(vc.project_version)}</code></div>` : ''}
        ${vc.git_commit ? `<div class="metadata-item"><span class="metadata-label">${t('detail.git_commit')}</span><code>${escapeHtml(vc.git_commit)}</code></div>` : ''}
        ${vc.session_hash ? `<div class="metadata-item"><span class="metadata-label">${t('detail.session_hash')}</span><code>${escapeHtml(vc.session_hash)}</code></div>` : ''}
        ${vc.critic_hash ? `<div class="metadata-item"><span class="metadata-label">${t('detail.critic_hash')}</span><code>${escapeHtml(vc.critic_hash)}</code></div>` : ''}
        ${vc.binary_star_hash ? `<div class="metadata-item"><span class="metadata-label">${t('detail.bs_hash')}</span><code>${escapeHtml(vc.binary_star_hash)}</code></div>` : ''}
        ${vc.config_hash ? `<div class="metadata-item"><span class="metadata-label">${t('detail.config_hash')}</span><code>${escapeHtml(vc.config_hash)}</code></div>` : ''}
      </div>
    </section>`;
}
