from dataclasses import dataclass
import os
import json
import logging
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.image import MIMEImage
from typing import Dict, Any, Optional, List
from dotenv import load_dotenv

from src.utils.logger_utils import setup_logger
logger = setup_logger(__name__)

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

class BaseEmailTemplate:
    """
    Base class for email templates, providing shared styles and structural components.
    """
    @staticmethod
    def get_styles() -> str:
        return """
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <style>
                body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; line-height: 1.5; color: #334155; margin: 0; padding: 20px; background-color: #f8fafc; }
                .container { max-width: 850px; margin: 0 auto; background: #ffffff; border-radius: 12px; box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.1); padding: 40px; border: 1px solid #e2e8f0; }
                .badge { display: inline-block; padding: 4px 12px; border-radius: 9999px; font-size: 12px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.05em; }
                .panel { background: #ffffff; border: 1px solid #e2e8f0; border-radius: 10px; padding: 15px; }
                .panel-title { margin: 0 0 10px 0; color: #64748b; font-size: 10px; text-transform: uppercase; font-weight: 700; border-bottom: 1px solid #f1f5f9; padding-bottom: 5px; }
                .grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 15px; margin-bottom: 35px; }
                .metric-box { background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; padding: 12px; text-align: center; }
                .metric-label { font-size: 10px; color: #64748b; text-transform: uppercase; font-weight: 700; display: block; margin-bottom: 4px; }
                .metric-value { font-size: 16px; color: #0f172a; font-weight: 800; }
                .metric_pnl_pos { color: #10b981; }
                .metric_pnl_neg { color: #ef4444; }
                table { width: 100%; border-collapse: collapse; margin-bottom: 20px; }
                th { text-align: left; font-size: 11px; text-transform: uppercase; color: #64748b; padding: 10px; border-bottom: 1px solid #e2e8f0; }
                td { padding: 10px; border-bottom: 1px solid #f1f5f9; font-size: 13px; color: #334155; }
                
                /* Responsive Overrides */
                @media only screen and (max-width: 600px) {
                    .container { padding: 20px !important; }
                    .responsive-metrics td { 
                        display: block !important; 
                        width: 100% !important; 
                        box-sizing: border-box; 
                        margin-bottom: 15px;
                        border-bottom: 1px solid #334155 !important;
                        padding-bottom: 15px !important;
                    }
                    .responsive-metrics td:last-child {
                        border-bottom: none !important;
                        margin-bottom: 0 !important;
                    }
                }
            </style>
        """

    @staticmethod
    def fmt(v: Any) -> str:
        """Formatting helper to handle None (null) values gracefully in the UI."""
        return str(v) if v is not None else "N/A"

    @staticmethod
    def format_duration(hours: float) -> str:
        """Formats hours into a human-readable string (e.g., 18.5h or 2.3d)."""
        if hours < 24:
            return f"{hours:.1f}h"
        days = hours / 24
        return f"{days:.1f}d"

    @staticmethod
    def render_footer(full_json: Dict[str, Any], trigger_info: str) -> str:
        return f"""
                <div style="margin-top: 40px; border-top: 1px solid #e2e8f0; padding-top: 25px; text-align: center;">
                    <details>
                        <summary style="font-size: 12px; color: #94a3b8; cursor: pointer; font-weight: 600;">Raw Data</summary>
                        <pre style="background: #1e293b; color: #cbd5e1; padding: 20px; border-radius: 8px; font-size: 11px; text-align: left; overflow-x: auto; margin-top: 15px;"><code>{json.dumps(full_json, indent=2, ensure_ascii=False)}</code></pre>
                    </details>
                    <div style="margin-top: 25px; color: #94a3b8; font-size: 11px; font-weight: 500;">
                        {trigger_info}
                    </div>
                </div>
        """

    @staticmethod
    def render_summary_footer(trigger_info: str) -> str:
        """Lightweight footer for aggregate reports, excludes raw JSON data blocks."""
        return f"""
                <div style="margin-top: 40px; border-top: 1px solid #e2e8f0; padding-top: 25px; text-align: center;">
                    <div style="margin-top: 10px; color: #94a3b8; font-size: 11px; font-weight: 500;">
                        {trigger_info}
                    </div>
                </div>
        """

class EmailDispatcher:
    """Manages the low-level infrastructure for sending emails via SMTP."""
    
    def __init__(self, config: NotificationConfig):
        self.config = config

    def dispatch(self, subject: str, html_body: str, attachments: Optional[Dict[str, str]] = None, files: Optional[List[str]] = None) -> bool:
        """Sends a multi-part email with HTML body, image attachments (CID), and file attachments."""
        if not self.config.enabled:
            logger.warning("Dispatcher: Email notifications are disabled (missing credentials).")
            return False

        msg = MIMEMultipart('related')
        msg['From'] = self.config.sender_email
        msg['To'] = self.config.sender_email  # Self-notification
        msg['Subject'] = subject

        # Attach HTML body
        msg.attach(MIMEText(html_body, 'html', 'utf-8'))

        # Attach Image Assets (CID based)
        if attachments:
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

        # Attach Regular Files
        if files:
            import mimetypes
            from email.mime.application import MIMEApplication
            for file_path in files:
                if file_path and os.path.exists(file_path):
                    try:
                        mime_type, _ = mimetypes.guess_type(file_path)
                        if mime_type == 'text/html':
                            with open(file_path, 'r', encoding='utf-8') as f:
                                part = MIMEText(f.read(), 'html', 'utf-8')
                        else:
                            with open(file_path, 'rb') as f:
                                part = MIMEApplication(f.read())
                        part.add_header('Content-Disposition', 'attachment', filename=os.path.basename(file_path))
                        msg.attach(part)
                    except Exception as e:
                        logger.error(f"Dispatcher: Failed to attach file {file_path}: {e}")

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
