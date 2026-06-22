// Shared session detail rendering functions.
// Used by session.html and audit.html.

function opinionBadge(opinion) {
  const cls = opinion === 'BULLISH' ? 'badge-green' : opinion === 'BEARISH' ? 'badge-red' : 'badge-gray';
  return `<span class="badge ${cls}">${opinion}</span>`;
}

function formatPrice(v) {
  if (v == null || v === 0) return '&mdash;';
  return parseFloat(v).toFixed(2);
}

function renderDecisionCard(decision) {
  const tp = decision.tactical_parameters || {};
  return `
    <section class="card decision-card">
      <h2>Final Decision</h2>
      <div class="decision-header">
        <div class="decision-opinion">${opinionBadge(decision.opinion || 'UNKNOWN')}</div>
        <div class="decision-confidence">
          <span class="confidence-value">${decision.confidence_score != null ? decision.confidence_score.toFixed(1) + '%' : '&mdash;'}</span>
          <span class="confidence-label">Confidence</span>
        </div>
      </div>
      <div class="tactical-grid">
        <div class="tactical-item">
          <span class="tactical-label">Current Price</span>
          <span class="tactical-value mono">${formatPrice(tp.current_price)}</span>
        </div>
        <div class="tactical-item">
          <span class="tactical-label">Entry</span>
          <span class="tactical-value mono">${formatPrice(tp.entry)}</span>
        </div>
        <div class="tactical-item">
          <span class="tactical-label">Take Profit</span>
          <span class="tactical-value mono profit">${formatPrice(tp.take_profit)}</span>
        </div>
        <div class="tactical-item">
          <span class="tactical-label">Stop Loss</span>
          <span class="tactical-value mono loss">${formatPrice(tp.stop_loss)}</span>
        </div>
        <div class="tactical-item">
          <span class="tactical-label">RR Ratio</span>
          <span class="tactical-value mono">${tp.rr_ratio != null ? tp.rr_ratio.toFixed(2) : '&mdash;'}</span>
        </div>
        <div class="tactical-item">
          <span class="tactical-label">Waiting Hours</span>
          <span class="tactical-value">${tp.projected_waiting_hours != null ? tp.projected_waiting_hours + 'h' : '&mdash;'}</span>
        </div>
        <div class="tactical-item">
          <span class="tactical-label">Holding Hours</span>
          <span class="tactical-value">${tp.projected_holding_hours != null ? tp.projected_holding_hours + 'h' : '&mdash;'}</span>
        </div>
      </div>
      ${decision.reasoning_chain ? `
      <details class="reasoning-details">
        <summary>Reasoning Chain</summary>
        <pre class="reasoning-text">${decision.reasoning_chain}</pre>
      </details>` : ''}
      ${decision.critic_impact ? `
      <details class="reasoning-details">
        <summary>Critic Impact</summary>
        <pre class="reasoning-text">${decision.critic_impact}</pre>
      </details>` : ''}
    </section>`;
}

function renderMathCheck(math) {
  if (!math || !math.compliance_verdict) return '';
  if (typeof math.compliance_verdict === 'string') return `<p>${math.compliance_verdict}</p>`;
  return `<pre class="reasoning-text">${JSON.stringify(math.compliance_verdict, null, 2)}</pre>`;
}

function renderDebateRounds(debateHistory) {
  if (!debateHistory || !debateHistory.length) return '';
  return `
    <section class="card">
      <h2>Debate Rounds (${debateHistory.length})</h2>
      ${debateHistory.map((r, i) => `
        <details class="debate-round" ${i === debateHistory.length - 1 ? 'open' : ''}>
          <summary>
            <span class="round-label">Round ${r.round || (i + 1)}</span>
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
                <div class="tactical-item"><span class="tactical-label">Entry</span><span class="tactical-value mono">${formatPrice(r.plan.tactical_parameters.entry)}</span></div>
                <div class="tactical-item"><span class="tactical-label">TP</span><span class="tactical-value mono profit">${formatPrice(r.plan.tactical_parameters.take_profit)}</span></div>
                <div class="tactical-item"><span class="tactical-label">SL</span><span class="tactical-value mono loss">${formatPrice(r.plan.tactical_parameters.stop_loss)}</span></div>
                <div class="tactical-item"><span class="tactical-label">RR</span><span class="tactical-value mono">${r.plan.tactical_parameters.rr_ratio != null ? r.plan.tactical_parameters.rr_ratio.toFixed(2) : '&mdash;'}</span></div>
              </div>` : ''}
              ${r.plan.reasoning_chain ? `<pre class="reasoning-text">${r.plan.reasoning_chain}</pre>` : ''}
            </div>` : ''}
            ${r.critic ? `
            <div class="debate-section">
              <h4>Critic Review <span class="round-veto veto-${(r.critic.veto_level || '').toLowerCase()}">${r.critic.veto_level || ''}</span></h4>
              ${r.critic.critic_summary ? `<pre class="reasoning-text">${r.critic.critic_summary}</pre>` : ''}
              ${r.critic.audit_evidence ? `
              <h5>Audit Evidence</h5>
              <pre class="reasoning-text">${r.critic.audit_evidence}</pre>` : ''}
            </div>` : ''}
            ${r.math_fact_check ? `
            <div class="debate-section">
              <h4>Math Fact Check <span class="round-math math-${(r.math_fact_check.status || '').toLowerCase()}">${r.math_fact_check.status || ''}</span></h4>
              ${renderMathCheck(r.math_fact_check)}
            </div>` : ''}
          </div>
        </details>`).join('')}
    </section>`;
}

function renderCharts(visualContext) {
  if (!visualContext) return '';
  const charts = [];
  if (visualContext.macro_snapshot) charts.push({label: 'Macro (1h)', path: visualContext.macro_snapshot});
  if (visualContext.micro_snapshot) charts.push({label: 'Micro (15m)', path: visualContext.micro_snapshot});
  if (!charts.length) return '';
  return `
    <section class="card">
      <h2>Charts</h2>
      <div class="chart-grid">
        ${charts.map(c => `
        <div class="chart-container">
          <h4>${c.label}</h4>
          <p class="chart-path mono">${c.path}</p>
          <img src="/${c.path}" alt="${c.label}" class="chart-img" loading="lazy"
               onerror="this.style.display='none'; this.nextElementSibling.style.display='block';">
          <div class="chart-fallback" style="display:none;">Chart image not available via server</div>
        </div>`).join('')}
      </div>
    </section>`;
}

function renderMetadata(metadata) {
  if (!metadata) return '';
  const vc = metadata.version_control || {};
  return `
    <section class="card">
      <h2>Metadata</h2>
      <div class="metadata-grid">
        ${vc.project_version ? `<div class="metadata-item"><span class="metadata-label">Project Version</span><code>${vc.project_version}</code></div>` : ''}
        ${vc.git_commit ? `<div class="metadata-item"><span class="metadata-label">Git Commit</span><code>${vc.git_commit}</code></div>` : ''}
        ${vc.session_hash ? `<div class="metadata-item"><span class="metadata-label">Session Hash</span><code>${vc.session_hash}</code></div>` : ''}
        ${vc.critic_hash ? `<div class="metadata-item"><span class="metadata-label">Critic Hash</span><code>${vc.critic_hash}</code></div>` : ''}
        ${vc.binary_star_hash ? `<div class="metadata-item"><span class="metadata-label">Binary Star Hash</span><code>${vc.binary_star_hash}</code></div>` : ''}
        ${vc.config_hash ? `<div class="metadata-item"><span class="metadata-label">Config Hash</span><code>${vc.config_hash}</code></div>` : ''}
      </div>
    </section>`;
}
