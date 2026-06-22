"""Server-side session HTML renderer for email notifications.

Produces standalone HTML documents whose structure and styling match the
dashboard session view (session-detail.js + dashboard.css) exactly.
Used by SessionNotifier for email generation and local HTML preview.
"""

import json
from typing import Dict, Any

from src.infrastructure.notifications.base_notifier import BaseEmailTemplate
from src.utils.datetime_utils import to_html_display


class SessionRenderer(BaseEmailTemplate):
    """Renders session data to dark-themed HTML matching the dashboard session view."""

    @staticmethod
    def render(session_data: Dict[str, Any]) -> str:
        obs = session_data.get("observation") or {}
        decision = session_data.get("final_decision") or {}
        symbol = obs.get("symbol", "UNKNOWN")
        display_time = to_html_display(obs.get("observed_at", ""))
        history = session_data.get("debate_history", [])
        visual_context = obs.get("visual_context") or {}
        metadata = session_data.get("metadata")

        fmt = SessionRenderer.fmt

        return f"""
        <html>
        <head>{SessionRenderer.get_styles()}</head>
        <body class="dark">
            <div class="container">
                {SessionRenderer._render_header(symbol, display_time)}
                {SessionRenderer._render_decision_card(decision, fmt)}
                {SessionRenderer._render_debate_rounds(history, fmt)}
                {SessionRenderer._render_charts(visual_context)}
                {SessionRenderer._render_metadata(metadata)}
            </div>
        </body>
        </html>"""

    # ── Section renderers ─────────────────────────────────────────────

    @staticmethod
    def _render_header(symbol: str, display_time: str) -> str:
        return f"""
        <div class="session-header">
            <h2>Session: {symbol}</h2>
            <p class="session-time">Observed: {display_time}</p>
        </div>"""

    @staticmethod
    def _opinion_badge(opinion: str) -> str:
        opinion = (opinion or "UNKNOWN").upper()
        cls = {"BULLISH": "badge-green", "BEARISH": "badge-red"}.get(opinion, "badge-gray")
        return f'<span class="badge {cls}">{opinion}</span>'

    @staticmethod
    def _format_price(v) -> str:
        if v is None or v == 0:
            return "&mdash;"
        try:
            return f"{float(v):.2f}"
        except (ValueError, TypeError):
            return str(v)

    @staticmethod
    def _render_decision_card(decision: Dict[str, Any], fmt) -> str:
        opinion = str(decision.get("opinion") or "UNKNOWN").upper()
        confidence = decision.get("confidence_score")
        tp = decision.get("tactical_parameters") or {}
        reasoning = decision.get("reasoning_chain")
        critic_impact = decision.get("critic_impact")

        conf_display = f"{confidence:.1f}%" if confidence is not None else "&mdash;"
        sp = SessionRenderer._format_price

        return f"""
        <section class="card decision-card">
            <h2>Final Decision</h2>
            <div class="decision-header">
                <div class="decision-opinion">{SessionRenderer._opinion_badge(opinion)}</div>
                <div class="decision-confidence">
                    <span class="confidence-value">{conf_display}</span>
                    <span class="confidence-label">Confidence</span>
                </div>
            </div>
            <div class="tactical-grid">
                <div class="tactical-item">
                    <span class="tactical-label">Current Price</span>
                    <span class="tactical-value mono">{sp(tp.get("current_price"))}</span>
                </div>
                <div class="tactical-item">
                    <span class="tactical-label">Entry</span>
                    <span class="tactical-value mono">{sp(tp.get("entry"))}</span>
                </div>
                <div class="tactical-item">
                    <span class="tactical-label">Take Profit</span>
                    <span class="tactical-value mono profit">{sp(tp.get("take_profit"))}</span>
                </div>
                <div class="tactical-item">
                    <span class="tactical-label">Stop Loss</span>
                    <span class="tactical-value mono loss">{sp(tp.get("stop_loss"))}</span>
                </div>
                <div class="tactical-item">
                    <span class="tactical-label">RR Ratio</span>
                    <span class="tactical-value mono">{tp.get("rr_ratio") if tp.get("rr_ratio") is not None else "&mdash;"}</span>
                </div>
                <div class="tactical-item">
                    <span class="tactical-label">Waiting Hours</span>
                    <span class="tactical-value">{tp.get("projected_waiting_hours") if tp.get("projected_waiting_hours") is not None else "&mdash;"}h</span>
                </div>
                <div class="tactical-item">
                    <span class="tactical-label">Holding Hours</span>
                    <span class="tactical-value">{tp.get("projected_holding_hours") if tp.get("projected_holding_hours") is not None else "&mdash;"}h</span>
                </div>
            </div>
            {f'''<details class="reasoning-details">
                <summary>Reasoning Chain</summary>
                <pre class="reasoning-text">{reasoning}</pre>
            </details>''' if reasoning else ""}
            {f'''<details class="reasoning-details">
                <summary>Critic Impact</summary>
                <pre class="reasoning-text">{fmt(critic_impact)}</pre>
            </details>''' if critic_impact else ""}
        </section>"""

    @staticmethod
    def _render_debate_rounds(history: list, fmt) -> str:
        if not history:
            return ""

        sp = SessionRenderer._format_price
        rounds = []
        for i, r in enumerate(history):
            plan = r.get("plan") or {}
            critic = r.get("critic") or {}
            math = r.get("math_fact_check") or {}
            veto = str(critic.get("veto_level") or "")
            math_status = str(math.get("status") or "")
            round_num = r.get("round", i + 1)

            plan_tactics = plan.get("tactical_parameters") or {}
            compact_grid = ""
            if plan_tactics:
                compact_grid = f"""
                <div class="tactical-grid compact">
                    <div class="tactical-item"><span class="tactical-label">Entry</span><span class="tactical-value mono">{sp(plan_tactics.get("entry"))}</span></div>
                    <div class="tactical-item"><span class="tactical-label">TP</span><span class="tactical-value mono profit">{sp(plan_tactics.get("take_profit"))}</span></div>
                    <div class="tactical-item"><span class="tactical-label">SL</span><span class="tactical-value mono loss">{sp(plan_tactics.get("stop_loss"))}</span></div>
                    <div class="tactical-item"><span class="tactical-label">RR</span><span class="tactical-value mono">{plan_tactics.get("rr_ratio") if plan_tactics.get("rr_ratio") is not None else "&mdash;"}</span></div>
                </div>"""

            plan_reasoning = plan.get("reasoning_chain") or ""
            critic_summary = critic.get("critic_summary") or ""
            critic_evidence = critic.get("audit_evidence") or ""
            math_verdict = math.get("compliance_verdict") or {}

            rounds.append(f"""
            <details class="debate-round">
                <summary>
                    <span class="round-label">Round {round_num}</span>
                    {f'<span class="round-plan-opinion">{SessionRenderer._opinion_badge(plan.get("opinion") or "?")}</span>' if plan else ""}
                    {f'<span class="round-confidence">{plan.get("confidence_score"):.1f}%</span>' if plan and plan.get("confidence_score") is not None else ""}
                    {f'<span class="round-veto veto-{veto.lower()}">{veto}</span>' if veto else ""}
                    {f'<span class="round-math math-{math_status.lower()}">{math_status}</span>' if math_status else ""}
                </summary>
                <div class="debate-body">
                    {f'''<div class="debate-section">
                        {compact_grid}
                        {f'<pre class="reasoning-text">{plan_reasoning}</pre>' if plan_reasoning else ""}
                    </div>''' if plan else ""}
                    {f'''<div class="debate-section">
                        <h4>Critic Review <span class="round-veto veto-{veto.lower()}">{veto}</span></h4>
                        {f'<pre class="reasoning-text">{critic_summary}</pre>' if critic_summary else ""}
                        {f"<h5>Audit Evidence</h5><pre class=\"reasoning-text\">{critic_evidence}</pre>" if critic_evidence else ""}
                    </div>''' if critic else ""}
                    {f'''<div class="debate-section">
                        <h4>Math Fact Check <span class="round-math math-{math_status.lower()}">{math_status}</span></h4>
                        <pre class="reasoning-text">{json.dumps(math_verdict, indent=2)}</pre>
                    </div>''' if math else ""}
                </div>
            </details>""")

        return f"""
        <section class="card">
            <h2>Debate Rounds ({len(history)})</h2>
            {"".join(rounds)}
        </section>"""

    @staticmethod
    def _render_charts(visual_context: Dict[str, Any]) -> str:
        if not visual_context:
            return ""

        charts = []
        if visual_context.get("macro_snapshot"):
            charts.append(("Macro (1h)", "macro_snapshot"))
        if visual_context.get("micro_snapshot"):
            charts.append(("Micro (15m)", "micro_snapshot"))

        if not charts:
            return ""

        items = ""
        for label, cid in charts:
            items += f"""
            <div class="chart-container">
                <h4>{label}</h4>
                <img src="cid:{cid}" alt="{label}" class="chart-img">
            </div>"""

        return f"""
        <section class="card">
            <h2>Charts</h2>
            <div class="chart-grid">{items}
            </div>
        </section>"""

    @staticmethod
    def _render_metadata(metadata: Dict[str, Any]) -> str:
        if not metadata:
            return ""
        vc = (metadata.get("version_control") or {}) if isinstance(metadata, dict) else {}
        items = []
        if vc.get("project_version"):
            items.append(f'<div class="metadata-item"><span class="metadata-label">Project Version</span><code>{vc["project_version"]}</code></div>')
        if vc.get("git_commit"):
            items.append(f'<div class="metadata-item"><span class="metadata-label">Git Commit</span><code>{vc["git_commit"]}</code></div>')
        if vc.get("session_hash"):
            items.append(f'<div class="metadata-item"><span class="metadata-label">Session Hash</span><code>{vc["session_hash"]}</code></div>')
        if vc.get("critic_hash"):
            items.append(f'<div class="metadata-item"><span class="metadata-label">Critic Hash</span><code>{vc["critic_hash"]}</code></div>')
        if vc.get("binary_star_hash"):
            items.append(f'<div class="metadata-item"><span class="metadata-label">Binary Star Hash</span><code>{vc["binary_star_hash"]}</code></div>')
        if vc.get("config_hash"):
            items.append(f'<div class="metadata-item"><span class="metadata-label">Config Hash</span><code>{vc["config_hash"]}</code></div>')
        if not items:
            return ""

        return f"""
        <section class="card">
            <h2>Metadata</h2>
            <div class="metadata-grid">{"".join(items)}
            </div>
        </section>"""

    # ── Styles (extracted from dashboard.css, hardcoded for email) ──

    @staticmethod
    def get_styles() -> str:
        return """
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <style>
                /* ── Variables & Base ── */
                :root {
                    --bg-primary: #0d1117; --bg-secondary: #161b22; --bg-card: #1c2333;
                    --bg-card-hover: #21283a; --bg-input: #0d1117;
                    --border-color: #30363d; --border-muted: #21262d;
                    --text-primary: #e6edf3; --text-secondary: #8b949e; --text-muted: #6e7681;
                    --accent-blue: #58a6ff; --accent-green: #3fb950; --accent-red: #f85149;
                    --accent-orange: #d29922; --accent-purple: #a371f7;
                    --badge-green-bg: rgba(63, 185, 80, 0.15); --badge-green-text: #3fb950;
                    --badge-green-border: rgba(63, 185, 80, 0.4);
                    --badge-red-bg: rgba(248, 81, 73, 0.15); --badge-red-text: #f85149;
                    --badge-red-border: rgba(248, 81, 73, 0.4);
                    --badge-gray-bg: rgba(139, 148, 158, 0.15); --badge-gray-text: #8b949e;
                    --badge-gray-border: rgba(139, 148, 158, 0.4);
                    --radius: 8px; --radius-sm: 4px;
                    --shadow: 0 1px 3px rgba(0,0,0,0.3);
                }
                *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
                body.dark {
                    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Oxygen,
                        Ubuntu, Cantarell, "Fira Sans", "Droid Sans", "Helvetica Neue", Arial, sans-serif;
                    background: var(--bg-primary); color: var(--text-primary); line-height: 1.6;
                }
                a { color: var(--accent-blue); text-decoration: none; }
                code, pre, .mono {
                    font-family: "SF Mono", "Fira Code", Consolas, monospace;
                }

                /* ── Container & Card ── */
                .container { max-width: 1200px; margin: 0 auto; padding: 24px; }
                .card {
                    background: var(--bg-card); border: 1px solid var(--border-muted);
                    border-radius: var(--radius); padding: 20px 24px; margin-bottom: 20px;
                }
                .card h2 { font-size: 1.1rem; font-weight: 600; margin-bottom: 16px; color: var(--text-primary); }

                /* ── Session Header ── */
                .session-header { margin-bottom: 20px; }
                .session-header h2 { font-size: 1.4rem; font-weight: 700; color: var(--text-primary); margin-bottom: 4px; }
                .session-time { color: var(--text-secondary); font-size: 0.85rem; }

                /* ── Badges ── */
                .badge {
                    display: inline-block; padding: 2px 10px; border-radius: 12px;
                    font-size: 0.75rem; font-weight: 600; letter-spacing: 0.03em;
                    text-transform: uppercase; border: 1px solid transparent;
                }
                .badge-green { background: var(--badge-green-bg); color: var(--badge-green-text); border-color: var(--badge-green-border); }
                .badge-red { background: var(--badge-red-bg); color: var(--badge-red-text); border-color: var(--badge-red-border); }
                .badge-gray { background: var(--badge-gray-bg); color: var(--badge-gray-text); border-color: var(--badge-gray-border); }

                /* ── Decision Card ── */
                .decision-card { border-left: 3px solid var(--accent-blue); }
                .decision-header { display: flex; align-items: center; gap: 20px; margin-bottom: 20px; }
                .decision-opinion .badge { font-size: 0.9rem; padding: 4px 16px; }
                .decision-confidence { display: flex; flex-direction: column; }
                .confidence-value { font-size: 1.5rem; font-weight: 700; color: var(--accent-blue); }
                .confidence-label { font-size: 0.75rem; color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.05em; }

                /* ── Tactical Grid ── */
                .tactical-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(160px, 1fr)); gap: 16px; margin-bottom: 16px; }
                .tactical-grid.compact { grid-template-columns: repeat(auto-fill, minmax(120px, 1fr)); gap: 10px; }
                .tactical-item { display: flex; flex-direction: column; gap: 4px; padding: 10px 12px; background: var(--bg-secondary); border-radius: var(--radius-sm); }
                .tactical-label { font-size: 0.7rem; color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.05em; }
                .tactical-value { font-size: 1rem; font-weight: 600; color: var(--text-primary); }
                .tactical-value.profit { color: var(--accent-green); }
                .tactical-value.loss { color: var(--accent-red); }

                /* ── Reasoning ── */
                .reasoning-details { margin-top: 8px; }
                .reasoning-details summary { cursor: pointer; color: var(--text-secondary); font-size: 0.85rem; font-weight: 500; padding: 6px 0; }
                .reasoning-text {
                    background: var(--bg-secondary); border: 1px solid var(--border-muted);
                    border-radius: var(--radius-sm); padding: 14px; font-size: 0.8rem;
                    line-height: 1.5; color: var(--text-secondary); white-space: pre-wrap;
                    word-break: break-word; max-height: 400px; overflow-y: auto; margin-top: 8px;
                }

                /* ── Debate Rounds ── */
                .debate-round { border: 1px solid var(--border-muted); border-radius: var(--radius); margin-bottom: 12px; overflow: hidden; }
                .debate-round summary {
                    display: flex; align-items: center; gap: 10px; padding: 12px 16px;
                    background: var(--bg-secondary); cursor: pointer; font-weight: 500;
                    font-size: 0.9rem; user-select: none;
                }
                .round-label { color: var(--text-primary); font-weight: 600; }
                .round-plan-opinion .badge { font-size: 0.7rem; }
                .round-confidence { color: var(--text-secondary); font-size: 0.85rem; }
                .round-veto {
                    padding: 1px 8px; border-radius: 10px; font-size: 0.7rem; font-weight: 600;
                    text-transform: uppercase; letter-spacing: 0.03em; margin-left: auto;
                }
                .round-math {
                    padding: 1px 8px; border-radius: 10px; font-size: 0.7rem; font-weight: 600;
                    text-transform: uppercase; letter-spacing: 0.03em;
                }
                .veto-pass { background: var(--badge-green-bg); color: var(--badge-green-text); }
                .veto-constructive { background: rgba(210, 153, 34, 0.15); color: var(--accent-orange); }
                .veto-critical { background: var(--badge-red-bg); color: var(--badge-red-text); }
                .math-verified { background: var(--badge-green-bg); color: var(--badge-green-text); }
                .math-failed { background: var(--badge-red-bg); color: var(--badge-red-text); }
                .debate-body { padding: 16px; }
                .debate-section { margin-bottom: 14px; }
                .debate-section:last-child { margin-bottom: 0; }
                .debate-section h4 { font-size: 0.85rem; font-weight: 600; margin-bottom: 8px; color: var(--text-primary); display: flex; align-items: center; gap: 8px; }
                .debate-section h5 { font-size: 0.8rem; font-weight: 600; margin-bottom: 6px; margin-top: 10px; color: var(--text-secondary); }

                /* ── Charts ── */
                .chart-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(400px, 1fr)); gap: 16px; }
                .chart-container { background: var(--bg-secondary); border-radius: var(--radius-sm); padding: 12px; }
                .chart-container h4 { font-size: 0.85rem; font-weight: 600; margin-bottom: 8px; color: var(--text-secondary); }
                .chart-img { width: 100%; border-radius: var(--radius-sm); border: 1px solid var(--border-muted); }

                /* ── Metadata ── */
                .metadata-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 12px; }
                .metadata-item { display: flex; flex-direction: column; gap: 4px; padding: 8px 12px; background: var(--bg-secondary); border-radius: var(--radius-sm); }
                .metadata-label { font-size: 0.7rem; color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.05em; }
                .metadata-item code { font-size: 0.8rem; color: var(--accent-purple); }

                /* ── Responsive ── */
                @media only screen and (max-width: 600px) {
                    .container { padding: 12px !important; }
                    .chart-grid { grid-template-columns: 1fr; }
                    .tactical-grid { grid-template-columns: 1fr 1fr; }
                }
            </style>"""
