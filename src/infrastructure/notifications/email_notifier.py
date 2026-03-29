import os
import json
import logging
from datetime import datetime
from typing import Dict, List, Any, Optional
import yaml
from src.utils.path_utils import find_project_root

from .base_notifier import (
    NotificationConfig, 
    BaseEmailTemplate, 
    EmailDispatcher
)

from src.utils.logger_utils import setup_logger
logger = setup_logger(__name__)



class StrategyEmailTemplate(BaseEmailTemplate):
    """
    Handles the generation of professional HTML templates for trading strategies.
    Decouples the UI presentation from the data fetching/sending logic.
    """
    @staticmethod
    def render(strategy_data: Dict[str, Any]) -> str:
        """
        Renders the final strategy JSON into a rich HTML report.
        """
        obs = strategy_data.get("observation") or {}
        decision = strategy_data.get("final_decision") or {}
        symbol = obs.get("symbol", "UNKNOWN")
        
        # 1. Local Time Conversion (Device Local)
        utc_ts = obs.get("timestamp", "")
        try:
            local_dt = datetime.fromisoformat(utc_ts.replace("Z", "+00:00")).astimezone()
            display_time = local_dt.strftime("%Y-%m-%d %H:%M:%S %Z")
        except Exception:
            display_time = utc_ts

        # 2. Extract Data Suites
        semantics = obs.get("semantic_analysis") or {}
        critique = strategy_data.get("critique") or {}
        
        opinion = decision.get("opinion", "NEUTRAL") or "NEUTRAL"
        opinion = str(opinion).upper()
        confidence = decision.get("confidence", 0)
        reasoning = decision.get("reasoning", "No description provided.")
        
        # 3. UI Styling & Formatting
        colors = {"BULLISH": "#10b981", "BEARISH": "#ef4444", "NEUTRAL": "#64748b"}
        icons = {"BULLISH": "🟢", "BEARISH": "🔴", "NEUTRAL": "⏸️"}
        theme_color = colors.get(opinion, "#64748b")
        theme_icon = icons.get(opinion, "⚡")
        display_opinion = "STAND ASIDE" if opinion == "NEUTRAL" else opinion
        
        fmt = StrategyEmailTemplate.fmt
        
        return f"""
        <html>
        <head>{StrategyEmailTemplate.get_styles()}</head>
        <body>
            <div class="container">
                <div style="text-align: center; margin-bottom: 35px; border-bottom: 2px solid #f1f5f9; padding-bottom: 25px;">
                    <div style="display: inline-block; padding: 6px 14px; border-radius: 50px; background-color: {theme_color}15; color: {theme_color}; font-weight: 700; font-size: 13px; margin-bottom: 12px; border: 1px solid {theme_color}30;">
                        {theme_icon} {display_opinion}
                    </div>
                    <h1 style="color: #0f172a; margin: 0; font-size: 32px; letter-spacing: -0.025em;">{symbol} Market Blueprint</h1>
                    <p style="color: #64748b; margin-top: 8px; font-size: 14px; font-weight: 500;">
                        Confidence: <span style="color: {theme_color}; font-weight: 700;">{confidence}%</span> | 🕒 {display_time}
                    </p>
                </div>

                <!-- Risk Assessment -->
                {f'''
                <div style="background-color: #fff7ed; padding: 25px; border-radius: 12px; border: 1px solid #ffedd5; margin-bottom: 35px; border-left: 5px solid #f97316;">
                    <table width="100%" cellpadding="0" cellspacing="0" border="0" style="margin: 0 0 10px 0;">
                        <tr>
                            <td align="left" style="color: #9a3412; font-size: 16px; font-weight: bold;">
                                <span>🛡️ Risk Assessment</span>
                            </td>
                            <td align="right" style="vertical-align: middle;">
                                <span style="background: #ffedd5; padding: 2px 8px; border-radius: 4px; font-size: 11px; color: #9a3412; font-weight: bold;">Risk Level: {fmt((critique or {}).get('skepticism_score'))}%</span>
                            </td>
                        </tr>
                    </table>
                    <p style="font-size: 14px; line-height: 1.6; color: #7c2d12; margin: 0;">{fmt((critique or {}).get('hidden_risk'))}</p>
                </div>
                ''' if critique else ""}

                <!-- Critic's Verdict -->
                {f'''
                <div style="margin-bottom: 35px; padding: 20px; border: 1px dashed #cbd5e1; border-radius: 12px; background_color: #f8fafc;">
                    <h3 style="margin-top: 0; color: #475569; font-size: 15px; margin-bottom: 12px;">🧐 Critic's Verdict</h3>
                    <p style="font-size: 13px; line-height: 1.6; color: #334155; margin: 0; font-style: italic;">{fmt(decision.get('critic_impact'))}</p>
                </div>
                ''' if decision.get('critic_impact') else ""}

                <!-- Reasoning -->
                <div style="background-color: #f8fafc; padding: 25px; border-radius: 12px; border: 1px solid #e2e8f0; margin-bottom: 35px;">
                    <h3 style="margin-top: 0; color: #334155; font-size: 18px; margin-bottom: 15px;">🧠 Logic & Reasoning</h3>
                    <p style="font-size: 15px; line-height: 1.7; color: #1e293b; margin-bottom: 20px;">{reasoning}</p>
                    
                    {f'''
                    <table class="responsive-metrics" style="width: 100%; background: #1e293b; border-radius: 8px; border-collapse: separate; border-spacing: 15px 20px; text-align: center; color: #ffffff;">
                        <tr>
                            <td style="width: 25%; vertical-align: top; border: none !important;">
                                <div style="font-size: 11px; color: #94a3b8; text-transform: uppercase; font-weight: 700; margin-bottom: 5px;">📥 Entry</div>
                                <div style="font-size: 18px; color: #60a5fa; font-weight: 800; font-family: 'SF Mono', 'Courier New', monospace;">{fmt((decision.get('limit_order') or {}).get('entry'))}</div>
                            </td>
                            <td style="width: 25%; vertical-align: top; border: none !important;">
                                <div style="font-size: 11px; color: #94a3b8; text-transform: uppercase; font-weight: 700; margin-bottom: 5px;">💰 Take Profit</div>
                                <div style="font-size: 18px; color: #34d399; font-weight: 800; font-family: 'SF Mono', 'Courier New', monospace;">{fmt((decision.get('limit_order') or {}).get('take_profit'))}</div>
                            </td>
                            <td style="width: 25%; vertical-align: top; border: none !important;">
                                <div style="font-size: 11px; color: #94a3b8; text-transform: uppercase; font-weight: 700; margin-bottom: 5px;">🛡️ Stop Loss</div>
                                <div style="font-size: 18px; color: #fb7185; font-weight: 800; font-family: 'SF Mono', 'Courier New', monospace;">{fmt((decision.get('limit_order') or {}).get('stop_loss'))}</div>
                            </td>
                            <td style="width: 25%; vertical-align: top; border: none !important;">
                                <div style="font-size: 11px; color: #94a3b8; text-transform: uppercase; font-weight: 700; margin-bottom: 5px;">⏱️ Temporal Window</div>
                                <div style="font-size: 18px; color: #cbd5e1; font-weight: 800; font-family: 'SF Mono', 'Courier New', monospace;">{StrategyEmailTemplate.format_duration((decision.get('limit_order') or {}).get('holding_time_hours', 0))}</div>
                            </td>
                        </tr>
                    </table>
                    ''' if decision else ""}
                </div>

                <!-- Intelligence Briefing -->
                <div style="margin-bottom: 35px; border-top: 1px solid #e2e8f0; padding-top: 25px;">
                    <h3 style="margin-top: 0; color: #334155; font-size: 18px; margin-bottom: 20px;">🔬 Forensic Breakdown</h3>
                    <div style="display: grid; grid-template-columns: 1fr; gap: 15px;">
                        <div style="border-left: 4px solid #3b82f6; background-color: #eff6ff; padding: 15px; border-radius: 0 8px 8px 0; margin-bottom: 15px;">
                            <span style="font-size: 11px; font-weight: 800; color: #1e40af; text-transform: uppercase; letter-spacing: 0.05em;">Synthesized Topography</span>
                            <p style="font-size: 13px; color: #1e3a8a; margin-top: 8px; line-height: 1.6; font-weight: 500;">{fmt(semantics.get('synthesized_topography'))}</p>
                        </div>

                        <div style="border-left: 3px solid #cbd5e1; padding-left: 15px; margin-bottom: 12px;">
                            <span style="font-size: 11px; font-weight: 700; color: #64748b; text-transform: uppercase;">Structural Gravity</span>
                            <p style="font-size: 13px; color: #475569; margin-top: 5px; line-height: 1.5;">{fmt(semantics.get('structural_gravity'))}</p>
                        </div>

                        <div style="border-left: 3px solid #cbd5e1; padding-left: 15px; margin-bottom: 12px;">
                            <span style="font-size: 11px; font-weight: 700; color: #64748b; text-transform: uppercase;">Topographical Friction</span>
                            <p style="font-size: 13px; color: #475569; margin-top: 5px; line-height: 1.5;">{fmt(semantics.get('topographical_friction'))}</p>
                        </div>

                        <div style="border-left: 3px solid #cbd5e1; padding-left: 15px; margin-bottom: 12px;">
                            <span style="font-size: 11px; font-weight: 700; color: #64748b; text-transform: uppercase;">Sentiment Flow</span>
                            <p style="font-size: 13px; color: #475569; margin-top: 5px; line-height: 1.5;">{fmt(semantics.get('sentiment_flow'))}</p>
                        </div>

                        <div style="border-left: 3px solid #cbd5e1; padding-left: 15px; margin-bottom: 12px;">
                            <span style="font-size: 11px; font-weight: 700; color: #64748b; text-transform: uppercase;">Regime & Volatility</span>
                            <p style="font-size: 13px; color: #475569; margin-top: 5px; line-height: 1.5;">{fmt(semantics.get('regime_volatility'))}</p>
                        </div>

                        <div style="border-left: 3px solid #cbd5e1; padding-left: 15px; margin-bottom: 10px;">
                            <span style="font-size: 11px; font-weight: 700; color: #64748b; text-transform: uppercase;">Micro-Interactive detail</span>
                            <p style="font-size: 13px; color: #475569; margin-top: 5px; line-height: 1.5;">{fmt((semantics or {}).get('micro_interactive'))}</p>
                        </div>
                    </div>
                </div>

                <!-- Visual Assets -->
                <div id="charts-root" style="text-align: center;">
                    <h4 style="color: #64748b; margin-bottom: 15px; font-size: 11px; text-transform: uppercase;">🖼️ Visual Snapshots</h4>
                    <table width="100%" cellpadding="0" cellspacing="0" border="0" style="margin-bottom: 25px; border-collapse: separate; border-spacing: 15px 0;">
                        <tr>
                            <td style="width: 50%; vertical-align: top;">
                                <span style="font-size: 10px; color: #94a3b8; font-weight: 700; text-transform: uppercase; display: block; margin-bottom: 8px;">Macro</span>
                                <img src="cid:macro_chart" style="width: 100%; border-radius: 8px; border: 1px solid #e2e8f0; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.05);">
                            </td>
                            <td style="width: 50%; vertical-align: top;">
                                <span style="font-size: 10px; color: #94a3b8; font-weight: 700; text-transform: uppercase; display: block; margin-bottom: 8px;">Micro</span>
                                <img src="cid:micro_chart" style="width: 100%; border-radius: 8px; border: 1px solid #e2e8f0; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.05);">
                            </td>
                        </tr>
                    </table>
                </div>

                {StrategyEmailTemplate.render_footer(strategy_data, "This is an auto-generated email notification | Triggered by Crypto Strategy")}
            </div>
        </body>
        </html>
        """

