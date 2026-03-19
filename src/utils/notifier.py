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
        self.config = config.get('notifications', {})
        self.smtp_server = self.config.get('smtp_server', 'smtp.gmail.com')
        self.smtp_port = self.config.get('smtp_port', 587)

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
        
        # New Zealand Time Conversion
        nz_time_str = "N/A"
        try:
            timestamp_str = prediction.get('timestamp')
            if timestamp_str:
                # Handle Z suffix if present
                if timestamp_str.endswith('Z'):
                    timestamp_str = timestamp_str[:-1]
                
                # Parse the ISO timestamp (assuming UTC)
                utc_dt = datetime.fromisoformat(timestamp_str).replace(tzinfo=ZoneInfo("UTC"))
                nz_dt = utc_dt.astimezone(ZoneInfo("Pacific/Auckland"))
                nz_time_str = nz_dt.strftime("%Y-%m-%d %H:%M:%S NZDT/NZST")
        except Exception as e:
            logger.warning(f"Failed to convert timestamp to NZ time: {e}")
        
        subject = f"Crypto Alert: {action} {symbol} (Confidence: {confidence}%)"
        
        # Prepare HTML body with image placeholders
        img_html = ""
        if chart_paths:
            img_html = "<div style='margin-top: 20px;'>"
            for i, path in enumerate(chart_paths):
                if os.path.exists(path):
                    cid = f"image_{i}"
                    img_html += f"<div style='margin-bottom: 20px;'><h4 style='color: #2c3e50;'>Chart {i+1} ({os.path.basename(path)}):</h4><img src='cid:{cid}' style='max-width: 100%; border: 1px solid #ddd; border-radius: 5px;'></div>"
            img_html += "</div>"
        
        body = f"""
        <html>
        <body style="font-family: Arial, sans-serif; color: #333; line-height: 1.6;">
            <div style="background-color: #f4f4f4; padding: 20px; border-radius: 10px;">
                <h2 style="color: #2c3e50; border-bottom: 2px solid #3498db; padding-bottom: 10px;">🚀 Trade Signal Detected: {action} {symbol}</h2>
                <div style="background-color: #fff; padding: 15px; border-radius: 5px; border: 1px solid #ddd;">
                    <pre style="background: #272822; color: #f8f8f2; padding: 15px; border-radius: 5px; overflow-x: auto;"><code>{formatted_json}</code></pre>
                </div>
                
                <div style="margin-top: 15px; font-weight: bold; color: #34495e;">
                    🇳🇿 New Zealand Time: <span style="color: #e67e22;">{nz_time_str}</span>
                </div>
                
                <h3 style="color: #2c3e50; margin-top: 25px;">🇨🇳 中文解析 (Mandarin Translation):</h3>
                <div style="background-color: #e8f4fd; padding: 15px; border-radius: 5px; border-left: 5px solid #3498db; font-size: 1.1em;">
                    {reasoning_zh}
                </div>
                
                {img_html}
                
                <p style="margin-top: 30px; border-top: 1px solid #ddd; padding-top: 10px; font-size: 0.9em; color: #7f8c8d;">
                    This is an automated notification from your Crypto Agent System.
                </p>
            </div>
        </body>
        </html>
        """

        msg = MIMEMultipart()
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
