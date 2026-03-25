from dataclasses import dataclass
import os
import json
import logging
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.image import MIMEImage
from datetime import datetime
from typing import Dict, List, Any, Optional
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

@dataclass(frozen=True)
class NotificationConfig:
    """Encapsulates email server and credential settings."""
    smtp_server: str
    smtp_port: int
    sender_email: str
    sender_password: str
    enabled: bool

    @classmethod
    def from_env(cls) -> "NotificationConfig":
        """Factory to load settings from environment variables."""
        load_dotenv()
        sender = os.environ.get("EMAIL_ADDRESS")
        password = os.environ.get("EMAIL_APP_PASSWORD")
        return cls(
            smtp_server=os.environ.get("EMAIL_SMTP_SERVER", "smtp.gmail.com"),
            smtp_port=int(os.environ.get("EMAIL_SMTP_PORT", 587)),
            sender_email=sender or "",
            sender_password=password or "",
            enabled=bool(sender and password)
        )

class StrategyEmailTemplate:
    """
    Handles the generation of professional HTML templates for trading strategies.
    Decouples the UI presentation from the data fetching/sending logic.
    """
    
    @staticmethod
    def render(strategy_data: Dict[str, Any]) -> str:
        """
        Renders the final strategy JSON into a rich HTML report.
        """
        obs = strategy_data.get("observation", {})
        decision = strategy_data.get("final_decision", {})
        symbol = obs.get("symbol", "UNKNOWN")
        
        # 1. Local Time Conversion (Device Local)
        utc_ts = obs.get("timestamp", "")
        try:
            # astimezone() with no args uses the system's local timezone
            local_dt = datetime.fromisoformat(utc_ts.replace("Z", "+00:00")).astimezone()
            display_time = local_dt.strftime("%Y-%m-%d %H:%M:%S %Z")
        except Exception:
            display_time = utc_ts

        # 2. Extract Key Metrics
        metrics = obs.get("quantitative_metrics", {})
        dynamics = metrics.get("price_dynamics", {})
        regime = metrics.get("market_regime", {})
        sentiment = metrics.get("sentiment_signals", {})
        
        opinion = decision.get("opinion", "NEUTRAL").upper()
        confidence = decision.get("confidence", 0)
        reasoning = decision.get("reasoning", "No description provided.")
        
        # UI Styling based on opinion
        colors = {"BULLISH": "#10b981", "BEARISH": "#ef4444", "NEUTRAL": "#64748b"}
        icons = {"BULLISH": "📈", "BEARISH": "📉", "NEUTRAL": "↔️"}
        theme_color = colors.get(opinion, "#64748b")
        theme_icon = icons.get(opinion, "💡")

        return f"""
        <html>
        <body style="font-family: 'Inter', system-ui, -apple-system, sans-serif; color: #1e293b; background: #f8fafc; padding: 20px;">
            <div style="max-width: 800px; margin: 0 auto; background: #ffffff; padding: 40px; border-radius: 16px; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.1); border: 1px solid #e2e8f0;">
                
                <!-- Header Section -->
                <div style="text-align: center; margin-bottom: 35px;">
                    <div style="display: inline-block; padding: 6px 14px; border-radius: 50px; background-color: {theme_color}15; color: {theme_color}; font-weight: 700; font-size: 13px; margin-bottom: 12px; border: 1px solid {theme_color}30;">
                        {theme_icon} MARKET {opinion}
                    </div>
                    <h1 style="color: #0f172a; margin: 0; font-size: 32px; letter-spacing: -0.025em;">{symbol} Strategy Report</h1>
                    <p style="color: #64748b; margin-top: 8px; font-size: 14px; font-weight: 500;">
                        Confidence: <span style="color: {theme_color}; font-weight: 700;">{confidence}%</span> | {display_time}
                    </p>
                </div>

                <!-- Strategic Summary (Draft -> Audit -> Synthesis Result) -->
                <div style="background-color: #f1f5f9; padding: 25px; border-radius: 12px; border-left: 5px solid {theme_color}; margin-bottom: 35px;">
                    <h3 style="margin-top: 0; color: #334155; font-size: 18px; display: flex; align-items: center;">
                        <span style="margin-right: 8px;">🎯</span> Refined Strategic Reasoning
                    </h3>
                    <p style="font-size: 15px; line-height: 1.6; color: #1e293b; margin-bottom: 0;">{reasoning}</p>
                </div>

                <!-- Dashboard Stats Grid -->
                <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 20px; margin-bottom: 35px;">
                    <div style="background: #ffffff; border: 1px solid #e2e8f0; border-radius: 10px; padding: 20px;">
                        <h4 style="margin: 0 0 12px 0; color: #64748b; font-size: 11px; text-transform: uppercase; font-weight: 700; letter-spacing: 0.05em;">Price Dynamics</h4>
                        <div style="font-size: 14px; color: #334155; line-height: 1.8;">
                            Price: <strong>{dynamics.get('current_price', 'N/A')}</strong><br>
                            Vol-Ratio: <strong>{dynamics.get('vol_ratio', 'N/A')}</strong><br>
                            Wick-Skew: <strong>{dynamics.get('wick_skewness', 'N/A')}</strong>
                        </div>
                    </div>
                    <div style="background: #ffffff; border: 1px solid #e2e8f0; border-radius: 10px; padding: 20px;">
                        <h4 style="margin: 0 0 12px 0; color: #64748b; font-size: 11px; text-transform: uppercase; font-weight: 700; letter-spacing: 0.05em;">Market Regime</h4>
                        <div style="font-size: 14px; color: #334155; line-height: 1.8;">
                            Regime: <strong>{regime.get('market_regime', 'N/A')}</strong><br>
                            Trend: <strong>{regime.get('trend_intensity', 'N/A')}</strong><br>
                            Squeeze: <strong>{regime.get('squeeze_factor', 'N/A')}</strong>
                        </div>
                    </div>
                </div>

                <!-- Visual Assets (Charts) -->
                <div id="charts-root">
                    <!-- Placeholder for CID images -->
                    <div style="margin-top: 30px; text-align: center;">
                        <div style="margin-bottom: 30px;">
                            <h4 style="color: #64748b; margin-bottom: 12px; font-size: 11px; text-transform: uppercase;">📊 Macro Topography Snapshot</h4>
                            <img src="cid:macro_chart" style="max-width: 100%; border-radius: 8px; border: 1px solid #e2e8f0;">
                        </div>
                        <div style="margin-bottom: 10px;">
                            <h4 style="color: #64748b; margin-bottom: 12px; font-size: 11px; text-transform: uppercase;">🔍 Micro execution context</h4>
                            <img src="cid:micro_chart" style="max-width: 100%; border-radius: 8px; border: 1px solid #e2e8f0;">
                        </div>
                    </div>
                </div>

                <!-- Forensic Detail (Raw JSON) -->
                <div style="margin-top: 40px; border-top: 1px solid #e2e8f0; padding-top: 25px;">
                    <details>
                        <summary style="font-size: 13px; color: #94a3b8; cursor: pointer; font-weight: 600;">View Raw Data Logs</summary>
                        <pre style="background: #0f172a; color: #cbd5e1; padding: 20px; border-radius: 8px; font-size: 11px; overflow-x: auto; margin-top: 15px;"><code>{json.dumps(strategy_data, indent=2, ensure_ascii=False)}</code></pre>
                    </details>
                </div>

                <div style="text-align: center; margin-top: 40px; color: #94a3b8; font-size: 12px;">
                    Automated Trading Intelligence System | Forensic Modernization Phase
                </div>
            </div>
        </body>
        </html>
        """