class ReviewEmailTemplate(BaseEmailTemplate):
    """
    Handles the generation of professional HTML templates for Forensic Reviews.
    """
    @staticmethod
    def render(review_data: Dict[str, Any]) -> str:
        """
        Renders the final review JSON into a rich HTML report.
        """
        strat_session = review_data.get("strategy_session") or {}
        obs = strat_session.get("observation") or {}
        decision = strat_session.get("final_decision") or {}
        outcome = review_data.get("market_outcome") or {}
        audit = review_data.get("audit_findings") or {}
        
        symbol = obs.get("symbol", "UNKNOWN")
        strat_ts = obs.get("timestamp", "")
        audit_ts = review_data.get("audit_timestamp", "")
        
        # Local Time Conversion
        try:
            strat_dt = datetime.fromisoformat(strat_ts.replace("Z", "+00:00")).astimezone()
            display_strat_time = strat_dt.strftime("%Y-%m-%d %H:%M:%S")
            audit_dt = datetime.fromisoformat(audit_ts.replace("Z", "+00:00")).astimezone()
            display_audit_time = audit_dt.strftime("%Y-%m-%d %H:%M:%S %Z")
        except Exception:
            display_strat_time = strat_ts
            display_audit_time = audit_ts

        opinion = decision.get("opinion", "NEUTRAL") or "NEUTRAL"
        opinion = str(opinion).upper()
        confidence = decision.get("confidence", 0)
        
        # Outcome styling
        metrics = outcome.get("trade_execution_metrics") or {}
        result_type = metrics.get("tp_sl_result", "NEITHER")
        
        result_colors = {"TP_HIT": "#10b981", "SL_HIT": "#ef4444", "NEITHER": "#64748b"}
        result_labels = {"TP_HIT": "PROFIT (TP)", "SL_HIT": "LOSS (SL)", "NEITHER": "FLAT (NEITHER)"}
        res_color = result_colors.get(result_type, "#64748b")
        res_label = result_labels.get(result_type, "PENDING / N/A")
        
        fmt = ReviewEmailTemplate.fmt
        
        # 4. Forensic Formatting
        shadow_list = audit.get('adversarial_audit', {}).get('shadow_evidence', [])
        if isinstance(shadow_list, list) and shadow_list:
            shadow_html = f'<ul style="margin: 0; padding-left: 18px;">' + "".join([f"<li>{fmt(item)}</li>" for item in shadow_list]) + "</ul>"
        else:
            shadow_html = fmt(shadow_list or "None")

        return f"""
        <html>
        <head>{ReviewEmailTemplate.get_styles()}</head>
        <body>
            <div class="container">
                <!-- Header -->
                <div style="text-align: center; margin-bottom: 35px; border-bottom: 2px solid #f1f5f9; padding-bottom: 25px;">
                    <div style="display: inline-block; padding: 6px 14px; border-radius: 50px; background-color: {res_color}15; color: {res_color}; font-weight: 700; font-size: 13px; margin-bottom: 12px; border: 1px solid {res_color}30;">
                        🏁 {res_label}
                    </div>
                    <h1 style="color: #0f172a; margin: 0; font-size: 32px; letter-spacing: -0.025em;">{symbol} Market Performance</h1>
                    <p style="color: #64748b; margin-top: 8px; font-size: 14px; font-weight: 500;">
                        Original Signal: {opinion} ({confidence}%) at {display_strat_time} | Audit: {display_audit_time}
                    </p>
                </div>

                <!-- Outcome Summary -->
                <div style="background-color: #f8fafc; padding: 25px; border-radius: 12px; border: 1px solid #e2e8f0; margin-bottom: 35px;">
                    <h3 style="margin-top: 0; color: #334155; font-size: 18px; margin-bottom: 20px;">🏁 Outcome Summary</h3>
                    <table class="responsive-metrics" width="100%" cellpadding="0" cellspacing="0" border="0" style="margin-bottom: 25px; border-collapse: separate; border-spacing: 10px 0;">
                        <tr>
                            <td style="width: 33.33%; background: #ffffff; border: 1px solid #e2e8f0; border-radius: 8px; padding: 15px; text-align: center; border-bottom: 1px solid #e2e8f0 !important;">
                                <span style="font-size: 10px; color: #64748b; text-transform: uppercase; font-weight: 700; display: block; margin-bottom: 6px;">📐 Price Change</span>
                                <div style="font-size: 18px; font-weight: 800; color: {'#10b981' if outcome.get('total_price_change_pct', 0) >= 0 else '#ef4444'};">
                                    {fmt(outcome.get('total_price_change_pct'))}%
                                </div>
                            </td>
                            <td style="width: 33.33%; background: #ffffff; border: 1px solid #e2e8f0; border-radius: 8px; padding: 15px; text-align: center; border-bottom: 1px solid #e2e8f0 !important;">
                                <span style="font-size: 10px; color: #64748b; text-transform: uppercase; font-weight: 700; display: block; margin-bottom: 6px;">🔥 Max Favorable (MFE)</span>
                                <div style="font-size: 18px; font-weight: 800; color: #10b981;">{fmt(outcome.get('max_favorable_runup_pct'))}%</div>
                            </td>
                            <td style="width: 33.33%; background: #ffffff; border: 1px solid #e2e8f0; border-radius: 8px; padding: 15px; text-align: center; border-bottom: 1px solid #e2e8f0 !important;">
                                <span style="font-size: 10px; color: #64748b; text-transform: uppercase; font-weight: 700; display: block; margin-bottom: 6px;">💧 Max Adverse (MAE)</span>
                                <div style="font-size: 18px; font-weight: 800; color: #ef4444;">{fmt(outcome.get('max_adverse_drawdown_pct'))}%</div>
                            </td>
                        </tr>
                    </table>

                    <table class="responsive-metrics" style="width: 100%; background: #1e293b; border-radius: 8px; border-collapse: separate; border-spacing: 15px 20px; text-align: center; color: #ffffff;">
                        <tr>
                            <td style="width: 33.33%; vertical-align: top; border: none !important;">
                                <div style="font-size: 11px; color: #94a3b8; text-transform: uppercase; font-weight: 700; margin-bottom: 5px;">⚡ Efficiency</div>
                                <div style="font-size: 16px; color: #34d399; font-weight: 800;">{fmt(metrics.get('mfe_efficiency'))}</div>
                            </td>
                            <td style="width: 33.33%; vertical-align: top; border: none !important;">
                                <div style="font-size: 11px; color: #94a3b8; text-transform: uppercase; font-weight: 700; margin-bottom: 5px;">🌡️ MAE Stress</div>
                                <div style="font-size: 16px; color: #fb7185; font-weight: 800;">{fmt(metrics.get('mae_stress_level'))}</div>
                            </td>
                            <td style="width: 33.33%; vertical-align: top; border: none !important;">
                                <div style="font-size: 11px; color: #94a3b8; text-transform: uppercase; font-weight: 700; margin-bottom: 5px;">⏱️ Duration</div>
                                <div style="font-size: 16px; color: #60a5fa; font-weight: 800;">{ReviewEmailTemplate.format_duration(metrics.get('actual_hours', 0))}</div>
                            </td>
                        </tr>
                    </table>
                </div>

                <!-- Forensic Audit Findings -->
                <div style="background-color: #eff6ff; padding: 25px; border-radius: 12px; border: 1px solid #dbeafe; margin-bottom: 35px; border-left: 5px solid #3b82f6;">
                    <table width="100%" cellpadding="0" cellspacing="0" border="0" style="margin: 0 0 15px 0; border-bottom: 1px solid #dbeafe; padding-bottom: 10px;">
                        <tr>
                            <td align="left" style="color: #1e40af; font-size: 18px; font-weight: bold;">
                                📑 Audit Findings & Score
                            </td>
                            <td align="right" style="vertical-align: middle;">
                                <span style="background: #1e40af; padding: 4px 12px; border-radius: 6px; font-size: 14px; color: #ffffff; font-weight: 800;">Score: {audit.get('evaluation_score', 0)}/100</span>
                            </td>
                        </tr>
                    </table>
                    
                    <div style="margin-bottom: 20px;">
                        <span style="font-size: 11px; font-weight: 800; color: #1e40af; text-transform: uppercase; letter-spacing: 0.05em; display: block; margin-bottom: 8px;">Critical Audit</span>
                        <div style="font-size: 14px; line-height: 1.6; color: #1e3a8a; margin: 0; background: #ffffff66; padding: 12px; border-radius: 6px;">
                            {shadow_html}
                        </div>
                    </div>

                    <div>
                        <span style="font-size: 11px; font-weight: 800; color: #1e40af; text-transform: uppercase; letter-spacing: 0.05em; display: block; margin-bottom: 8px;">Execution Analysis</span>
                        <p style="font-size: 14px; line-height: 1.6; color: #1e3a8a; margin: 0;">{fmt(audit.get('post_mortem'))}</p>
                    </div>
                </div>

                <!-- Original Strategy Summary (Context) -->
                <div style="margin-bottom: 35px; padding: 20px; border: 1px dashed #cbd5e1; border-radius: 12px; background-color: #f8fafc;">
                    <h3 style="margin-top: 0; color: #475569; font-size: 15px; margin-bottom: 12px;">🧐 Context</h3>
                    <p style="font-size: 13px; line-height: 1.6; color: #334155; margin: 0; font-style: italic;">{fmt(decision.get('reasoning'))}</p>
                </div>

                <!-- Visual Assets (Comparative Proof) -->
                <div id="charts-root" style="text-align: center;">
                    <h4 style="color: #64748b; margin-bottom: 15px; font-size: 11px; text-transform: uppercase;">🖼️ Visual Snapshots</h4>
                    
                    <!-- Macro Row -->
                    <table width="100%" cellpadding="0" cellspacing="0" border="0" style="margin-bottom: 15px; border-collapse: separate; border-spacing: 15px 0;">
                        <tr>
                            <td style="width: 50%; vertical-align: top;">
                                <span style="font-size: 10px; color: #94a3b8; font-weight: 700; text-transform: uppercase; display: block; margin-bottom: 8px;">Macro T0 (Entry)</span>
                                <img src="cid:t0_macro" style="width: 100%; border-radius: 8px; border: 1px solid #e2e8f0; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.05);">
                            </td>
                            <td style="width: 50%; vertical-align: top;">
                                <span style="font-size: 10px; color: #94a3b8; font-weight: 700; text-transform: uppercase; display: block; margin-bottom: 8px;">Macro T1 (Audit)</span>
                                <img src="cid:t1_macro" style="width: 100%; border-radius: 8px; border: 1px solid #e2e8f0; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.05);">
                            </td>
                        </tr>
                    </table>

                    <!-- Micro Row -->
                    <table width="100%" cellpadding="0" cellspacing="0" border="0" style="margin-bottom: 25px; border-collapse: separate; border-spacing: 15px 0;">
                        <tr>
                            <td style="width: 50%; vertical-align: top;">
                                <span style="font-size: 10px; color: #94a3b8; font-weight: 700; text-transform: uppercase; display: block; margin-bottom: 8px;">Micro T0 (Entry)</span>
                                <img src="cid:t0_micro" style="width: 100%; border-radius: 8px; border: 1px solid #e2e8f0; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.05);">
                            </td>
                            <td style="width: 50%; vertical-align: top;">
                                <span style="font-size: 10px; color: #94a3b8; font-weight: 700; text-transform: uppercase; display: block; margin-bottom: 8px;">Micro T1 (Audit)</span>
                                <img src="cid:t1_micro" style="width: 100%; border-radius: 8px; border: 1px solid #e2e8f0; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.05);">
                            </td>
                        </tr>
                    </table>
                </div>

                {ReviewEmailTemplate.render_footer(review_data, "This is an auto-generated email notification | Triggered by Crypto Strategy")}
            </div>
        </body>
        </html>
        """

