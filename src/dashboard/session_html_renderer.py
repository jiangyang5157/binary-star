"""Server-side session HTML renderer for email notifications.

Produces standalone HTML documents with embedded dark-theme CSS
matching the dashboard web UI. Used by SessionNotifier for email
generation and local HTML preview.
"""

import json
from typing import Dict, Any

from src.infrastructure.notifications.base_notifier import BaseEmailTemplate
from src.utils.datetime_utils import to_html_display


class SessionRenderer(BaseEmailTemplate):
    """Renders session data to dark-themed HTML for email embedding."""

    @staticmethod
    def render(session_data: Dict[str, Any]) -> str:
        obs = session_data.get("observation") or {}
        decision = session_data.get("final_decision") or {}
        symbol = obs.get("symbol", "UNKNOWN")
        display_time = to_html_display(obs.get("observed_at", ""))

        opinion = str(decision.get("opinion", "NEUTRAL") or "NEUTRAL").upper()
        confidence = decision.get("confidence_score", 0)
        reasoning = decision.get("reasoning_chain", "No description provided.")

        tactical = decision.get("tactical_parameters") or {}
        rr_display = tactical.get("rr_ratio")
        rr_display = rr_display if rr_display is not None else "N/A"

        proj_wait = tactical.get("projected_waiting_hours") or 0
        proj_hold = tactical.get("projected_holding_hours") or 0

        # Regime detection
        history = session_data.get("debate_history", [])
        last_round = history[-1] if history else {}
        verdict = last_round.get("math_fact_check", {}).get("compliance_verdict", {})
        sl_shielded = verdict.get("sl_is_shielded", False)

        vr_val = obs.get("quantitative_metrics", {}).get("price_dynamics", {}).get("volatility_expansion_index", 0)
        regime_cfg = session_data.get("metadata", {}).get("config_snapshot", {}).get("regime_parameters", {})
        vr_extreme = regime_cfg.get("volatility_extreme_ratio")
        is_chaos = float(vr_val or 0) > float(vr_extreme) if vr_extreme is not None else False

        colors = {"BULLISH": "#10b981", "BEARISH": "#ef4444", "NEUTRAL": "#64748b"}
        theme_color = colors.get(opinion, "#64748b")
        display_opinion = "STAND ASIDE" if opinion == "NEUTRAL" else opinion
        fmt = SessionRenderer.fmt

        # Confidence matrix
        def get_row_style(min_val, max_val):
            return 'class="matrix-highlight"' if min_val <= confidence < max_val else ""

        matrix_html = f"""
        <table class="matrix-table">
            <thead>
                <tr><th>Confidence</th><th>Rating</th><th>Action</th></tr>
            </thead>
            <tbody>
                <tr {get_row_style(90, 101)}><td>90-100</td><td>DIAMOND</td><td>Precision Deployment</td></tr>
                <tr {get_row_style(70, 90)}><td>70-90</td><td>HARDENED</td><td>Reinforced Entry</td></tr>
                <tr {get_row_style(50, 70)}><td>50-70</td><td>SHIELDED</td><td>Defensive Buffer (DLE)</td></tr>
                <tr {get_row_style(0, 50)}><td>0-50</td><td>FRAGILE</td><td>Systemic Halt</td></tr>
            </tbody>
        </table>"""

        # Debate rounds
        debate_html = ""
        if history:
            rounds = []
            for i, r in enumerate(history):
                plan = r.get("plan") or {}
                critic = r.get("critic") or {}
                math = r.get("math_fact_check") or {}
                veto = critic.get("veto_level", "")
                math_status = math.get("status", "")
                rounds.append(f"""
                <details class="debate-round" {"open" if i == len(history) - 1 else ""}>
                    <summary>
                        <span class="round-label">Round {r.get("round", i + 1)}</span>
                        {f'<span class="badge badge-green">{plan.get("opinion", "?")}</span>' if plan else ""}
                        {f'<span class="round-confidence">{plan.get("confidence_score", 0):.1f}%</span>' if plan and plan.get("confidence_score") is not None else ""}
                        {f'<span class="round-veto veto-{veto.lower()}">{veto}</span>' if veto else ""}
                        {f'<span class="round-math math-{math_status.lower()}">{math_status}</span>' if math_status else ""}
                    </summary>
                    <div class="debate-body">
                        {f'<div class="debate-section"><pre class="reasoning-text">{plan.get("reasoning_chain", "")}</pre></div>' if plan else ""}
                        {f'<div class="debate-section"><h4>Critic Review</h4><pre class="reasoning-text">{critic.get("critic_summary", "")}</pre></div>' if critic else ""}
                        {f'<div class="debate-section"><h4>Math Fact Check</h4><pre class="reasoning-text">{json.dumps(math.get("compliance_verdict", {}), indent=2)}</pre></div>' if math else ""}
                    </div>
                </details>""")
            debate_html = f"""
            <div class="card">
                <h3>Debate Rounds ({len(history)})</h3>
                {"".join(rounds)}
            </div>"""

        return f"""
        <html>
        <head>{SessionRenderer.get_styles()}</head>
        <body>
            <div class="container">
                <!-- Header -->
                <div class="session-header">
                    <span class="badge {"badge-green" if opinion == "BULLISH" else "badge-red" if opinion == "BEARISH" else "badge-gray"}">{display_opinion}</span>
                    <h1>{symbol} Session</h1>
                    <p class="session-time">Confidence: <b style="color:{theme_color}">{confidence}%</b> | {display_time}</p>
                </div>

                <!-- Final Decision -->
                <div class="card decision-card">
                    <h2>Final Decision</h2>
                    <div class="tactical-grid">
                        <div class="tactical-item"><span class="tactical-label">Current Price</span><span class="tactical-value mono">{fmt(tactical.get("current_price"))}</span></div>
                        <div class="tactical-item"><span class="tactical-label">Entry</span><span class="tactical-value mono">{fmt(tactical.get("entry"))}</span></div>
                        <div class="tactical-item"><span class="tactical-label">Take Profit</span><span class="tactical-value mono profit">{fmt(tactical.get("take_profit"))}</span></div>
                        <div class="tactical-item"><span class="tactical-label">Stop Loss</span><span class="tactical-value mono loss">{fmt(tactical.get("stop_loss"))}</span></div>
                        <div class="tactical-item"><span class="tactical-label">RR Ratio</span><span class="tactical-value mono">{rr_display}</span></div>
                        <div class="tactical-item"><span class="tactical-label">Waiting Hours</span><span class="tactical-value">{SessionRenderer.format_duration(proj_wait)}</span></div>
                        <div class="tactical-item"><span class="tactical-label">Holding Hours</span><span class="tactical-value">{SessionRenderer.format_duration(proj_hold)}</span></div>
                    </div>
                    <div class="reasoning-details">
                        <h4>Reasoning Chain</h4>
                        <pre class="reasoning-text">{SessionRenderer.render_md(reasoning)}</pre>
                    </div>
                    {f'<div class="reasoning-details"><h4>Critic Impact</h4><pre class="reasoning-text">{fmt(decision.get("audit_impact"))}</pre></div>' if decision.get("audit_impact") else ""}
                </div>

                <!-- Audit Matrix -->
                <div class="card">
                    <h2>Audit Matrix</h2>
                    <div class="status-pills">
                        <span class="status-pill {"pill-chaos" if is_chaos else "pill-safe"}">{"CHAOS" if is_chaos else "SAFE"} Regime</span>
                        <span class="status-pill {"pill-shielded" if sl_shielded else "pill-exposed"}">{"SHIELDED" if sl_shielded else "EXPOSED"} Armor</span>
                    </div>
                    {matrix_html}
                    {f'<div class="warning-banner chaos">Chaos Regime: Extreme physical friction. Slippage risk detected. Manual audit required.</div>' if is_chaos else ""}
                    {f'<div class="warning-banner exposed">Exposed Armor: SL lacks structural shielding. Risk of liquidity wicks. Reduce sizing.</div>' if not sl_shielded else ""}
                </div>

                <!-- Debate Rounds -->
                {debate_html}

                <!-- Charts -->
                <div class="card">
                    <h2>Visual Context</h2>
                    <div class="chart-grid">
                        <div class="chart-container">
                            <h4>Macro (1h)</h4>
                            <img src="cid:macro_snapshot" style="width:100%;border-radius:8px;">
                        </div>
                        <div class="chart-container">
                            <h4>Micro (15m)</h4>
                            <img src="cid:micro_snapshot" style="width:100%;border-radius:8px;">
                        </div>
                    </div>
                </div>

                <!-- Metadata -->
                <div class="card">
                    <h2>Metadata</h2>
                    <div class="metadata-grid">
                        {SessionRenderer._render_metadata(session_data.get("metadata"))}
                    </div>
                </div>

                {SessionRenderer.render_footer(session_data, "Auto-generated by Singularity | Session Engine")}
            </div>
        </body>
        </html>"""

    @staticmethod
    def _render_metadata(metadata: Dict[str, Any]) -> str:
        if not metadata:
            return ""
        vc = metadata.get("version_control") or {}
        parts = []
        if vc.get("project_version"):
            parts.append(f'<div class="metadata-item"><span class="metadata-label">Version</span><code>{vc["project_version"]}</code></div>')
        if vc.get("git_commit"):
            parts.append(f'<div class="metadata-item"><span class="metadata-label">Commit</span><code>{vc["git_commit"]}</code></div>')
        if vc.get("session_hash"):
            parts.append(f'<div class="metadata-item"><span class="metadata-label">Session Hash</span><code>{vc["session_hash"]}</code></div>')
        if vc.get("critic_hash"):
            parts.append(f'<div class="metadata-item"><span class="metadata-label">Critic Hash</span><code>{vc["critic_hash"]}</code></div>')
        if vc.get("binary_star_hash"):
            parts.append(f'<div class="metadata-item"><span class="metadata-label">Binary Star Hash</span><code>{vc["binary_star_hash"]}</code></div>')
        if vc.get("config_hash"):
            parts.append(f'<div class="metadata-item"><span class="metadata-label">Config Hash</span><code>{vc["config_hash"]}</code></div>')
        return "".join(parts)

    @staticmethod
    def get_styles() -> str:
        """Dark-themed styles matching the dashboard web UI."""
        return """
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <style>
                body {
                    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
                    line-height: 1.5; color: #e2e8f0; margin: 0; padding: 20px;
                    background-color: #0f172a;
                }
                .container {
                    max-width: 850px; margin: 0 auto;
                    background: #1e293b; border-radius: 12px;
                    box-shadow: 0 10px 15px -3px rgba(0,0,0,0.4);
                    padding: 40px; border: 1px solid #334155;
                }
                .badge {
                    display: inline-block; padding: 4px 12px; border-radius: 9999px;
                    font-size: 12px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.05em;
                }
                .badge-green { background: #065f4620; color: #34d399; border: 1px solid #34d39940; }
                .badge-red { background: #7f1d1d20; color: #f87171; border: 1px solid #f8717140; }
                .badge-gray { background: #334155; color: #94a3b8; border: 1px solid #475569; }
                .card {
                    background: #1e293b; border: 1px solid #334155; border-radius: 10px;
                    padding: 20px; margin-bottom: 20px;
                }
                h1 { color: #f1f5f9; font-size: 28px; margin: 0 0 4px 0; }
                h2 { color: #f1f5f9; font-size: 18px; margin: 0 0 16px 0; }
                h3 { color: #e2e8f0; font-size: 15px; margin: 0 0 12px 0; }
                h4 { color: #94a3b8; font-size: 12px; text-transform: uppercase; margin: 0 0 8px 0; }
                .session-header { text-align: center; margin-bottom: 30px; padding-bottom: 20px; border-bottom: 1px solid #334155; }
                .session-time { color: #94a3b8; font-size: 13px; margin-top: 4px; }
                .tactical-grid {
                    display: grid; grid-template-columns: repeat(auto-fill, minmax(120px, 1fr));
                    gap: 12px; margin-bottom: 16px;
                }
                .tactical-item {
                    background: #0f172a; border: 1px solid #334155; border-radius: 8px;
                    padding: 12px; text-align: center;
                }
                .tactical-label { font-size: 10px; color: #64748b; text-transform: uppercase; font-weight: 700; display: block; margin-bottom: 4px; }
                .tactical-value { font-size: 16px; color: #e2e8f0; font-weight: 800; }
                .mono { font-family: "SF Mono", "Courier New", monospace; }
                .profit { color: #34d399; }
                .loss { color: #f87171; }
                .reasoning-details { margin-top: 12px; }
                .reasoning-text {
                    background: #0f172a; color: #cbd5e1; padding: 16px; border-radius: 8px;
                    font-size: 12px; line-height: 1.6; white-space: pre-wrap; overflow-x: auto;
                }
                .status-pills { display: flex; gap: 8px; margin-bottom: 16px; }
                .status-pill {
                    display: inline-block; padding: 4px 10px; border-radius: 6px;
                    font-size: 11px; font-weight: 700; text-transform: uppercase;
                }
                .pill-safe { background: #065f4620; color: #34d399; border: 1px solid #34d39940; }
                .pill-chaos { background: #7f1d1d20; color: #f87171; border: 1px solid #f8717140; }
                .pill-shielded { background: #1e3a5f20; color: #60a5fa; border: 1px solid #60a5fa40; }
                .pill-exposed { background: #78350f20; color: #fbbf24; border: 1px solid #fbbf2440; }
                .warning-banner {
                    text-align: center; padding: 10px; border-radius: 8px; margin-bottom: 8px;
                    font-size: 11px; font-weight: 600; line-height: 1.5;
                }
                .warning-banner.chaos { background: #7f1d1d20; color: #f87171; border: 1px solid #f8717140; }
                .warning-banner.exposed { background: #78350f20; color: #fbbf24; border: 1px solid #fbbf2440; }
                .matrix-table {
                    width: 100%; border-collapse: separate; border-spacing: 0;
                    border-radius: 8px; border: 1px solid #334155; overflow: hidden; margin-top: 10px;
                }
                .matrix-table th { background: #0f172a; color: #94a3b8; font-size: 10px; padding: 8px; text-align: center; border-bottom: 1px solid #334155; }
                .matrix-table td { font-size: 11px; padding: 10px 8px; text-align: center; border-bottom: 1px solid #1e293b; color: #cbd5e1; }
                .matrix-table tr:last-child td { border-bottom: none; }
                .matrix-highlight { background: #0f172a; font-weight: 600; color: #f1f5f9; }
                .debate-round { margin-bottom: 12px; border: 1px solid #334155; border-radius: 8px; }
                .debate-round summary { padding: 10px 16px; cursor: pointer; color: #e2e8f0; font-weight: 600; background: #0f172a; border-radius: 8px; }
                .debate-body { padding: 16px; }
                .debate-section { margin-bottom: 12px; }
                .round-label { margin-right: 8px; }
                .round-veto { display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 11px; font-weight: 700; margin-left: 8px; }
                .veto-pass { background: #065f4620; color: #34d399; }
                .veto-weak { background: #78350f20; color: #fbbf24; }
                .veto-terminal { background: #7f1d1d20; color: #f87171; }
                .veto-constructive { background: #1e3a5f20; color: #60a5fa; }
                .round-math { display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 11px; font-weight: 700; margin-left: 4px; }
                .math-verified { background: #065f4620; color: #34d399; }
                .math-error { background: #7f1d1d20; color: #f87171; }
                .math-skipped { background: #334155; color: #94a3b8; }
                .chart-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
                .chart-container { text-align: center; }
                .chart-container img { max-width: 100%; }
                .metadata-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap: 8px; }
                .metadata-item { padding: 8px 12px; background: #0f172a; border-radius: 6px; }
                .metadata-label { font-size: 10px; color: #64748b; text-transform: uppercase; display: block; margin-bottom: 2px; }
                code { font-size: 11px; color: #94a3b8; font-family: "SF Mono", "Courier New", monospace; }
                @media only screen and (max-width: 600px) {
                    .container { padding: 20px !important; }
                    .chart-grid { grid-template-columns: 1fr; }
                }
            </style>
        """
