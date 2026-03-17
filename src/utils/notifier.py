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
        self.sender_password = os.environ.get("SENDER_PASSWORD") # App Password for Gmail

    def send_prediction_alert(self, symbol, prediction):
        """
        Send an email alert for a high-confidence prediction.
        """
        if not self.enabled or not self.sender_email or not self.sender_password:
            logger.warning("Email notification skipped: Disabled or credentials missing in .env")
            return False

        confidence = prediction.get('confidence', 0)
        action = prediction.get('action', 'HOLD')
        reasoning = prediction.get('reasoning', 'No reasoning provided.')
        metadata = prediction.get('metadata', {})
        prompt_version = metadata.get('prompt_version', 'N/A')
        config_snapshot = metadata.get('config_snapshot', {})

        subject = f"Crypto Alert: {action} {symbol} (Confidence: {confidence}%)"
        
        body = f"""
        <h3>Trade Signal Detected</h3>
        <p><b>Symbol:</b> {symbol}</p>
        <p><b>Action:</b> {action}</p>
        <p><b>Confidence:</b> {confidence}%</p>
        <hr>
        <p><b>Reasoning:</b></p>
        <p style="white-space: pre-wrap;">{reasoning}</p>
        <hr>
        <p><b>Metadata:</b></p>
        <ul>
            <li><b>Prompt Version:</b> {prompt_version}</li>
            <li><b>Config Snapshot:</b> {config_snapshot}</li>
        </ul>
        <hr>
        <p><small>This is an automated notification from your Crypto Dual-Agent System.</small></p>
        """

        msg = MIMEMultipart()
        msg['From'] = self.sender_email
        msg['To'] = self.recipient
        msg['Subject'] = subject
        msg.attach(MIMEText(body, 'html'))

        try:
            with smtplib.SMTP(self.smtp_server, self.smtp_port) as server:
                server.starttls()
                server.login(self.sender_email, self.sender_password)
                server.send_message(msg)
            logger.info(f"Email alert sent to {self.recipient} for {symbol}")
            return True
        except Exception as e:
            logger.error(f"Failed to send email: {e}")
            return False