class StrategyEmailDispatcher:
    """Manages the low-level infrastructure for sending emails via SMTP."""
    
    def __init__(self, config: NotificationConfig):
        self.config = config

    def dispatch(self, subject: str, html_body: str, attachments: Dict[str, str]) -> bool:
        """Sends a multi-part email with HTML body and image attachments."""
        if not self.config.enabled:
            logger.warning("Dispatcher: Email notifications are disabled (missing credentials).")
            return False

        msg = MIMEMultipart('related')
        msg['From'] = self.config.sender_email
        msg['To'] = self.config.sender_email  # Self-notification
        msg['Subject'] = subject

        # Attach HTML body
        msg.attach(MIMEText(html_body, 'html', 'utf-8'))

        # Attach Visual Assets (Charts)
        for cid, file_path in attachments.items():
            if file_path and os.path.exists(file_path):
                try:
                    with open(file_path, 'rb') as f:
                        img = MIMEImage(f.read())
                        img.add_header('Content-ID', f'<{cid}>')
                        img.add_header('Content-Disposition', 'inline', filename=os.path.basename(file_path))
                        msg.attach(img)
                except Exception as e:
                    logger.error(f"Dispatcher: Failed to attach image {cid}: {e}")

        # Execute SMTP send
        try:
            with smtplib.SMTP(self.config.smtp_server, self.config.smtp_port) as server:
                server.starttls()
                server.login(self.config.sender_email, self.config.sender_password)
                server.send_message(msg)
            return True
        except Exception as e:
            logger.error(f"Dispatcher: SMTP relay failed: {e}")
            return False

class StrategyNotifier:
    """
    High-level facade for dispatching trading strategy alerts.
    Orchestrates template rendering and email dispatching.
    """
    
    def __init__(self, data_root: str = "data"):
        self.config = NotificationConfig.from_env()
        self.dispatcher = StrategyEmailDispatcher(self.config)
        self.data_root = data_root

    @property
    def enabled(self) -> bool:
        return self.config.enabled

    def notify_strategy(self, symbol: str, strategy_data: Dict[str, Any]) -> bool:
        """
        Parses strategy result and dispatches an actionable email alert.
        """
        # Always generate HTML for potential preview even if email is disabled
        html_body = StrategyEmailTemplate.render(strategy_data)
        
        # Collect Visual Attachments
        assets = strategy_data.get("observation", {}).get("visual_assets", {})
        attachments = {
            "macro_chart": assets.get("macro_snapshot"),
            "micro_chart": assets.get("micro_snapshot")
        }

        # 1. Local Preview (Useful for debugging/UI verification)
        self.save_html_preview(symbol, html_body)

        if not self.enabled:
            return False
            
        opinion = strategy_data.get("final_decision", {}).get("opinion", "NEUTRAL")
        confidence = strategy_data.get("final_decision", {}).get("confidence", 0)
        subject = f"[{opinion}] {symbol} Trading Strategy ({confidence}%)"
        
        # 2. Dispatch Email
        logger.info(f"Notifier: Dispatching strategy alert for {symbol}...")
        return self.dispatcher.dispatch(subject, html_body, attachments)

    def save_html_preview(self, symbol: str, html_body: str) -> Optional[str]:
        """
        Saves the rendered HTML to a local file for visual inspection.
        Uses the instance's data_root.
        """
        try:
            output_dir = os.path.join(self.data_root, "html")
            os.makedirs(output_dir, exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            file_name = f"{symbol}_strategy_preview_{timestamp}.html"
            file_path = os.path.join(output_dir, file_name)
            
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(html_body)
            
            logger.info(f"Notifier: HTML preview saved to {file_path}")
            return file_path
        except Exception as e:
            logger.error(f"Notifier: Failed to save HTML preview: {e}")
            return None