class DashboardEmailTemplate(BaseEmailTemplate):
    """
    Handles the generation of professional HTML templates for Strategic Alpha Ledgers (Dashboards).
    """
    @staticmethod
    def render(symbol: str, stats: Dict[str, Any], dataset: List[Dict[str, Any]]) -> str:
        """
        Renders an aggregate performance summary into a rich HTML report.
        """
        # Build Rows
        rows_html = ""
        # iterate safely
        limit = 100
        recent_items = dataset[max(0, len(dataset)-limit):] if len(dataset) > limit else dataset
        for item in recent_items:
            res_color = "#10b981" if item['tp_sl_result'] == 'TP_HIT' else "#ef4444" if item['tp_sl_result'] == 'SL_HIT' else "#64748b"
            pnl_val = float(item.get('estimated_pnl_pct', 0.0))
            p_sign = "+" if pnl_val > 0 else ""
            
            rows_html += f"""
                <tr>
                    <td style="font-family: monospace; font-size: 11px;">{item['observation_time']}</td>
                    <td><span style="font-weight: 700; color: {res_color};">{item['tp_sl_result']}</span></td>
                    <td style="text-align: right; font-weight: 700;"><span class="{'metric_pnl_pos' if pnl_val > 0 else 'metric_pnl_neg' if pnl_val < 0 else ''}">{p_sign}{pnl_val}%</span></td>
                </tr>
            """

        wr = stats.get('win_rate', 0.0)
        pnl = stats.get('net_pnl', 0.0)
        pnl_sign = "+" if pnl >= 0 else ""

        return f"""
        <html>
        <head>{DashboardEmailTemplate.get_styles()}</head>
        <body>
            <div class="container">
                <!-- Header -->
                <div style="text-align: center; margin-bottom: 35px; border-bottom: 2px solid #f1f5f9; padding-bottom: 25px;">
                    <div style="display: inline-block; padding: 6px 14px; border-radius: 50px; background-color: #3b82f615; color: #3b82f6; font-weight: 700; font-size: 13px; margin-bottom: 12px; border: 1px solid #3b82f630;">
                        💎 AGGREGATE PERFORMANCE
                    </div>
                    <h1 style="color: #0f172a; margin: 0; font-size: 32px; letter-spacing: -0.025em;">{symbol} Ledger</h1>
                </div>

                <!-- KPI Panel (Dark Style) -->
                <div style="background-color: #f8fafc; padding: 25px; border-radius: 12px; border: 1px solid #e2e8f0; margin-bottom: 35px;">
                    <table class="responsive-metrics" style="width: 100%; background: #1e293b; border-radius: 8px; border-collapse: separate; border-spacing: 15px 20px; text-align: center; color: #ffffff;">
                        <tr>
                            <td style="width: 33.33%; vertical-align: top; border: none !important;">
                                <div style="font-size: 11px; color: #94a3b8; text-transform: uppercase; font-weight: 700; margin-bottom: 5px;">🧬 Validated Samples</div>
                                <div style="font-size: 18px; color: #cbd5e1; font-weight: 800;">{stats.get('executed_count', 0)}</div>
                            </td>
                            <td style="width: 33.33%; vertical-align: top; border: none !important;">
                                <div style="font-size: 11px; color: #94a3b8; text-transform: uppercase; font-weight: 700; margin-bottom: 5px;">🎯 Win Rate</div>
                                <div style="font-size: 18px; color: #34d399; font-weight: 800;">{wr}%</div>
                            </td>
                            <td style="width: 33.33%; vertical-align: top; border: none !important;">
                                <div style="font-size: 11px; color: #94a3b8; text-transform: uppercase; font-weight: 700; margin-bottom: 5px;">💰 Cumulative Net PnL</div>
                                <div style="font-size: 18px; color: {'#34d399' if pnl >= 0 else '#fb7185'}; font-weight: 800;">{pnl_sign}{pnl}%</div>
                            </td>
                        </tr>
                    </table>
                </div>

                <!-- Evidence List -->
                <div class="panel">
                    <h3 class="panel-title">🔍 Validated Samples</h3>
                    <table>
                        <thead>
                            <tr>
                                <th>Timestamp</th>
                                <th>Result</th>
                                <th style="text-align: right;">PnL %</th>
                            </tr>
                        </thead>
                        <tbody>
                            {rows_html}
                        </tbody>
                    </table>
                    <p style="font-size: 11px; color: #94a3b8; text-align: center;">
                        Only showing the most recent {limit} records. View the full dashboard for complete trajectory.
                    </p>
                </div>

                {DashboardEmailTemplate.render_summary_footer("This is an auto-generated email notification | Triggered by Crypto Strategy")}
            </div>
        </body>
        </html>
        """


