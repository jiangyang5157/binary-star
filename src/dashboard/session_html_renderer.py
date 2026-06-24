"""Server-side session HTML renderer for email notifications.

Produces standalone, email-safe HTML documents with hardcoded inline styles.
Email clients (Gmail, Outlook) strip <style> blocks and don't support CSS
variables, <details>, or CSS Grid — so everything is inlined with style=""
attributes and table-based layouts.
"""

import json
from typing import Dict, Any

from src.infrastructure.notifications.base_notifier import BaseEmailTemplate
from src.utils.datetime_utils import to_html_display


# ── Hardcoded dark-theme palette (email-safe, no CSS variables) ──

C = {
    "bg":           "#0d1117",
    "bg2":          "#161b22",
    "card":         "#1c2333",
    "border":       "#30363d",
    "text":         "#e6edf3",
    "text2":        "#8b949e",
    "text3":        "#6e7681",
    "blue":         "#58a6ff",
    "green":        "#3fb950",
    "red":          "#f85149",
    "orange":       "#d29922",
    "purple":       "#a371f7",
    "badge_green_bg":  "rgba(63,185,80,0.15)",
    "badge_green_txt": "#3fb950",
    "badge_red_bg":    "rgba(248,81,73,0.15)",
    "badge_red_txt":   "#f85149",
    "badge_gray_bg":   "rgba(139,148,158,0.15)",
    "badge_gray_txt":  "#8b949e",
}


def _s(**kwargs) -> str:
    """Build an inline style string from keyword arguments (camelCase→kebab-case)."""
    parts = []
    for k, v in kwargs.items():
        css_key = "".join(
            f"-{c.lower()}" if c.isupper() else c for c in k
        )
        parts.append(f"{css_key}: {v}")
    return "; ".join(parts)


