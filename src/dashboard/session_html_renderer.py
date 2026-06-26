"""Server-side session HTML renderer for email notifications.

Produces standalone, email-safe HTML documents with hardcoded inline styles.
Email clients (Gmail, Outlook) strip <style> blocks and don't support CSS
variables, <details>, or CSS Grid — so everything is inlined with style=""
attributes and table-based layouts.

Design: "The Trading Desk Brief" — a data-dense but scannable one-page report.
Gold accent on softened dark background.  Light sans-serif throughout for a
clean, modern feel; monospace for data precision.  The horizontal hero strip
is the signature element: opinion → confidence → levels in one left-to-right
scan.
"""

import json
from typing import Dict, Any, Optional

from src.infrastructure.notifications.base_notifier import BaseEmailTemplate
from src.utils.datetime_utils import to_html_display


# ── Design tokens ────────────────────────────────────────────────────
# Email-safe inline palette — no CSS variables.  Gold-as-accent avoids
# competing with green/red trading-direction signals.

C = {
    "void":         "#0c1119",   # page background (softened from pure black)
    "surface":      "#151d28",   # card backgrounds
    "elevated":     "#1d2a39",   # nested sections, code blocks
    "border":       "#283648",   # dividers, card borders
    "text":         "#dce3eb",   # primary text
    "muted":        "#8898ac",   # secondary text, labels
    "gold":         "#d4a348",   # brand accent, confidence, key metrics
    "verde":        "#40a85f",   # bullish signals, profit, TP
    "crimson":      "#e0554a",   # bearish signals, risk, SL
    "amber":        "#d98c2e",   # neutral, warnings
    "violet":       "#9488d8",   # metadata, secondary data, debate accent
    "teal":         "#54a0a8",   # charts, quantitative data
    # badge backgrounds
    "bg_bullish":   "rgba(64,168,95,0.15)",
    "bg_bearish":   "rgba(224,85,74,0.15)",
    "bg_neutral":   "rgba(217,140,46,0.15)",
    "bg_pass":      "rgba(64,168,95,0.15)",
    "bg_weak":      "rgba(84,160,168,0.15)",
    "bg_construct": "rgba(217,140,46,0.15)",
    "bg_terminal":  "rgba(224,85,74,0.15)",
    "bg_verified":  "rgba(64,168,95,0.12)",
    "bg_skipped":   "rgba(141,157,176,0.10)",
    "bg_error":     "rgba(224,85,74,0.12)",
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


# ── Type stacks (email-safe, no @font-face) ─────────────────────────
# Lighter sans-serif throughout — avoids the harsh angularity of serif
# on dark backgrounds.  Weight 300 for display, 400 for body.

F = {
    "display":  "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif",
    "body":     "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, 'Helvetica Neue', Arial, sans-serif",
    "mono":     "'SF Mono', 'Fira Code', 'Consolas', 'Monaco', monospace",
}


class SessionRenderer(BaseEmailTemplate):
    """Renders session data to dark-themed, email-safe HTML with inline styles."""

    # ── Public API ──────────────────────────────────────────────────

    @staticmethod
    def render(session_data: Dict[str, Any]) -> str:
        obs = session_data.get("observation") or {}
        decision = session_data.get("final_decision") or {}
        symbol = obs.get("symbol", "UNKNOWN")
        display_time = to_html_display(obs.get("observed_at", ""))
        history = session_data.get("debate_history", [])
        visual_context = obs.get("visual_context") or {}
        metadata = session_data.get("metadata")
        qm = obs.get("quantitative_metrics") or {}
        brief = obs.get("situation_brief") or {}

        fmt = SessionRenderer.fmt

        return f"""\
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
</head>
<body style="{_s(background=C['void'], color=C['text'], fontFamily=F['body'], lineHeight='1.6', margin='0', padding='0')}">
    <div style="{_s(maxWidth='680px', margin='0 auto', padding='28px 18px')}">
        {SessionRenderer._render_header(symbol, display_time, metadata)}
        {SessionRenderer._render_hero(decision, fmt)}
        {SessionRenderer._render_market_dashboard(qm, brief, fmt)}
        {SessionRenderer._render_reasoning(decision, fmt)}
        {SessionRenderer._render_debate_rounds(history, fmt)}
        {SessionRenderer._render_charts(visual_context)}
        {SessionRenderer._render_metadata(metadata)}
        {SessionRenderer._render_footer()}
    </div>
</body>
</html>"""

    # ── Section renderers ───────────────────────────────────────────

    @staticmethod
    def _render_header(symbol: str, display_time: str, metadata: Optional[Dict]) -> str:
        vc = (metadata or {}).get("version_control", {}) if isinstance(metadata, dict) else {}
        version = vc.get("project_version", "")
        version_badge = (
            f'<span style="{_s(fontSize="10px", color=C["muted"], fontFamily=F["mono"], background=C["elevated"], padding="2px 8px", borderRadius="4px", marginLeft="10px", verticalAlign="middle")}">v{version}</span>'
            if version else ""
        )
        return f"""\
<div style="{_s(marginBottom='28px', borderBottom=f'1px solid {C["border"]}', paddingBottom='16px')}">
    <table cellpadding="0" cellspacing="0" border="0" width="100%">
        <tr>
            <td>
                <h1 style="{_s(fontFamily=F['display'], fontSize='24px', fontWeight='300', color=C['text'], margin='0 0 4px 0', letterSpacing='0.01em')}">
                    {symbol}{version_badge}
                </h1>
                <p style="{_s(fontFamily=F['body'], fontSize='12px', color=C['muted'], margin='0', fontWeight='400')}">{display_time}</p>
            </td>
            <td style="{_s(textAlign='right', verticalAlign='bottom')}">
                <span style="{_s(fontFamily=F['mono'], fontSize='10px', color=C['muted'], textTransform='uppercase', letterSpacing='0.08em')}">Session Report</span>
            </td>
        </tr>
    </table>
</div>"""

    # ── Badge helpers ───────────────────────────────────────────────

    @staticmethod
    def _opinion_badge(opinion: str, size: str = "default") -> str:
        """Render a BULLISH / BEARISH / NEUTRAL badge.

        Args:
            opinion: The opinion string.
            size: 'default' for inline use or 'hero' for the hero strip.
        """
        opinion = (opinion or "UNKNOWN").upper()
        if opinion == "BULLISH":
            bg, c, bc = C["bg_bullish"], C["verde"], C["verde"]
        elif opinion == "BEARISH":
            bg, c, bc = C["bg_bearish"], C["crimson"], C["crimson"]
        else:
            bg, c, bc = C["bg_neutral"], C["amber"], C["amber"]

        if size == "hero":
            return f'<span style="{_s(display="inline-block", padding="8px 24px", borderRadius="6px", fontSize="15px", fontWeight="700", textTransform="uppercase", letterSpacing="0.08em", background=bc, color="#ffffff", fontFamily=F["body"])}">{opinion}</span>'
        return f'<span style="{_s(display="inline-block", padding="2px 10px", borderRadius="4px", fontSize="11px", fontWeight="600", textTransform="uppercase", letterSpacing="0.05em", background=bg, color=c, border=f"1px solid {bc}", fontFamily=F["body"])}">{opinion}</span>'

    @staticmethod
    def _veto_badge(veto: str) -> str:
        """Render a debate veto-level badge."""
        veto = (veto or "").upper()
        colors = {
            "PASS":         (C["bg_pass"], C["verde"]),
            "WEAK":         (C["bg_weak"], C["teal"]),
            "CONSTRUCTIVE": (C["bg_construct"], C["amber"]),
            "TERMINAL":     (C["bg_terminal"], C["crimson"]),
        }
        bg, tc = colors.get(veto, (C["bg_skipped"], C["muted"]))
        return f'<span style="{_s(display="inline-block", padding="2px 10px", borderRadius="4px", fontSize="11px", fontWeight="600", textTransform="uppercase", letterSpacing="0.04em", background=bg, color=tc, fontFamily=F["body"])}">{veto or "?"}</span>'

    @staticmethod
    def _math_badge(status: str) -> str:
        """Render a math-fact-check status badge."""
        status = (status or "").upper()
        colors = {
            "VERIFIED": (C["bg_verified"], C["verde"]),
            "SKIPPED":  (C["bg_skipped"], C["muted"]),
        }
        bg, tc = colors.get(status, (C["bg_error"], C["crimson"]))
        return f'<span style="{_s(display="inline-block", padding="2px 10px", borderRadius="4px", fontSize="10px", fontWeight="600", textTransform="uppercase", letterSpacing="0.04em", background=bg, color=tc, fontFamily=F["body"])}">{status}</span>'

    # ── Number formatting ───────────────────────────────────────────

    @staticmethod
    def _fmt_price(v, precision: int = 2) -> str:
        """Format a price value for display."""
        if v is None or v == 0:
            return "&mdash;"
        try:
            return f"{float(v):.{precision}f}"
        except (ValueError, TypeError):
            return str(v)

    @staticmethod
    def _fmt_pct(v) -> str:
        """Format a ratio/value as a percentage string."""
        if v is None:
            return "&mdash;"
        try:
            return f"{float(v):.1f}%"
        except (ValueError, TypeError):
            return str(v)

    # ── Hero strip ──────────────────────────────────────────────────
    # Signature element: opinion → confidence → entry → TP/SL in one
    # left-to-right scan — the trader's decision sequence materialised.

    @staticmethod
    def _render_hero(decision: Dict[str, Any], fmt) -> str:
        opinion = str(decision.get("opinion") or "NEUTRAL").upper()
        confidence = decision.get("confidence_score")
        tp = decision.get("tactical_parameters") or {}

        fp = SessionRenderer._fmt_price
        conf_val = f"{confidence:.1f}%" if confidence is not None else "&mdash;"

        entry = fp(tp.get("entry"))
        take_profit = fp(tp.get("take_profit"))
        stop_loss = fp(tp.get("stop_loss"))
        rr = tp.get("rr_ratio")
        rr_display = f"1:{rr:.1f}" if rr and rr > 0 else "&mdash;"
        current = fp(tp.get("current_price"))
        wait_h = tp.get("projected_waiting_hours")
        hold_h = tp.get("projected_holding_hours")

        return f"""\
<div style="{_s(background=C['surface'], border=f'1px solid {C["border"]}', borderRadius='10px', padding='0', marginBottom='24px', overflow='hidden')}">

    <!-- Hero strip: opinion · confidence · price levels -->
    <table cellpadding="0" cellspacing="0" border="0" width="100%" style="{_s(tableLayout='fixed')}">
        <tr>
            <!-- Opinion -->
            <td style="{_s(padding='20px 24px', verticalAlign='middle', width='25%')}">
                {SessionRenderer._opinion_badge(opinion, size="hero")}
            </td>
            <!-- Confidence -->
            <td style="{_s(padding='20px 8px', verticalAlign='middle', width='20%', textAlign='center')}">
                <span style="{_s(fontSize='36px', fontWeight='700', color=C['gold'], fontFamily=F['mono'], lineHeight='1.1', display='block')}">{conf_val}</span>
                <span style="{_s(fontSize='10px', color=C['muted'], textTransform='uppercase', letterSpacing='0.08em', display='block', marginTop='2px')}">Confidence</span>
            </td>
            <!-- Divider -->
            <td style="{_s(padding='20px 0', verticalAlign='middle', width='1')}">
                <div style="{_s(width='1px', height='56px', background=C['border'])}"></div>
            </td>
            <!-- Price levels -->
            <td style="{_s(padding='12px 24px', verticalAlign='middle', width='54%')}">
                <table cellpadding="0" cellspacing="0" border="0" width="100%">
                    <tr>
                        <td style="{_s(padding='4px 12px 4px 0')}">
                            <span style="{_s(fontSize='10px', color=C['muted'], textTransform='uppercase', letterSpacing='0.06em', display='block')}">Current</span>
                            <span style="{_s(fontSize='13px', fontWeight='600', color=C['text'], fontFamily=F['mono'])}">{current}</span>
                        </td>
                        <td style="{_s(padding='4px 12px')}">
                            <span style="{_s(fontSize='10px', color=C['muted'], textTransform='uppercase', letterSpacing='0.06em', display='block')}">Entry</span>
                            <span style="{_s(fontSize='13px', fontWeight='600', color=C['gold'], fontFamily=F['mono'])}">{entry}</span>
                        </td>
                        <td style="{_s(padding='4px 12px')}">
                            <span style="{_s(fontSize='10px', color=C['muted'], textTransform='uppercase', letterSpacing='0.06em', display='block')}">Profit</span>
                            <span style="{_s(fontSize='13px', fontWeight='600', color=C['verde'], fontFamily=F['mono'])}">{take_profit}</span>
                        </td>
                        <td style="{_s(padding='4px 0 4px 12px')}">
                            <span style="{_s(fontSize='10px', color=C['muted'], textTransform='uppercase', letterSpacing='0.06em', display='block')}">Stop</span>
                            <span style="{_s(fontSize='13px', fontWeight='600', color=C['crimson'], fontFamily=F['mono'])}">{stop_loss}</span>
                        </td>
                    </tr>
                </table>
            </td>
        </tr>
    </table>

    <!-- Bottom bar: RR · wait/hold -->
    <div style="{_s(padding='10px 24px', background=C['elevated'], borderTop=f'1px solid {C["border"]}')}">
        <table cellpadding="0" cellspacing="0" border="0" width="100%">
            <tr>
                <td style="{_s(fontSize='11px', color=C['muted'])}">
                    <span style="{_s(textTransform='uppercase', letterSpacing='0.05em')}">R:R Ratio</span>
                    &nbsp;
                    <span style="{_s(fontWeight='600', color=C['text'], fontFamily=F['mono'])}">{rr_display}</span>
                </td>
                <td style="{_s(fontSize='11px', color=C['muted'], textAlign='right')}">
                    <span style="{_s(textTransform='uppercase', letterSpacing='0.05em')}">Wait</span>
                    &nbsp;
                    <span style="{_s(fontWeight='600', color=C['text'], fontFamily=F['mono'])}">{wait_h if wait_h is not None else '&mdash;'}h</span>
                    &nbsp;&nbsp;
                    <span style="{_s(textTransform='uppercase', letterSpacing='0.05em')}">Hold</span>
                    &nbsp;
                    <span style="{_s(fontWeight='600', color=C['text'], fontFamily=F['mono'])}">{hold_h if hold_h is not None else '&mdash;'}h</span>
                </td>
            </tr>
        </table>
    </div>
</div>"""

    # ── Market dashboard ────────────────────────────────────────────
    # Four metric pills in a row: Regime · Confluence · Signals · ATR.
    # Surfaces quantitative_metrics + situation_brief that were previously
    # invisible in the email.

    @staticmethod
    def _render_market_dashboard(qm: Dict[str, Any], brief: Dict[str, Any], fmt) -> str:
        if not qm and not brief:
            return ""

        # Extract metrics
        pd_ = qm.get("price_dynamics", {}) if qm else {}
        regime_data = qm.get("market_regime", {}) if qm else {}
        struct = qm.get("structural_anchors", {}) if qm else {}
        sentiment = qm.get("sentiment_signals", {}) if qm else {}

        atr_macro = pd_.get("atr_macro")
        regime_note = brief.get("regime_note", "") if brief else ""
        confluence = brief.get("confluence_score") if brief else None
        confluence_dir = brief.get("confluence_direction", "") if brief else ""
        signals_count = brief.get("stacked_signals_count") if brief else None
        gate_result = brief.get("gate_result", "") if brief else ""
        activated_by = brief.get("activated_by", []) if brief else []
        risk_caveats = brief.get("risk_caveats", []) if brief else []

        # ── Build primary metric cards (only those with real data) ──

        primary_cards = []  # list of (label, value_html, accent_color)

        # Regime
        regime_label = str(regime_note)
        if " — " in regime_label:
            regime_label = regime_label.split(" — ")[0]
        if len(regime_label) > 36:
            regime_label = regime_label[:34] + "…"
        if regime_label:
            primary_cards.append(("Regime", regime_label, C["teal"]))

        # Confluence
        if confluence is not None:
            dir_color = C["verde"] if confluence_dir == "BULLISH" else (C["crimson"] if confluence_dir == "BEARISH" else C["muted"])
            confluence_html = f'<span style="{_s(fontFamily=F["mono"], fontSize="18px", fontWeight="700", color=C["gold"])}">{confluence:.2f}</span><span style="{_s(fontSize="10px", color=dir_color, display="block", marginTop="2px")}">{confluence_dir}</span>'
            primary_cards.append(("Confluence", confluence_html, C["gold"]))

        # Signals
        if signals_count is not None and signals_count > 0:
            label = "signal" if signals_count == 1 else "signals"
            signals_val = f'{signals_count} {label}'
            if gate_result:
                gate_color = C["verde"] if gate_result == "PASS" else (C["crimson"] if gate_result == "FAIL" else C["amber"])
                gate_bg = C["bg_pass"] if gate_result == "PASS" else (C["bg_terminal"] if gate_result == "FAIL" else C["bg_neutral"])
                gate_badge = f' <span style="{_s(display="inline-block", padding="2px 8px", borderRadius="4px", fontSize="10px", fontWeight="600", textTransform="uppercase", letterSpacing="0.05em", background=gate_bg, color=gate_color, fontFamily=F["body"])}">{gate_result}</span>'
                signals_val += gate_badge
            primary_cards.append(("Signals", signals_val, C["violet"]))

        # ATR
        if atr_macro is not None:
            try:
                atr_val = f'{float(atr_macro):.1f}'
            except (ValueError, TypeError):
                atr_val = str(atr_macro)
            primary_cards.append(("ATR (1h)", atr_val, C["muted"]))

        # ── Build secondary metric row (only those with real data) ──

        secondary_cards = []  # list of (label, value, color)

        # Trend intensity
        trend = regime_data.get("trend_intensity")
        if trend is not None:
            try:
                trend_val = float(trend)
                if trend_val > 0.3:
                    secondary_cards.append(("Trend", f"↑ {trend_val:+.2f}", C["verde"]))
                elif trend_val < -0.3:
                    secondary_cards.append(("Trend", f"↓ {trend_val:+.2f}", C["crimson"]))
                else:
                    secondary_cards.append(("Trend", f"→ {trend_val:+.2f}", C["amber"]))
            except (ValueError, TypeError):
                pass

        # Squeeze factor
        squeeze = regime_data.get("squeeze_factor")
        if squeeze is not None:
            try:
                secondary_cards.append(("Squeeze", f"{float(squeeze):.1f}x", C["teal"]))
            except (ValueError, TypeError):
                pass

        # POC distance
        poc_dist = struct.get("poc_dist_atr")
        if poc_dist is not None:
            try:
                d = float(poc_dist)
                secondary_cards.append(("POC", f"{d:+.1f} ATR", C["muted"]))
            except (ValueError, TypeError):
                pass

        # CVD intensity
        cvd_intensity = sentiment.get("cvd_intensity_ratio")
        if cvd_intensity is not None:
            try:
                cvd_val = float(cvd_intensity)
                secondary_cards.append(("CVD Δ", f"{cvd_val:+.4f}", C["verde"] if cvd_val >= 0 else C["crimson"]))
            except (ValueError, TypeError):
                pass

        # OI delta
        oi_delta = sentiment.get("oi_delta_micro")
        if oi_delta is not None:
            try:
                oi_val = float(oi_delta) * 100
                secondary_cards.append(("OI Δ", f"{oi_val:+.2f}%", C["verde"] if oi_val >= 0 else C["crimson"]))
            except (ValueError, TypeError):
                pass

        # Funding rate
        funding = sentiment.get("funding_rate")
        if funding is not None:
            try:
                fr = float(funding) * 100
                secondary_cards.append(("Funding", f"{fr:+.4f}%", C["verde"] if fr >= 0 else C["crimson"]))
            except (ValueError, TypeError):
                pass

        # ── Decide whether to render ──────────────────────────────

        has_primary = len(primary_cards) >= 2
        has_secondary = len(secondary_cards) > 0
        has_signals = bool(activated_by)
        has_risks = bool(risk_caveats)

        if not has_primary and not has_secondary and not has_signals and not has_risks:
            return ""

        # ── Render ────────────────────────────────────────────────

        primary_html = ""
        if has_primary:
            col_w = f"{100 // len(primary_cards):.0f}%"
            for label, value, _accent in primary_cards:
                primary_html += f"""\
            <td style="{_s(padding='12px 16px', verticalAlign='top', width=col_w)}">
                <span style="{_s(fontSize='10px', color=C['muted'], textTransform='uppercase', letterSpacing='0.06em', display='block', marginBottom='6px', fontFamily=F['body'])}">{label}</span>
                <span style="{_s(fontSize='13px', fontWeight='600', color=C['text'], fontFamily=F['mono'], lineHeight='1.4')}">{value}</span>
            </td>"""

        secondary_html = ""
        if has_secondary:
            for label, value, accent_color in secondary_cards:
                secondary_html += f"""\
            <td style="{_s(padding='8px 16px', verticalAlign='top')}">
                <span style="{_s(fontSize='10px', color=C['muted'], textTransform='uppercase', letterSpacing='0.05em', display='block', marginBottom='3px', fontFamily=F['body'])}">{label}</span>
                <span style="{_s(fontSize='12px', fontWeight='600', color=accent_color, fontFamily=F['mono'])}">{value}</span>
            </td>"""

        # Activated signals
        signals_html = ""
        if activated_by:
            signal_pills = ""
            for sig in activated_by:
                s_name = sig.get("signal", "?")
                s_dir = sig.get("direction", "")
                s_color = C["verde"] if s_dir == "BULLISH" else (C["crimson"] if s_dir == "BEARISH" else C["amber"])
                s_bg = C["bg_bullish"] if s_dir == "BULLISH" else (C["bg_bearish"] if s_dir == "BEARISH" else C["bg_neutral"])
                signal_pills += f'<span style="{_s(display="inline-block", padding="2px 10px", margin="2px 4px 2px 0", borderRadius="4px", fontSize="10px", fontWeight="600", color=s_color, background=s_bg, border=f"1px solid {s_color}30", fontFamily=F["body"])}">{s_name}</span>'
            signals_html = f"""\
        <tr>
            <td colspan="6" style="{_s(padding='4px 16px 2px 16px')}">
                <span style="{_s(fontSize='10px', color=C['muted'], textTransform='uppercase', letterSpacing='0.06em', marginRight='8px', fontFamily=F['body'])}">Driven by</span>
                {signal_pills}
            </td>
        </tr>"""

        # Risk caveats
        risk_html = ""
        if risk_caveats:
            caveat_items = "".join(
                f'<span style="{_s(display="inline-block", padding="2px 10px", margin="2px 4px 2px 0", borderRadius="4px", fontSize="10px", color=C["amber"], background=C["bg_neutral"], border=f"1px solid {C["amber"]}20", fontFamily=F["body"])}">{c}</span>'
                for c in risk_caveats
            )
            risk_html = f"""\
        <tr>
            <td colspan="6" style="{_s(padding='4px 16px 12px 16px')}">
                <span style="{_s(fontSize='10px', color=C['muted'], textTransform='uppercase', letterSpacing='0.06em', marginRight='8px', fontFamily=F['body'])}">Risks</span>
                {caveat_items}
            </td>
        </tr>"""

        return f"""\
<div style="{_s(background=C['surface'], border=f'1px solid {C["border"]}', borderRadius='10px', padding='0', marginBottom='24px', overflow='hidden')}">
    <div style="{_s(padding='14px 24px', borderBottom=f'1px solid {C["border"]}')}">
        <h2 style="{_s(fontFamily=F['display'], fontSize='15px', fontWeight='300', color=C['text'], margin='0', letterSpacing='0.03em')}">Market Context</h2>
    </div>
    {f'<table cellpadding="0" cellspacing="0" border="0" width="100%"><tr>{primary_html}</tr></table>' if has_primary else ""}
    {f'<div style="{_s(padding="0 24px 4px 24px")}"><table cellpadding="0" cellspacing="0" border="0" width="100%"><tr>{secondary_html}</tr>{signals_html}{risk_html}</table></div>' if (has_secondary or has_signals or has_risks) else ""}
</div>"""

    # ── Reasoning ───────────────────────────────────────────────────

    @staticmethod
    def _render_reasoning(decision: Dict[str, Any], fmt) -> str:
        reasoning = decision.get("reasoning_chain")
        critic_impact = decision.get("critic_impact")

        if not reasoning and not critic_impact:
            return ""

        sections = ""

        if reasoning:
            sections += f"""\
<div style="{_s(padding='16px 24px')}">
    <span style="{_s(fontSize='11px', color=C['muted'], textTransform='uppercase', letterSpacing='0.06em', display='block', marginBottom='10px', fontFamily=F['body'])}">Reasoning Chain</span>
    <pre style="{_s(fontSize='12px', lineHeight='1.7', color=C['text'], whiteSpace='pre-wrap', wordBreak='break-word', margin='0', fontFamily=F['body'], opacity='0.92')}">{reasoning}</pre>
</div>"""

        if critic_impact:
            sections += f"""\
<div style="{_s(padding='16px 24px', background=C['elevated'], borderTop=f'1px solid {C["border"]}')}">
    <span style="{_s(fontSize='11px', color=C['muted'], textTransform='uppercase', letterSpacing='0.06em', display='block', marginBottom='10px', fontFamily=F['body'])}">Critic Impact</span>
    <pre style="{_s(fontSize='12px', lineHeight='1.7', color=C['text'], whiteSpace='pre-wrap', wordBreak='break-word', margin='0', fontFamily=F['body'], opacity='0.85')}">{fmt(critic_impact)}</pre>
</div>"""

        return f"""\
<div style="{_s(background=C['surface'], border=f'1px solid {C["border"]}', borderRadius='10px', padding='0', marginBottom='24px', overflow='hidden', borderLeft=f'3px solid {C["gold"]}')}">
    <div style="{_s(padding='14px 24px', borderBottom=f'1px solid {C["border"]}')}">
        <h2 style="{_s(fontFamily=F['display'], fontSize='15px', fontWeight='300', color=C['text'], margin='0', letterSpacing='0.03em')}">Analysis</h2>
    </div>
    {sections}
</div>"""

    # ── Debate rounds ───────────────────────────────────────────────

    @staticmethod
    def _render_debate_rounds(history: list, fmt) -> str:
        if not history:
            return ""

        fp = SessionRenderer._fmt_price
        rounds_html = []

        for i, r in enumerate(history):
            plan = r.get("plan") or {}
            critic = r.get("critic") or {}
            math = r.get("math_fact_check") or {}
            veto = str(critic.get("veto_level") or "")
            math_status = str(math.get("status") or "")
            round_num = r.get("round", i + 1)

            # Plan section
            plan_opinion = plan.get("opinion", "?")
            plan_conf = plan.get("confidence_score")
            plan_tactics = plan.get("tactical_parameters") or {}
            plan_reasoning = plan.get("reasoning_chain") or ""

            # Build plan header
            opinion_badge = SessionRenderer._opinion_badge(plan_opinion) if plan_opinion else ""
            conf_str = f'{plan_conf:.1f}%' if plan_conf is not None else ""

            # Plan tactic mini-table
            tactic_rows = ""
            if plan_tactics:
                items = [
                    ("Entry", fp(plan_tactics.get("entry")), C["gold"]),
                    ("TP", fp(plan_tactics.get("take_profit")), C["verde"]),
                    ("SL", fp(plan_tactics.get("stop_loss")), C["crimson"]),
                ]
                rr_val = plan_tactics.get("rr_ratio")
                if rr_val and rr_val > 0:
                    items.append(("R:R", f"1:{rr_val:.1f}", C["muted"]))
                for label, val, clr in items:
                    tactic_rows += f"""\
                    <td style="{_s(padding='6px 10px', verticalAlign='top')}">
                        <span style="{_s(fontSize='9px', color=C['muted'], textTransform='uppercase', letterSpacing='0.05em', display='block', marginBottom='2px')}">{label}</span>
                        <span style="{_s(fontSize='12px', fontWeight='600', color=clr, fontFamily=F['mono'])}">{val}</span>
                    </td>"""

            # Plan body
            plan_section = ""
            if plan:
                plan_section = f"""\
        <div style="{_s(padding='16px 20px')}">
            <table cellpadding="0" cellspacing="0" border="0" width="100%" style="{_s(marginBottom=tactic_rows and '14px' or '0')}">
                <tr>{tactic_rows}</tr>
            </table>
            {f'<pre style="{_s(fontSize="12px", lineHeight="1.65", color=C["text"], whiteSpace="pre-wrap", wordBreak="break-word", margin="0", fontFamily=F["body"], opacity="0.88", maxHeight="280px", overflowY="auto")}">{plan_reasoning}</pre>' if plan_reasoning else ""}
        </div>"""

            # Critic section
            critic_summary = critic.get("critic_summary") or ""
            critic_evidence = critic.get("audit_evidence") or ""
            veto_badge = SessionRenderer._veto_badge(veto) if veto else ""
            math_badge = SessionRenderer._math_badge(math_status) if math_status else ""

            critic_section = ""
            if critic:
                critic_body = ""
                if critic_summary:
                    critic_body += f'<pre style="{_s(fontSize="12px", lineHeight="1.65", color=C["text"], whiteSpace="pre-wrap", wordBreak="break-word", margin="0 0 12px 0", fontFamily=F["body"], opacity="0.85")}">{critic_summary}</pre>'
                if critic_evidence:
                    critic_body += f"""\
<div style="{_s(padding='12px', background=C['elevated'], borderRadius='6px', border=f'1px solid {C["border"]}', marginBottom='8px')}">
    <span style="{_s(fontSize='10px', color=C['muted'], textTransform='uppercase', letterSpacing='0.05em', display='block', marginBottom='6px', fontFamily=F['body'])}">Audit Evidence</span>
    <pre style="{_s(fontSize='11px', lineHeight='1.5', color=C['muted'], whiteSpace='pre-wrap', wordBreak='break-word', margin='0', fontFamily=F['mono'])}">{fmt(critic_evidence)}</pre>
</div>"""

                critic_section = f"""\
        <div style="{_s(padding='0 20px 16px 20px')}">
            <div style="{_s(padding='12px', background=C['elevated'], borderRadius='6px', border=f'1px solid {C["border"]}')}">
                <span style="{_s(fontSize='11px', fontWeight='600', color=C['violet'], textTransform='uppercase', letterSpacing='0.05em', display='block', marginBottom='8px', fontFamily=F['body'])}">Critic Review {veto_badge} {math_badge}</span>
                {critic_body}
            </div>
        </div>"""

            # Math fact check detail (collapsed in critic section, show when present)
            math_verdict = math.get("compliance_verdict") or {}
            math_section = ""
            if math and math_verdict:
                math_section = f"""\
        <div style="{_s(padding='0 20px 16px 20px')}">
            <div style="{_s(padding='10px 12px', background=C['elevated'], borderRadius='6px', border=f'1px solid {C["border"]}')}">
                <span style="{_s(fontSize='10px', color=C['muted'], textTransform='uppercase', letterSpacing='0.05em', display='block', marginBottom='6px', fontFamily=F['body'])}">Math Fact Check</span>
                <pre style="{_s(fontSize='10px', lineHeight='1.5', color=C['muted'], whiteSpace='pre-wrap', wordBreak='break-word', margin='0', fontFamily=F['mono'])}">{json.dumps(math_verdict, indent=2)}</pre>
            </div>
        </div>"""

            # Veto verdict stripe
            veto_stripe_color = {
                "PASS":         C["verde"],
                "WEAK":         C["teal"],
                "CONSTRUCTIVE": C["amber"],
                "TERMINAL":     C["crimson"],
            }.get(veto, C["border"])

            rounds_html.append(f"""\
<div style="{_s(background=C['surface'], border=f'1px solid {C["border"]}', borderRadius='10px', marginBottom='14px', overflow='hidden', borderLeft=f'3px solid {veto_stripe_color}')}">
    <!-- Round header -->
    <div style="{_s(padding='12px 20px', background=C['elevated'], borderBottom=f'1px solid {C["border"]}')}">
        <table cellpadding="0" cellspacing="0" border="0" width="100%">
            <tr>
                <td>
                    <span style="{_s(fontFamily=F['display'], fontSize='14px', fontWeight='400', color=C['text'], letterSpacing='0.01em')}">Round {round_num}</span>
                    <span style="{_s(marginLeft='12px')}">{opinion_badge}</span>
                    {f'<span style="{_s(marginLeft="8px", fontSize="12px", fontWeight="600", color=C["gold"], fontFamily=F["mono"])}">{conf_str}</span>' if conf_str else ""}
                </td>
                <td style="{_s(textAlign='right')}">
                    {veto_badge}
                </td>
            </tr>
        </table>
    </div>
    {plan_section}
    {critic_section}
    {math_section}
</div>""")

        return f"""\
<div style="{_s(marginBottom='24px')}">
    <div style="{_s(padding='0 0 16px 0')}">
        <h2 style="{_s(fontFamily=F['display'], fontSize='18px', fontWeight='300', color=C['text'], margin='0', letterSpacing='0.03em')}">
            Debate Rounds
            <span style="{_s(fontFamily=F['mono'], fontSize='13px', fontWeight='400', color=C['muted'], marginLeft='8px')}">{len(history)}</span>
        </h2>
    </div>
    {"".join(rounds_html)}
</div>"""

    # ── Charts ──────────────────────────────────────────────────────

    @staticmethod
    def _render_charts(visual_context: Dict[str, Any]) -> str:
        if not visual_context:
            return ""

        has_macro = bool(visual_context.get("macro_snapshot"))
        has_micro = bool(visual_context.get("micro_snapshot"))

        if not has_macro and not has_micro:
            return ""

        # Single chart
        if has_macro and not has_micro:
            chart_html = f"""\
            <div style="{_s(padding='16px 20px')}">
                <span style="{_s(fontSize='11px', color=C['muted'], textTransform='uppercase', letterSpacing='0.06em', display='block', marginBottom='10px', fontFamily=F['body'])}">Macro (1h)</span>
                <img src="cid:macro_snapshot" alt="Macro Chart (1h)" style="{_s(width='100%', borderRadius='6px', border=f'1px solid {C["border"]}', display='block')}">
            </div>"""
        elif has_micro and not has_macro:
            chart_html = f"""\
            <div style="{_s(padding='16px 20px')}">
                <span style="{_s(fontSize='11px', color=C['muted'], textTransform='uppercase', letterSpacing='0.06em', display='block', marginBottom='10px', fontFamily=F['body'])}">Micro (15m)</span>
                <img src="cid:micro_snapshot" alt="Micro Chart (15m)" style="{_s(width='100%', borderRadius='6px', border=f'1px solid {C["border"]}', display='block')}">
            </div>"""
        else:
            # Side-by-side
            chart_html = f"""\
            <table cellpadding="0" cellspacing="0" border="0" width="100%">
                <tr>
                    <td style="{_s(padding='16px 10px 16px 20px', width='50%', verticalAlign='top')}">
                        <span style="{_s(fontSize='11px', color=C['muted'], textTransform='uppercase', letterSpacing='0.06em', display='block', marginBottom='10px', fontFamily=F['body'])}">Macro (1h)</span>
                        <img src="cid:macro_snapshot" alt="Macro Chart (1h)" style="{_s(width='100%', borderRadius='6px', border=f'1px solid {C["border"]}', display='block')}">
                    </td>
                    <td style="{_s(padding='16px 20px 16px 10px', width='50%', verticalAlign='top')}">
                        <span style="{_s(fontSize='11px', color=C['muted'], textTransform='uppercase', letterSpacing='0.06em', display='block', marginBottom='10px', fontFamily=F['body'])}">Micro (15m)</span>
                        <img src="cid:micro_snapshot" alt="Micro Chart (15m)" style="{_s(width='100%', borderRadius='6px', border=f'1px solid {C["border"]}', display='block')}">
                    </td>
                </tr>
            </table>"""

        return f"""\
<div style="{_s(background=C['surface'], border=f'1px solid {C["border"]}', borderRadius='10px', padding='0', marginBottom='24px', overflow='hidden')}">
    <div style="{_s(padding='14px 24px', borderBottom=f'1px solid {C["border"]}')}">
        <h2 style="{_s(fontFamily=F['display'], fontSize='15px', fontWeight='300', color=C['text'], margin='0', letterSpacing='0.03em')}">Charts</h2>
    </div>
    {chart_html}
</div>"""

    # ── Metadata ────────────────────────────────────────────────────

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
                val = vc[key]
                if len(str(val)) > 14:
                    val = str(val)[:14] + "&hellip;"
                rows += f"""<tr>
    <td style="{_s(padding="5px 12px", fontSize="10px", color=C['muted'], textTransform="uppercase", letterSpacing="0.05em", whiteSpace="nowrap", fontFamily=F['body'])}">{label}</td>
    <td style="{_s(padding="5px 12px", fontSize="11px", color=C['violet'], fontFamily=F['mono'], textAlign="right")}">{val}</td>
</tr>"""
        if not rows:
            return ""

        return f"""\
<div style="{_s(background=C['surface'], border=f'1px solid {C["border"]}', borderRadius='10px', padding='0', marginBottom='24px', overflow='hidden')}">
    <div style="{_s(padding='14px 24px', borderBottom=f'1px solid {C["border"]}')}">
        <h2 style="{_s(fontFamily=F['display'], fontSize='15px', fontWeight='300', color=C['text'], margin='0', letterSpacing='0.03em')}">Metadata</h2>
    </div>
    <table cellpadding="0" cellspacing="0" border="0" width="100%" style="{_s(margin='8px 0')}">
        {rows}
    </table>
</div>"""

    # ── Footer ──────────────────────────────────────────────────────

    @staticmethod
    def _render_footer() -> str:
        return f"""\
<div style="{_s(textAlign='center', padding='24px 0', borderTop=f'1px solid {C["border"]}', marginTop='8px')}">
    <p style="{_s(fontFamily=F['display'], fontSize='12px', fontWeight='300', color=C['muted'], margin='0', letterSpacing='0.02em')}">
        Singularity <span style="{_s(color=C['gold'])}">&middot;</span> Automated Notification
    </p>
</div>"""

    # ── Styles (empty — all styling is inline for email compatibility) ──

    @staticmethod
    def get_styles() -> str:
        return ""