class StrategyNotifier:
    """
    High-level facade for dispatching trading strategy alerts.
    Orchestrates template rendering and email dispatching.
    """
    
    def __init__(self, data_root: str):
        self.config = NotificationConfig.from_env()
        self.dispatcher = EmailDispatcher(self.config)
        self.data_root = data_root
        self.global_cfg = self._load_global_config()
        
        # Sourcing threshold from global_config.yaml (Strict enforcement)
        system_cfg = self.global_cfg['system']
        self.min_confidence_threshold = int(system_cfg['min_confidence_for_notifier_threshold'])


    def _load_global_config(self) -> Dict[str, Any]:
        """Loads global system settings."""
        try:
            cfg_path = os.path.join(find_project_root(), "config", "global_config.yaml")
            if os.path.exists(cfg_path):
                with open(cfg_path, 'r') as f:
                    return yaml.safe_load(f)
        except Exception as e:
            logger.error(f"Failed to load global_config.yaml: {e}")
        return {}

    @property
    def enabled(self) -> bool:
        return self.config.enabled

    def notify_strategy(self, symbol: str, strategy_data: Dict[str, Any], save_local: bool = True) -> bool:
        """
        Parses strategy result and dispatches an actionable email alert.
        """
        # Always generate HTML for potential preview even if email is disabled
        html_body = StrategyEmailTemplate.render(strategy_data or {})
        
        # Collect Visual Attachments
        obs = (strategy_data or {}).get("observation") or {}
        assets = obs.get("visual_assets") or {}
        attachments = {
            "macro_chart": str(assets.get("macro_snapshot") or ""),
            "micro_chart": str(assets.get("micro_snapshot") or "")
        }

        # 1. Local Preview (Useful for debugging/UI verification)
        if save_local:
            self.save_html_preview(f"{symbol}_strategy", html_body, attachments)

        if not self.enabled:
            return False
            
        final_decision = (strategy_data or {}).get("final_decision") or {}
        opinion = final_decision.get("opinion") or "NEUTRAL"
        confidence = final_decision.get("confidence", 0)
        
        # Only notify if confidence >= threshold
        if confidence < self.min_confidence_threshold:
            logger.info(f"Notifier: Confidence too low ({confidence}% < {self.min_confidence_threshold}%). Skipping dispatch.")
            return False

        # Only notify if opinion is BULLISH / BEARISH
        # if opinion.upper() not in ["BULLISH", "BEARISH"]:
        #     logger.info(f"Notifier: Opinion is {opinion}. Skipping dispatch (only BULLISH/BEARISH allowed).")
        #     return False
            
        icons = {"BULLISH": "🟢", "BEARISH": "🔴", "NEUTRAL": "⏸️"}
        indicator = icons.get(opinion.upper(), '⚡')
        subject = f"{indicator} Signal | {symbol} | {opinion.upper()} ({confidence}%)"
        
        # 2. Dispatch Email
        logger.info(f"Notifier: Dispatching alert: {subject}")
        return self.dispatcher.dispatch(subject, html_body, attachments)

    def notify_review(self, symbol: str, review_data: Dict[str, Any], save_local: bool = True) -> bool:
        """
        Parses review result and dispatches a forensic audit report.
        """
        html_body = ReviewEmailTemplate.render(review_data or {})
        
        # Collect Comparative Assets
        strat_session = (review_data or {}).get("strategy_session") or {}
        t0_obs = strat_session.get("observation") or {}
        t0_assets = t0_obs.get("visual_assets") or {}
        visual_ctx = review_data.get("visual_context") or {}
        
        # Attach all 4 snapshots (Macro/Micro T0 vs T1)
        attachments = {
            "t0_macro": str(t0_assets.get("macro_snapshot") or ""),
            "t0_micro": str(t0_assets.get("micro_snapshot") or ""),
            "t1_macro": str(visual_ctx.get("t1_macro") or ""),
            "t1_micro": str(visual_ctx.get("t1_micro") or "")
        }

        if save_local:
            self.save_html_preview(f"{symbol}_review", html_body, attachments)

        if not self.enabled:
            return False
            
        # We only notify reviews for strategies that met our confidence threshold
        final_decision = strat_session.get("final_decision") or {}
        confidence = final_decision.get("confidence", 0)
        
        if confidence < self.min_confidence_threshold:
            logger.info(f"Notifier: Original strategy confidence too low ({confidence}%). Skipping review dispatch.")
            return False
            
        intercept = (review_data.get("market_outcome") or {}).get("intercept_status") or {}
        
        # [Cost Firewall] Skip notifications for intercepted reports to reduce noise.
        if intercept.get("is_intercepted", False):
            logger.info(f"Notifier: Audit for {symbol} is intercepted ({intercept.get('reason')}). Skipping review dispatch.")
            return False
            
        metrics = (review_data.get("market_outcome") or {}).get("trade_execution_metrics") or {}
        result = metrics.get("tp_sl_result", "N/A")

        if result not in ["TP_HIT", "SL_HIT", "NEITHER"]:
            logger.info(f"Notifier: Result is {result}. Skipping review dispatch (only TP_HIT/SL_HIT/NEITHER allowed).")
            return False
            
        subject = f"📋 Audit | {symbol} | {result}"
        
        logger.info(f"Notifier: Dispatching forensic report: {subject}")
        return self.dispatcher.dispatch(subject, html_body, attachments)

    def save_html_preview(self, name_prefix: str, html_body: str, attachments: Optional[Dict[str, str]] = None) -> Optional[str]:
        """
        Saves the rendered HTML to a local file for visual inspection.
        Swaps CID references for local filesystem paths.
        """
        try:
            # Determine output directory based on data_root to keep it isolated (e.g. data/test/html)
            output_dir = os.path.join(find_project_root(), self.data_root, "html")
            os.makedirs(output_dir, exist_ok=True)
            
            # For local preview, swap 'cid:name' with the actual file path.
            preview_html = html_body
            if attachments:
                for cid, file_path in attachments.items():
                    if file_path:
                        # Resolve to absolute path for reliable local browser opening
                        if not os.path.isabs(file_path):
                            abs_path = os.path.abspath(os.path.join(find_project_root(), file_path))
                        else:
                            abs_path = file_path
                        preview_html = str(preview_html).replace(f"cid:{cid}", f"file://{abs_path}")
            
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            file_name = f"{name_prefix}_preview_{timestamp}.html"
            file_path = os.path.join(output_dir, file_name)
            
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(preview_html)
            
            logger.info(f"Notifier: HTML preview saved to {file_path}")
            return file_path
        except Exception as e:
            logger.error(f"Notifier: Failed to save HTML preview: {e}")
            return None

    def notify_dashboard(self, symbol: str, dataset: List[Dict[str, Any]], dashboard_path: Optional[str] = None) -> bool:
        """
        Calculates aggregate KPIs and sends a premium ledger summary.
        """
        # 1. Compute KPIs in Python
        executed = [d for d in dataset if d['tp_sl_result'] in ['TP_HIT', 'SL_HIT', 'NEITHER']]
        wins = [d for d in executed if d['tp_sl_result'] == 'TP_HIT']
        
        net_pnl = float(sum(d.get('estimated_pnl_pct', 0.0) for d in executed))
        win_rate = round(float(len(wins) / len(executed) * 100.0), 1) if executed else 0.0
        
        stats = {
            "executed_count": len(executed),
            "win_rate": float(f"{win_rate:.1f}"),
            "net_pnl": float(f"{net_pnl:.2f}")
        }

        # 2. Render Template
        html_body = DashboardEmailTemplate.render(symbol, stats, dataset)
        
        # 3. Local Preview
        self.save_html_preview(f"{symbol}_ledger", html_body)

        if not self.enabled:
            return False

        # 4. Subject Design (🎯 style as requested)
        pnl_sign = "+" if net_pnl >= 0 else ""
        subject = f"🎯 Ledger | {symbol} | {win_rate}% WR | {pnl_sign}{float(f'{net_pnl:.2f}')}%"
        
        logger.info(f"Notifier: Dispatching ledger summary: {subject}")
        
        # Optionally attach the html file
        files = [dashboard_path] if dashboard_path and os.path.exists(dashboard_path) else None
        
        return self.dispatcher.dispatch(subject, html_body, files=files)