class SessionRenderer(BaseEmailTemplate):
    """Renders session data to dark-themed, email-safe HTML with inline styles."""

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

        return f"""\
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
</head>
<body style="{_s(background=C['bg'], color=C['text'], fontFamily='-apple-system,BlinkMacSystemFont,Segoe UI,Roboto,Oxygen,Ubuntu,Cantarell,Helvetica Neue,Arial,sans-serif', lineHeight='1.6', margin='0', padding='0')}">
    <div style="{_s(maxWidth='640px', margin='0 auto', padding='24px 16px')}">
        {SessionRenderer._render_header(symbol, display_time)}
        {SessionRenderer._render_decision_card(decision, fmt)}
        {SessionRenderer._render_debate_rounds(history, fmt)}
        {SessionRenderer._render_charts(visual_context)}
        {SessionRenderer._render_metadata(metadata)}
        {SessionRenderer._render_footer()}
    </div>
</body>
</html>"""

    # ── Section renderers ─────────────────────────────────────────────

    @staticmethod
    def _render_header(symbol: str, display_time: str) -> str:
        return f"""\
<div style="{_s(marginBottom='24px', borderBottom=f'1px solid {C["border"]}', paddingBottom='16px')}">
    <h2 style="{_s(fontSize='20px', fontWeight='700', color=C['text'], margin='0 0 4px 0')}">Session: {symbol}</h2>
    <p style="{_s(fontSize='13px', color=C['text2'], margin='0')}">Observed: {display_time}</p>
</div>"""

    @staticmethod
    def _opinion_badge(opinion: str) -> str:
        opinion = (opinion or "UNKNOWN").upper()
        if opinion == "BULLISH":
            bg, c, bc = C["badge_green_bg"], C["badge_green_txt"], C["green"]
        elif opinion == "BEARISH":
            bg, c, bc = C["badge_red_bg"], C["badge_red_txt"], C["red"]
        else:
            bg, c, bc = C["badge_gray_bg"], C["badge_gray_txt"], C["text3"]
        return f'<span style="{_s(display="inline-block", padding="3px 12px", borderRadius="12px", fontSize="12px", fontWeight="600", textTransform="uppercase", letterSpacing="0.03em", background=bg, color=c, border=f"1px solid {bc}")}">{opinion}</span>'

    @staticmethod
    def _format_price(v) -> str:
        if v is None or v == 0:
            return "&mdash;"
        try:
            return f"{float(v):.2f}"
        except (ValueError, TypeError):
            return str(v)

    @staticmethod
    def _tactical_row(label: str, value: str, color: str = None) -> str:
        c = color or C["text"]
        return f"""\
<tr>
    <td style="{_s(padding="8px 12px", fontSize="11px", color=C['text3'], textTransform="uppercase", letterSpacing="0.05em", whiteSpace="nowrap")}">{label}</td>
    <td style="{_s(padding="8px 12px", fontSize="14px", fontWeight="600", color=c, fontFamily='"SF Mono","Fira Code",Consolas,monospace', textAlign="right")}">{value}</td>
</tr>"""

    @staticmethod
    def _render_decision_card(decision: Dict[str, Any], fmt) -> str:
        opinion = str(decision.get("opinion") or "UNKNOWN").upper()
        confidence = decision.get("confidence_score")
        tp = decision.get("tactical_parameters") or {}
        reasoning = decision.get("reasoning_chain")
        critic_impact = decision.get("critic_impact")

        conf_display = f"{confidence:.1f}%" if confidence is not None else "&mdash;"
        sp = SessionRenderer._format_price

        rows = "".join([
            SessionRenderer._tactical_row("Current Price", sp(tp.get("current_price"))),
            SessionRenderer._tactical_row("Entry", sp(tp.get("entry"))),
            SessionRenderer._tactical_row("Take Profit", sp(tp.get("take_profit")), C["green"]),
            SessionRenderer._tactical_row("Stop Loss", sp(tp.get("stop_loss")), C["red"]),
            SessionRenderer._tactical_row("RR Ratio", str(tp.get("rr_ratio")) if tp.get("rr_ratio") is not None else "&mdash;"),
            SessionRenderer._tactical_row("Wait / Hold", f'{tp.get("projected_waiting_hours", "&mdash;")}h / {tp.get("projected_holding_hours", "&mdash;")}h'),
        ])

        reasoning_html = ""
        if reasoning:
            reasoning_html = f"""\
<div style="{_s(marginTop='16px', padding='12px', background=C['bg2'], borderRadius='6px', border=f'1px solid {C["border"]}')}">
    <p style="{_s(fontSize='11px', color=C['text3'], textTransform='uppercase', letterSpacing='0.05em', margin='0 0 6px 0')}">Reasoning Chain</p>
    <pre style="{_s(fontSize='12px', lineHeight='1.6', color=C['text2'], whiteSpace='pre-wrap', wordBreak='break-word', margin='0', fontFamily='inherit')}">{reasoning}</pre>
</div>"""

        critic_html = ""
        if critic_impact:
            critic_html = f"""\
<div style="{_s(marginTop='12px', padding='12px', background=C['bg2'], borderRadius='6px', border=f'1px solid {C["border"]}')}">
    <p style="{_s(fontSize='11px', color=C['text3'], textTransform='uppercase', letterSpacing='0.05em', margin='0 0 6px 0')}">Critic Impact</p>
    <pre style="{_s(fontSize='12px', lineHeight='1.6', color=C['text2'], whiteSpace='pre-wrap', wordBreak='break-word', margin='0', fontFamily='inherit')}">{fmt(critic_impact)}</pre>
</div>"""

        return f"""\
<div style="{_s(background=C['card'], border=f'2px solid {C["blue"]}', borderLeft=f'4px solid {C["blue"]}', borderRadius='8px', padding='20px 24px', marginBottom='20px')}">
    <h2 style="{_s(fontSize='15px', fontWeight='600', color=C['text'], margin='0 0 16px 0')}">Final Decision</h2>
    <table cellpadding="0" cellspacing="0" border="0" width="100%" style="{_s(marginBottom='16px')}">
        <tr>
            <td style="{_s(paddingBottom='12px', paddingRight='20px')}">
                <span style="{_s(fontSize='22px', fontWeight='700', color=C['blue'])}">{conf_display}</span>
                <span style="{_s(fontSize='11px', color=C['text3'], textTransform='uppercase', display='block')}">Confidence</span>
            </td>
            <td style="{_s(paddingBottom='12px', verticalAlign='middle')}">
                {SessionRenderer._opinion_badge(opinion)}
            </td>
        </tr>
    </table>
    <table cellpadding="0" cellspacing="0" border="0" width="100%" style="{_s(background=C['bg2'], borderRadius='6px')}">
        {rows}
    </table>
    {reasoning_html}
    {critic_html}
</div>"""

    @staticmethod
    def _render_debate_rounds(history: list, fmt) -> str:
        if not history:
            return ""

        sp = SessionRenderer._format_price
        rounds_html = []
        for i, r in enumerate(history):
            plan = r.get("plan") or {}
            critic = r.get("critic") or {}
            math = r.get("math_fact_check") or {}
            veto = str(critic.get("veto_level") or "")
            math_status = str(math.get("status") or "")
            round_num = r.get("round", i + 1)

            # Veto badge
            veto_colors = {
                "PASS":         (C["badge_green_bg"], C["badge_green_txt"]),
                "WEAK":         ("rgba(88,166,255,0.15)", C["blue"]),
                "CONSTRUCTIVE": ("rgba(210,153,34,0.15)", C["orange"]),
                "TERMINAL":     (C["badge_red_bg"], C["badge_red_txt"]),
            }
            vbg, vc = veto_colors.get(veto, (C["badge_gray_bg"], C["badge_gray_txt"]))
            veto_badge = f'<span style="{_s(display="inline-block", padding="1px 8px", borderRadius="10px", fontSize="11px", fontWeight="600", textTransform="uppercase", background=vbg, color=vc)}">{veto}</span>'
            math_badge = ""
            if math_status:
                math_badge_colors = {
                    "VERIFIED": (C["badge_green_bg"], C["badge_green_txt"]),
                    "SKIPPED":  (C["badge_gray_bg"], C["badge_gray_txt"]),
                }
                mbg, mc = math_badge_colors.get(math_status.upper(), (C["badge_red_bg"], C["badge_red_txt"]))
                math_badge = f'<span style="{_s(display="inline-block", padding="1px 8px", borderRadius="10px", fontSize="11px", fontWeight="600", textTransform="uppercase", background=mbg, color=mc)}">{math_status}</span>'

            plan_opinion = SessionRenderer._opinion_badge(plan.get("opinion") or "?") if plan else ""
            plan_conf = f'<span style="{_s(fontSize="14px", color=C["text2"], fontWeight="500")}">{plan.get("confidence_score", 0):.1f}%</span>' if plan and plan.get("confidence_score") is not None else ""

            # Compact tactical table for this round
            plan_tactics = plan.get("tactical_parameters") or {}
            tactic_rows = ""
            if plan_tactics:
                tactic_rows = "".join([
                    SessionRenderer._tactical_row("Entry", sp(plan_tactics.get("entry"))),
                    SessionRenderer._tactical_row("TP", sp(plan_tactics.get("take_profit")), C["green"]),
                    SessionRenderer._tactical_row("SL", sp(plan_tactics.get("stop_loss")), C["red"]),
                    SessionRenderer._tactical_row("RR", str(plan_tactics.get("rr_ratio")) if plan_tactics.get("rr_ratio") is not None else "&mdash;"),
                ])

            plan_reasoning = plan.get("reasoning_chain") or ""
            critic_summary = critic.get("critic_summary") or ""
            critic_evidence = critic.get("audit_evidence") or ""
            math_verdict = math.get("compliance_verdict") or {}

            round_body = ""
            if plan:
                round_body += f"""\
<div style="{_s(padding='14px')}">
    {f'<table cellpadding="0" cellspacing="0" border="0" width="100%" style="{_s(background=C["bg2"], borderRadius="6px", marginBottom="12px")}">{tactic_rows}</table>' if tactic_rows else ""}
    {f'<div style="{_s(padding="12px", background=C["bg2"], borderRadius="6px", border=f"1px solid {C["border"]}", marginBottom="12px")}"><pre style="{_s(fontSize="12px", lineHeight="1.6", color=C["text2"], whiteSpace="pre-wrap", wordBreak="break-word", margin="0", fontFamily="inherit")}">{plan_reasoning}</pre></div>' if plan_reasoning else ""}
</div>"""

            if critic:
                round_body += f"""\
<div style="{_s(padding='0 14px 14px 14px')}">
    <p style="{_s(fontSize='12px', fontWeight='600', color=C['text'], margin='0 0 8px 0', overflow='hidden')}"><span>Critic Review</span> <span style="{_s(float='right')}">{veto_badge}</span></p>
    {f'<div style="{_s(padding="12px", background=C["bg2"], borderRadius="6px", border=f"1px solid {C["border"]}", marginBottom="12px")}"><pre style="{_s(fontSize="12px", lineHeight="1.6", color=C["text2"], whiteSpace="pre-wrap", wordBreak="break-word", margin="0", fontFamily="inherit")}">{critic_summary}</pre></div>' if critic_summary else ""}
</div>"""
            if critic_evidence:
                round_body += f"""\
<div style="{_s(padding='0 14px 14px 14px')}">
    <p style="{_s(fontSize='12px', fontWeight='600', color=C['text'], margin='0 0 8px 0')}">Audit Evidence</p>
    <pre style="{_s(fontSize='12px', lineHeight='1.6', color=C['text2'], whiteSpace='pre-wrap', wordBreak='break-word', margin='0', fontFamily='inherit', padding='12px', background=C['bg2'], borderRadius='6px', border=f'1px solid {C["border"]}')}">{fmt(critic_evidence)}</pre>
</div>"""

            if math:
                round_body += f"""\
<div style="{_s(padding='0 14px 14px 14px')}">
    <p style="{_s(fontSize='12px', fontWeight='600', color=C['text'], margin='0 0 8px 0', overflow='hidden')}"><span>Math Fact Check</span> <span style="{_s(float='right')}">{math_badge}</span></p>
    <div style="{_s(padding="12px", background=C["bg2"], borderRadius="6px", border=f"1px solid {C["border"]}")}"><pre style="{_s(fontSize="11px", lineHeight="1.5", color=C["text2"], whiteSpace="pre-wrap", wordBreak="break-word", margin="0", fontFamily='"SF Mono","Fira Code",Consolas,monospace')}">{json.dumps(math_verdict, indent=2)}</pre></div>
</div>"""

            rounds_html.append(f"""\
<div style="{_s(background=C['card'], border=f'1px solid {C["border"]}', borderRadius='8px', marginBottom='12px', overflow='hidden')}">
    <div style="{_s(padding='12px 16px', background=C['bg2'], borderBottom=f'1px solid {C["border"]}', fontSize='14px', fontWeight='600', color=C['text'])}">
        Round {round_num}
        <span style="{_s(marginLeft='8px')}">{plan_opinion}</span>
        <span style="{_s(marginLeft='8px')}">{plan_conf}</span>
        <span style="{_s(float='right')}">{veto_badge} {math_badge}</span>
    </div>
    {round_body}
</div>""")

        return f"""\
<div style="{_s(background=C['card'], border=f'1px solid {C["border"]}', borderRadius='8px', padding='20px 24px', marginBottom='20px')}">
    <h2 style="{_s(fontSize='15px', fontWeight='600', color=C['text'], margin='0 0 16px 0')}">Debate Rounds ({len(history)})</h2>
    {"".join(rounds_html)}
</div>"""

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
            items += f"""\
<div style="{_s(background=C['bg2'], borderRadius='6px', padding='12px', marginBottom='12px')}">
    <p style="{_s(fontSize='12px', fontWeight='600', color=C['text2'], margin='0 0 8px 0')}">{label}</p>
    <img src="cid:{cid}" alt="{label}" style="{_s(width='100%', borderRadius='4px', border=f'1px solid {C["border"]}', display='block')}">
</div>"""

        return f"""\
<div style="{_s(background=C['card'], border=f'1px solid {C["border"]}', borderRadius='8px', padding='20px 24px', marginBottom='20px')}">
    <h2 style="{_s(fontSize='15px', fontWeight='600', color=C['text'], margin='0 0 16px 0')}">Charts</h2>
    {items}
</div>"""

    @staticmethod
    def _render_metadata(metadata: Dict[str, Any]) -> str:
        if not metadata:
            return ""
        vc = (metadata.get("version_control") or {}) if isinstance(metadata, dict) else {}
        rows = ""
        for label, key in [
            ("Project Version", "project_version"),
            ("Git Commit", "git_commit"),
            ("Session Hash", "session_hash"),
            ("Critic Hash", "critic_hash"),
            ("Binary Star Hash", "binary_star_hash"),
            ("Config Hash", "config_hash"),
        ]:
            if vc.get(key):
                rows += f"""<tr>
    <td style="{_s(padding="6px 12px", fontSize="11px", color=C['text3'], textTransform="uppercase", letterSpacing="0.05em", whiteSpace="nowrap")}">{label}</td>
    <td style="{_s(padding="6px 12px", fontSize="12px", color=C['purple'], fontFamily='"SF Mono","Fira Code",Consolas,monospace', textAlign="right")}">{vc[key]}</td>
</tr>"""
        if not rows:
            return ""

        return f"""\
<div style="{_s(background=C['card'], border=f'1px solid {C["border"]}', borderRadius='8px', padding='20px 24px', marginBottom='20px')}">
    <h2 style="{_s(fontSize='15px', fontWeight='600', color=C['text'], margin='0 0 12px 0')}">Metadata</h2>
    <table cellpadding="0" cellspacing="0" border="0" width="100%" style="{_s(background=C['bg2'], borderRadius='6px')}">
        {rows}
    </table>
</div>"""

    @staticmethod
    def _render_footer() -> str:
        return f"""\
<div style="{_s(textAlign='center', padding='24px 0', borderTop=f'1px solid {C["border"]}', marginTop='16px')}">
    <p style="{_s(fontSize='11px', color=C['text3'], margin='0')}">Singularity &middot; Automated Notification</p>
</div>"""

    # ── Styles (empty — all styling is inline for email compatibility) ──

    @staticmethod
    def get_styles() -> str:
        return ""
