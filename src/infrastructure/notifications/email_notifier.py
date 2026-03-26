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
import yaml
from src.utils.path_utils import find_project_root

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
    def _format_duration(hours: float) -> str:
        """Formats hours into a human-readable string (e.g., 18.5h or 2.3d)."""
        if hours < 24:
            return f"{hours:.1f}h"
        days = hours / 24
        return f"{days:.1f}d"

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
            local_dt = datetime.fromisoformat(utc_ts.replace("Z", "+00:00")).astimezone()
            display_time = local_dt.strftime("%Y-%m-%d %H:%M:%S %Z")
        except Exception:
            display_time = utc_ts

        # 2. Extract Data Suites
        metrics = obs.get("quantitative_metrics", {})
        dynamics = metrics.get("price_dynamics", {})
        regime = metrics.get("market_regime", {})
        sentiment = metrics.get("sentiment_signals", {})
        structural = metrics.get("structural_anchors", {})
        topography = metrics.get("volume_topography", {})
        semantics = obs.get("semantic_analysis", {})
        
        critique = strategy_data.get("critique", {})
        skepticism = critique.get("skepticism_score", 0)
        
        opinion = decision.get("opinion", "NEUTRAL").upper()
        confidence = decision.get("confidence", 0)
        reasoning = decision.get("reasoning", "No description provided.")
        limit_order = decision.get("limit_order")
        
        # 3. UI Styling & Formatting
        colors = {"BULLISH": "#10b981", "BEARISH": "#ef4444", "NEUTRAL": "#64748b"}
        icons = {"BULLISH": "📈", "BEARISH": "📉", "NEUTRAL": "↔️"}
        theme_color = colors.get(opinion, "#64748b")
        theme_icon = icons.get(opinion, "💡")
        
        # Formatting helper to handle None (null) values gracefully in the UI
        fmt = lambda v: v if v is not None else "N/A"
        
        return f"""
        <html>
        <head>
            <meta charset="utf-8">
            <style>
                body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; line-height: 1.5; color: #334155; margin: 0; padding: 20px; background-color: #f8fafc; }}
                .container {{ max-width: 850px; margin: 0 auto; background: #ffffff; border-radius: 12px; box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.1); padding: 40px; border: 1px solid #e2e8f0; }}
                .badge {{ display: inline-block; padding: 4px 12px; border-radius: 9999px; font-size: 12px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.05em; }}
                .grid {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 15px; margin-bottom: 35px; }}
                .panel {{ background: #ffffff; border: 1px solid #e2e8f0; border-radius: 10px; padding: 15px; }}
                .panel-title {{ margin: 0 0 10px 0; color: #64748b; font-size: 10px; text-transform: uppercase; font-weight: 700; border-bottom: 1px solid #f1f5f9; padding-bottom: 5px; }}
            </style>
        </head>
        <body>
            <div class="container">
                <div style="text-align: center; margin-bottom: 35px; border-bottom: 2px solid #f1f5f9; padding-bottom: 25px;">
                    <div style="display: inline-block; padding: 6px 14px; border-radius: 50px; background-color: {theme_color}15; color: {theme_color}; font-weight: 700; font-size: 13px; margin-bottom: 12px; border: 1px solid {theme_color}30;">
                        {theme_icon} MARKET {opinion}
                    </div>
                    <h1 style="color: #0f172a; margin: 0; font-size: 32px; letter-spacing: -0.025em;">{symbol} Market Topography Audit</h1>
                    <p style="color: #64748b; margin-top: 8px; font-size: 14px; font-weight: 500;">
                        Confidence: <span style="color: {theme_color}; font-weight: 700;">{confidence}%</span> | 🕒 {display_time}
                    </p>
                </div>

                <!-- Adversarial Risk Audit -->
                {f'''
                <div style="background-color: #fff7ed; padding: 25px; border-radius: 12px; border: 1px solid #ffedd5; margin-bottom: 35px; border-left: 5px solid #f97316;">
                    <h3 style="margin: 0 0 10px 0; color: #9a3412; font-size: 16px; display: flex; align-items: center; justify-content: space-between;">
                        <span>⚖️ Adversarial Risk Audit</span>
                        <span style="background: #ffedd5; padding: 2px 8px; border-radius: 4px; font-size: 11px;">Audit Severity: {fmt(critique.get('skepticism_score'))}%</span>
                    </h3>
                    <p style="font-size: 14px; line-height: 1.6; color: #7c2d12; margin: 0;">{fmt(critique.get('hidden_risk'))}</p>
                </div>
                ''' if critique else ""}

                <!-- Audit Response -->
                {f'''
                <div style="margin-bottom: 35px; padding: 20px; border: 1px dashed #cbd5e1; border-radius: 12px; background-color: #f8fafc;">
                    <h3 style="margin-top: 0; color: #475569; font-size: 15px; margin-bottom: 12px;">🔄 Audit Response</h3>
                    <p style="font-size: 13px; line-height: 1.6; color: #334155; margin: 0; font-style: italic;">{fmt(decision.get('critic_impact'))}</p>
                </div>
                ''' if decision.get('critic_impact') else ""}

                <!-- Strategic Synthesis -->
                <div style="background-color: #f8fafc; padding: 25px; border-radius: 12px; border: 1px solid #e2e8f0; margin-bottom: 35px;">
                    <h3 style="margin-top: 0; color: #334155; font-size: 18px; margin-bottom: 15px;">🧩 Strategic Synthesis</h3>
                    <p style="font-size: 15px; line-height: 1.7; color: #1e293b; margin-bottom: 20px;">{reasoning}</p>
                    
                    {f'''
                    <div style="background: #1e293b; padding: 20px; border-radius: 8px; display: grid; grid-template-columns: repeat(4, 1fr); gap: 15px; text-align: center;">
                        <div>
                            <div style="font-size: 11px; color: #94a3b8; text-transform: uppercase; font-weight: 700; margin-bottom: 5px;">Entry</div>
                            <div style="font-size: 18px; color: #60a5fa; font-weight: 800; font-family: 'SF Mono', 'Courier New', monospace;">{fmt(decision.get('limit_order', {}).get('entry'))}</div>
                        </div>
                        <div>
                            <div style="font-size: 11px; color: #94a3b8; text-transform: uppercase; font-weight: 700; margin-bottom: 5px;">Take Profit</div>
                            <div style="font-size: 18px; color: #34d399; font-weight: 800; font-family: 'SF Mono', 'Courier New', monospace;">{fmt(decision.get('limit_order', {}).get('take_profit'))}</div>
                        </div>
                        <div>
                            <div style="font-size: 11px; color: #94a3b8; text-transform: uppercase; font-weight: 700; margin-bottom: 5px;">Stop Loss</div>
                            <div style="font-size: 18px; color: #fb7185; font-weight: 800; font-family: 'SF Mono', 'Courier New', monospace;">{fmt(decision.get('limit_order', {}).get('stop_loss'))}</div>
                        </div>
                        <div>
                            <div style="font-size: 11px; color: #94a3b8; text-transform: uppercase; font-weight: 700; margin-bottom: 5px;">Temporal Window</div>
                            <div style="font-size: 18px; color: #cbd5e1; font-weight: 800; font-family: 'SF Mono', 'Courier New', monospace;">{StrategyEmailTemplate._format_duration(decision.get('limit_order', {}).get('holding_time_hours', 0))}</div>
                        </div>
                    </div>
                    ''' if decision else ""}
                </div>

                <!-- 2026-03-26 Update: Forensic Dashboard Grid removed to reduce noise for focused textual analysis. -->

                <!-- Intelligence Briefing -->
                <div style="margin-bottom: 35px; border-top: 1px solid #e2e8f0; padding-top: 25px;">
                    <h3 style="margin-top: 0; color: #334155; font-size: 18px; margin-bottom: 20px;">🗺️ Market Topography Forensic</h3>
                    <div style="display: grid; grid-template-columns: 1fr; gap: 15px;">
                        <!-- 1. Synthesized Topography (Highest Priority) -->
                        <div style="border-left: 4px solid #3b82f6; background-color: #eff6ff; padding: 15px; border-radius: 0 8px 8px 0; margin-bottom: 15px;">
                            <span style="font-size: 11px; font-weight: 800; color: #1e40af; text-transform: uppercase; letter-spacing: 0.05em;">Synthesized Topography</span>
                            <p style="font-size: 13px; color: #1e3a8a; margin-top: 8px; line-height: 1.6; font-weight: 500;">{fmt(semantics.get('synthesized_topography'))}</p>
                        </div>

                        <!-- 2. Structural Gravity -->
                        <div style="border-left: 3px solid #cbd5e1; padding-left: 15px; margin-bottom: 12px;">
                            <span style="font-size: 11px; font-weight: 700; color: #64748b; text-transform: uppercase;">Structural Gravity</span>
                            <p style="font-size: 13px; color: #475569; margin-top: 5px; line-height: 1.5;">{fmt(semantics.get('structural_gravity'))}</p>
                        </div>

                        <!-- 3. Topographical Friction -->
                        <div style="border-left: 3px solid #cbd5e1; padding-left: 15px; margin-bottom: 12px;">
                            <span style="font-size: 11px; font-weight: 700; color: #64748b; text-transform: uppercase;">Topographical Friction</span>
                            <p style="font-size: 13px; color: #475569; margin-top: 5px; line-height: 1.5;">{fmt(semantics.get('topographical_friction'))}</p>
                        </div>

                        <!-- 4. Sentiment Flow -->
                        <div style="border-left: 3px solid #cbd5e1; padding-left: 15px; margin-bottom: 12px;">
                            <span style="font-size: 11px; font-weight: 700; color: #64748b; text-transform: uppercase;">Sentiment Flow</span>
                            <p style="font-size: 13px; color: #475569; margin-top: 5px; line-height: 1.5;">{fmt(semantics.get('sentiment_flow'))}</p>
                        </div>

                        <!-- 5. Regime & Volatility -->
                        <div style="border-left: 3px solid #cbd5e1; padding-left: 15px; margin-bottom: 12px;">
                            <span style="font-size: 11px; font-weight: 700; color: #64748b; text-transform: uppercase;">Regime & Volatility</span>
                            <p style="font-size: 13px; color: #475569; margin-top: 5px; line-height: 1.5;">{fmt(semantics.get('regime_volatility'))}</p>
                        </div>

                        <!-- 6. Micro-Interactive detail -->
                        <div style="border-left: 3px solid #cbd5e1; padding-left: 15px; margin-bottom: 10px;">
                            <span style="font-size: 11px; font-weight: 700; color: #64748b; text-transform: uppercase;">Micro-Interactive detail</span>
                            <p style="font-size: 13px; color: #475569; margin-top: 5px; line-height: 1.5;">{fmt(semantics.get('micro_interactive'))}</p>
                        </div>
                    </div>
                </div>

                <!-- Visual Assets -->
                <div id="charts-root" style="text-align: center;">
                    <h4 style="color: #64748b; margin-bottom: 15px; font-size: 11px; text-transform: uppercase;">📊 Visual Forensic Proof</h4>
                    <div style="margin-bottom: 30px;">
                        <img src="cid:macro_chart" style="max-width: 100%; border-radius: 12px; border: 1px solid #e2e8f0; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.05);">
                    </div>
                    <div>
                        <img src="cid:micro_chart" style="max-width: 100%; border-radius: 12px; border: 1px solid #e2e8f0; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.05);">
                    </div>
                </div>

                <!-- Footer -->
                <div style="margin-top: 40px; border-top: 1px solid #e2e8f0; padding-top: 25px; text-align: center;">
                    <details>
                        <summary style="font-size: 12px; color: #94a3b8; cursor: pointer; font-weight: 600;">Full Forensic Dataset</summary>
                        <pre style="background: #1e293b; color: #cbd5e1; padding: 20px; border-radius: 8px; font-size: 11px; text-align: left; overflow-x: auto; margin-top: 15px;"><code>{json.dumps(strategy_data, indent=2, ensure_ascii=False)}</code></pre>
                    </details>
                    <div style="margin-top: 25px; color: #94a3b8; font-size: 11px; font-weight: 500;">
                        This is an auto-generated email notification | Triggered by Crypto Strategy
                    </div>
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
    
    def __init__(self, data_root: str):
        self.config = NotificationConfig.from_env()
        self.dispatcher = StrategyEmailDispatcher(self.config)
        self.data_root = data_root
        self.global_cfg = self._load_global_config()
        
        # Sourcing threshold from global_config.yaml with fallback to hardcoded safety
        self.min_confidence_threshold = int(self.global_cfg['system']['min_confidence_for_notifier_threshold'])

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
        html_body = StrategyEmailTemplate.render(strategy_data)
        
        # Collect Visual Attachments
        assets = strategy_data.get("observation", {}).get("visual_assets", {})
        attachments = {
            "macro_chart": assets.get("macro_snapshot"),
            "micro_chart": assets.get("micro_snapshot")
        }

        # 1. Local Preview (Useful for debugging/UI verification)
        if save_local:
            self.save_html_preview(symbol, html_body, attachments)

        if not self.enabled:
            return False
            
        opinion = strategy_data.get("final_decision", {}).get("opinion", "NEUTRAL")
        confidence = strategy_data.get("final_decision", {}).get("confidence", 0)
        
        # Only notify if confidence >= threshold
        if confidence < self.min_confidence_threshold:
            logger.info(f"Notifier: Confidence too low ({confidence}% < {self.min_confidence_threshold}%). Skipping dispatch.")
            return False
            
        subject = f"{symbol} | {opinion} ({confidence}%) | Strategic Synthesis"
        
        # 2. Dispatch Email
        logger.info(f"Notifier: Dispatching alert: {subject}")
        return self.dispatcher.dispatch(subject, html_body, attachments)

    def save_html_preview(self, symbol: str, html_body: str, attachments: Dict[str, str]) -> Optional[str]:
        """
        Saves the rendered HTML to a local file for visual inspection.
        Swaps CID references for local filesystem paths.
        """
        try:
            # Default to data/test/html for previews to avoid mixing with live data
            test_root = os.path.join(find_project_root(), "data", "test")
            output_dir = os.path.join(test_root, "html")
            os.makedirs(output_dir, exist_ok=True)
            
            # For local preview, we need to swap 'cid:name' with the actual file path.
            # Since the preview is in data/html and assets are usually in data/klines,
            # we try to make them relative or use absolute if needed.
            preview_html = html_body
            for cid, file_path in attachments.items():
                if file_path:
                    # Convert to absolute path for reliable local browser opening
                    abs_path = os.path.abspath(file_path)
                    preview_html = preview_html.replace(f"cid:{cid}", f"file://{abs_path}")
            
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            file_name = f"{symbol}_strategy_preview_{timestamp}.html"
            file_path = os.path.join(output_dir, file_name)
            
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(preview_html)
            
            logger.info(f"Notifier: HTML preview saved to {file_path}")
            return file_path
        except Exception as e:
            logger.error(f"Notifier: Failed to save HTML preview: {e}")
            return None

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