if __name__ == "__main__":
    import argparse
    import sys
    
    # Configure granular logging for CLI use
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    parser = argparse.ArgumentParser(description="Crypto Strategy Email Notifier CLI")
    parser.add_argument("--data-root", required=True, help="Root directory for visualizations/logs")
    parser.add_argument("--file", required=True, help="Path to the strategy JSON file")
    
    args = parser.parse_args()
    
    if not os.path.exists(args.file):
        print(f"Error: Strategy file not found at {args.file}")
        sys.exit(1)
        
    try:
        with open(args.file, 'r') as f:
            # We use a hacky way to support 'null', 'true', 'false' in case the file 
            # was copied from a Python representation, but primarily we expect standard JSON.
            # json.load handles standard JSON 'null' correctly.
            strategy_data = json.load(f)
            
        symbol = strategy_data.get("observation", {}).get("symbol", "UNKNOWN")
        notifier = StrategyNotifier(data_root=args.data_root)
        
        print(f"--- Dispatching Test Email for {symbol} ---")
        success = notifier.notify_strategy(symbol, strategy_data)
        
        if success:
            print("Successfully dispatched strategy alert!")
        else:
            print("Failed to dispatch alert. Check logs or check if credentials are set in .env")
            
    except Exception as e:
        print(f"Critical error during execution: {e}")
        sys.exit(1)
