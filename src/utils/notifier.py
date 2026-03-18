import smtplib
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import os
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

class EmailNotifier:
    def __init__(self, config):
        """
        Initialize with config dictionary from config.yaml
        """
        self.config = config.get('notifications', {})
        self.enabled = self.config.get('email_enabled', False)
        self.recipient = self.config.get('recipient_email')
        self.smtp_server = self.config.get('smtp_server', 'smtp.gmail.com')
        self.smtp_port = self.config.get('smtp_port', 587)
        
        # Load credentials from .env
        load_dotenv()
        self.sender_email = os.environ.get("SENDER_EMAIL")
        self.sender_app_password = os.environ.get("SENDER_APP_PASSWORD")

    def send_prediction_alert(self, symbol, prediction):
        """
        Send an email alert for a high-confidence prediction.
        """
        if not self.enabled or not self.sender_email or not self.sender_app_password:
            logger.warning("Email notification skipped: Disabled or credentials missing in .env")
            return False

        import json
        
        confidence = prediction.get('confidence', 0)
        action = prediction.get('action', 'HOLD')
        
        # Format the full prediction JSON nicely
        # Remove reasoning_zh from the displayed JSON to keep it clean if preferred, 
        # or just show everything. The user asked for "basically just all prediction json".
        prediction_copy = prediction.copy()
        reasoning_zh = prediction_copy.pop('reasoning_zh', 'N/A')
        
        formatted_json = json.dumps(prediction_copy, indent=4)
        
        subject = f"Crypto Alert: {action} {symbol} (Confidence: {confidence}%)"
        
        body = f"""
        <html>
        <body style="font-family: Arial, sans-serif; color: #333; line-height: 1.6;">
            <div style="background-color: #f4f4f4; padding: 20px; border-radius: 10px;">
                <h2 style="color: #2c3e50; border-bottom: 2px solid #3498db; padding-bottom: 10px;">🚀 Trade Signal Detected: {action} {symbol}</h2>
                <div style="background-color: #fff; padding: 15px; border-radius: 5px; border: 1px solid #ddd;">
                    <pre style="background: #272822; color: #f8f8f2; padding: 15px; border-radius: 5px; overflow-x: auto;"><code>{formatted_json}</code></pre>
                </div>
                
                <h3 style="color: #2c3e50; margin-top: 25px;">🇨🇳 中文解析 (Mandarin Translation):</h3>
                <div style="background-color: #e8f4fd; padding: 15px; border-radius: 5px; border-left: 5px solid #3498db; font-size: 1.1em;">
                    {reasoning_zh}
                </div>
                
                <p style="margin-top: 30px; border-top: 1px solid #ddd; padding-top: 10px; font-size: 0.9em; color: #7f8c8d;">
                    This is an automated notification from your Crypto Agent System.
                </p>
            </div>
        </body>
        </html>
        """

        msg = MIMEMultipart()
        msg['From'] = self.sender_email
        msg['To'] = self.recipient
        msg['Subject'] = subject
        msg.attach(MIMEText(body, 'html'))

        try:
            with smtplib.SMTP(self.smtp_server, self.smtp_port) as server:
                server.starttls()
                server.login(self.sender_email, self.sender_app_password)
                server.send_message(msg)
            logger.info(f"Email alert sent to {self.recipient} for {symbol}")
            return True
        except Exception as e:
            logger.error(f"Failed to send email: {e}")
            return False
