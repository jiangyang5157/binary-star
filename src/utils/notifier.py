import smtplib
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import os
from datetime import datetime
from zoneinfo import ZoneInfo
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

class EmailNotifier:
    def __init__(self, config):
        """
        Initialize with config dictionary from config.yaml
        """
        self.config = config['notifications']
        self.smtp_server = self.config['smtp_server']
        self.smtp_port = self.config['smtp_port']
        self.timezone = self.config['timezone']

        # Load credentials from .env
        load_dotenv()
        self.recipient = os.environ.get("RECIPIENT_EMAIL")
        self.recipient_app_password = os.environ.get("RECIPIENT_APP_PASSWORD")
        
        # Auto-enable if both credentials are provided
        self.enabled = bool(self.recipient and self.recipient_app_password)

    def send_prediction_alert(self, symbol, prediction, chart_paths=None):
        """
        Send an email alert for a high-confidence prediction.
        """
        if not self.enabled or not self.recipient or not self.recipient_app_password:
            logger.warning("Email notification skipped: Disabled or credentials missing in .env")
            return False

        import json
        from email.mime.image import MIMEImage
        
        confidence = prediction.get('confidence', 0)
        action = prediction.get('action', 'HOLD')
        
        # Format the full prediction JSON nicely
        # Remove reasoning_zh from the displayed JSON, and adding it back as a separate section
        prediction_copy = prediction.copy()
        reasoning_zh = prediction_copy.pop('reasoning_zh', 'N/A')
        
        formatted_json = json.dumps(prediction_copy, indent=4)
        
        # Optimized Time Conversion
        local_time_str = "N/A"
        try:
            timestamp_str = prediction.get('timestamp')
            if timestamp_str:
                # Use robust fromisoformat (handles Z in Python 3.11+)
                utc_dt = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
                local_dt = utc_dt.astimezone(ZoneInfo(self.timezone))
                local_time_str = local_dt.strftime(f"%Y-%m-%d %H:%M:%S {self.timezone}")
        except Exception as e:
            logger.warning(f"Failed to convert timestamp to local time ({self.timezone}): {e}")
        
        subject = f"Crypto Alert: {action} {symbol} (Confidence: {confidence}%)"
        
        # Prepare HTML body with premium styling
        img_html = ""
        if chart_paths:
            img_html = "<div style='margin-top: 20px;'>"
            for i, path in enumerate(chart_paths):
                if os.path.exists(path):
                    cid = f"image_{i}"
                    desc = "Macro Chart" if i == 0 else "Micro Chart"
                    img_html += f"""
                    <div style='margin-bottom: 25px;'>
                        <h4 style='color: #34495e; margin-bottom: 10px;'>📊 {desc} ({os.path.basename(path)}):</h4>
                        <img src='cid:{cid}' style='max-width: 100%; border: 2px solid #ecf0f1; border-radius: 8px; box-shadow: 0 4px 6px rgba(0,0,0,0.1);'>
                    </div>"""
            img_html += "</div>"
        
        # Determine Color based on action
        action_color = "#27ae60" if action == "BUY" else "#e74c3c" if action == "SELL" else "#f39c12"
        
        metadata = prediction.get('metadata', {})
        current_price = prediction.get('current_price', 'N/A')
        tp = prediction.get('take_profit', 'N/A')
        sl = prediction.get('stop_loss', 'N/A')

        body = f"""
        <html>
        <body style="font-family: 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; color: #2c3e50; line-height: 1.6; background-color: #f9f9f9; padding: 20px;">
            <div style="max-width: 800px; margin: 0 auto; background-color: #ffffff; padding: 30px; border-radius: 12px; box-shadow: 0 10px 25px rgba(0,0,0,0.05); border: 1px solid #eee;">
                
                <!-- Header Section -->
                <div style="text-align: center; margin-bottom: 30px;">
                    <h1 style="color: {action_color}; margin: 0; font-size: 28px; letter-spacing: 1px;">🚀 {action} {symbol}</h1>
                    <p style="color: #7f8c8d; margin-top: 5px; font-size: 14px;">Signal Detected at: <span style="color: #34495e; font-weight: 600;">{local_time_str}</span></p>
                </div>

                <!-- Core Details Grid -->
                <div style="background-color: #fcfcfc; border: 1px solid #f0f0f0; border-radius: 10px; padding: 20px; margin-bottom: 30px; display: flex; flex-wrap: wrap;">
                    <div style="flex: 1; min-width: 200px; padding: 10px;">
                        <span style="display: block; font-size: 12px; color: #95a5a6; text-transform: uppercase;">Confidence</span>
                        <span style="font-size: 24px; font-weight: bold; color: {action_color};">{confidence}%</span>
                    </div>
                    <div style="flex: 1; min-width: 200px; padding: 10px;">
                        <span style="display: block; font-size: 12px; color: #95a5a6; text-transform: uppercase;">Current Price</span>
                        <span style="font-size: 20px; font-weight: 600;">{current_price}</span>
                    </div>
                    <div style="flex: 1; min-width: 200px; padding: 10px;">
                        <span style="display: block; font-size: 12px; color: #27ae60; text-transform: uppercase;">Take Profit</span>
                        <span style="font-size: 20px; font-weight: 600; color: #27ae60;">{tp}</span>
                    </div>
                    <div style="flex: 1; min-width: 200px; padding: 10px;">
                        <span style="display: block; font-size: 12px; color: #e74c3c; text-transform: uppercase;">Stop Loss</span>
                        <span style="font-size: 20px; font-weight: 600; color: #e74c3c;">{sl}</span>
                    </div>
                </div>

                <!-- Reasoning Section (Mandarin) -->
                <div style="background-color: #e8f4fd; padding: 20px; border-radius: 8px; border-left: 6px solid #3498db; margin-bottom: 30px;">
                    <h3 style="margin-top: 0; color: #2980b9; font-size: 18px;">💡 Reasoning</h3>
                    <p style="font-size: 16px; margin-bottom: 0; color: #34495e;">{reasoning_zh}</p>
                </div>

                <!-- Metadata -->
                <div style="font-size: 12px; color: #bdc3c7; background: #fafafa; padding: 10px; border-radius: 5px; margin-bottom: 30px;">
                    <strong>System Metadata:</strong> Symbol: {metadata.get('symbol')} | Horizon: {metadata.get('trade_horizon_days')}d | Model: {metadata.get('model')}
                </div>

                <!-- Visual Charts -->
                {img_html}

                <!-- Technical Log (Accordion-style implied) -->
                <div style="margin-top: 40px; border-top: 1px solid #eee; padding-top: 15px;">
                    <p style="font-size: 12px; color: #95a5a6; text-transform: uppercase;">Full Technical Payload:</p>
                    <pre style="background: #272822; color: #c5c8c6; padding: 15px; border-radius: 5px; font-size: 11px; overflow-x: auto; line-height: 1.4;"><code>{formatted_json}</code></pre>
                </div>

                <p style="text-align: center; color: #bdc3c7; font-size: 11px; margin-top: 30px;">
                    This is an automated notification from your <strong>Crypto Triple-Agent System</strong>.
                </p>
            </div>
        </body>
        </html>
        """

        msg = MIMEMultipart()
        # Note: From == To is intentional for Gmail App Password self-notification setup
        msg['From'] = self.recipient
        msg['To'] = self.recipient
        msg['Subject'] = subject
        msg.attach(MIMEText(body, 'html'))

        # Attach images with CID for embedding
        if chart_paths:
            for i, path in enumerate(chart_paths):
                if os.path.exists(path):
                    with open(path, 'rb') as f:
                        img_data = f.read()
                        image = MIMEImage(img_data)
                        image.add_header('Content-ID', f'<image_{i}>')
                        image.add_header('Content-Disposition', 'inline', filename=os.path.basename(path))
                        msg.attach(image)

        try:
            with smtplib.SMTP(self.smtp_server, self.smtp_port) as server:
                server.starttls()
                server.login(self.recipient, self.recipient_app_password)
                server.send_message(msg)
            logger.info(f"Email alert sent to {self.recipient} for {symbol} with attachments")
            return True
        except Exception as e:
            logger.error(f"Failed to send email: {e}")
            return False
