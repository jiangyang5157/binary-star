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
        action = str(prediction.get('action', 'WAIT')).upper()
        opinion = str(prediction.get('opinion', 'NEUTRAL')).upper()
        pos_context = prediction.get('position_context', {"position_type": "NONE", "entry_price": None})
        pos_type = str(pos_context.get('position_type', 'NONE')).upper()
        entry_price = pos_context.get('entry_price')
        
        # Format the full prediction JSON nicely
        # Remove reasoning_zh from the displayed JSON, and adding it back as a separate section
        prediction_copy = prediction.copy()
        formatted_json = json.dumps(prediction_copy, indent=4, ensure_ascii=False)
        reasoning_zh = prediction_copy.pop('reasoning_zh', 'N/A')
        
        
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
        
        # Subject: Crypto: [ACTION] SYMBOL | OPINION (CONFIDENCE%)
        subject = f"Crypto: {action} {symbol} | {opinion} ({confidence}%)"
        
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
        # Determine Color and Icons
        action_colors = {
            "LONG": "#27ae60",
            "SHORT": "#e74c3c",
            "HOLD": "#3498db",
            "WAIT": "#95a5a6",
            "CLOSE": "#e67e22"
        }
        opinion_colors = {
            "BULLISH": "#27ae60",
            "BEARISH": "#e74c3c",
            "NEUTRAL": "#95a5a6"
        }
        action_icons = {
            "LONG": "🚀", "SHORT": "🐻", "HOLD": "💎", "WAIT": "⏳", "CLOSE": "🚪"
        }
        opinion_icons = {
            "BULLISH": "📈", "BEARISH": "📉", "NEUTRAL": "↔️"
        }
        
        action_color = action_colors.get(action, "#f39c12")
        opinion_color = opinion_colors.get(opinion, "#f39c12")
        action_icon = action_icons.get(action, "🔔")
        opinion_icon = opinion_icons.get(opinion, "💡")
        
        metadata = prediction.get('metadata', {})
        current_price = prediction.get('current_price', 'N/A')
        tp = prediction.get('take_profit', 'N/A')
        sl = prediction.get('stop_loss', 'N/A')
        horizon = prediction.get('config_context', {}).get('prediction_horizon_days', 'N/A')

        # Calculate TP/SL Ratio
        tpsl_ratio = "N/A"
        try:
            # Use entry_price as base if it exists, otherwise use current_price
            base_price = float(entry_price) if entry_price is not None else float(current_price)
            tp_f = float(tp)
            sl_f = float(sl)
            
            # Logic for LONG/BULLISH: (TP - Base) / (Base - SL)
            # Logic for SHORT/BEARISH: (Base - TP) / (SL - Base)
            
            is_long = action == "LONG" or opinion == "BULLISH"
            is_short = action == "SHORT" or opinion == "BEARISH"
            
            if is_long:
                if base_price > sl_f:
                    tpsl_ratio = f"{(tp_f - base_price) / (base_price - sl_f):.2f}"
            elif is_short:
                if sl_f > base_price:
                    tpsl_ratio = f"{(base_price - tp_f) / (sl_f - base_price):.2f}"
            
        except (Exception, ValueError, TypeError):
            pass

        body = f"""
        <html>
        <body style="font-family: 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; color: #2c3e50; line-height: 1.6; background-color: #f9f9f9; padding: 20px;">
            <div style="max-width: 800px; margin: 0 auto; background-color: #ffffff; padding: 30px; border-radius: 12px; box-shadow: 0 10px 25px rgba(0,0,0,0.05); border: 1px solid #eee;">
                
                <!-- Header Section -->
                <div style="text-align: center; margin-bottom: 30px;">
                    <div style="display: inline-block; padding: 8px 16px; border-radius: 50px; background-color: {opinion_color}15; color: {opinion_color}; font-weight: bold; font-size: 14px; margin-bottom: 10px; border: 1px solid {opinion_color}30;">
                        {opinion_icon} Market {opinion}
                    </div>
                    <h1 style="color: {action_color}; margin: 0; font-size: 32px; letter-spacing: 1px;">{action_icon} {action} {symbol}</h1>
                    <p style="color: #7f8c8d; margin-top: 8px; font-size: 14px;">Signal Confidence: <span style="color: {action_color}; font-weight: 700;">{confidence}%</span> | Detected at: <span style="color: #34495e; font-weight: 600;">{local_time_str}</span></p>
                </div>
                <!-- Position & Trade Summary -->
                <div style="margin-bottom: 25px;">
                    <!-- Tier 1: Current Status -->
                    <div style="display: flex; gap: 15px; margin-bottom: 15px; width: 100%;">
                        <div style="flex: 1; min-width: 0; background-color: #f8f9fa; border: 1px solid #e9ecef; border-radius: 8px; padding: 12px; text-align: center;">
                            <span style="display: block; font-size: 10px; color: #95a5a6; text-transform: uppercase;">Market Price</span>
                            <span style="font-size: 15px; font-weight: 700; color: #2c3e50;">{current_price}</span>
                        </div>
                        <div style="flex: 1; min-width: 0; background-color: #f8f9fa; border: 1px solid #e9ecef; border-radius: 8px; padding: 12px; text-align: center;">
                            <span style="display: block; font-size: 10px; color: #95a5a6; text-transform: uppercase;">Current Position</span>
                            <span style="font-size: 15px; font-weight: 700; color: #2c3e50;">{f"{pos_type} @ {entry_price}" if pos_type != "NONE" else "NONE"}</span>
                        </div>
                    </div>

                    <!-- Tier 2: Trade Targets -->
                    <div style="display: flex; gap: 15px; width: 100%;">
                        <div style="flex: 1; min-width: 0; background-color: #fff5f5; border: 1px solid #ffe3e3; border-radius: 8px; padding: 12px; text-align: center;">
                            <span style="display: block; font-size: 10px; color: #e74c3c; text-transform: uppercase;">SL</span>
                            <span style="font-size: 15px; font-weight: 700; color: #e74c3c;">{sl}</span>
                        </div>
                        <div style="flex: 1; min-width: 0; background-color: #f2fdf5; border: 1px solid #dcfce7; border-radius: 8px; padding: 12px; text-align: center;">
                            <span style="display: block; font-size: 10px; color: #27ae60; text-transform: uppercase;">TP</span>
                            <span style="font-size: 15px; font-weight: 700; color: #27ae60;">{tp}</span>
                        </div>
                        <div style="flex: 1; min-width: 0; background-color: #f0f7ff; border: 1px solid #e0efff; border-radius: 8px; padding: 12px; text-align: center;">
                            <span style="display: block; font-size: 10px; color: #3498db; text-transform: uppercase;">TP/SL</span>
                            <span style="font-size: 15px; font-weight: 700; color: #3498db;">{tpsl_ratio}</span>
                        </div>
                    </div>

                    <!-- Tier 3: Prediction Outlook -->
                    <div style="margin-top: 15px; background-color: #fcfaff; border: 1px solid #efe5ff; border-radius: 8px; padding: 10px; text-align: center;">
                        <span style="display: block; font-size: 10px; color: #8e44ad; text-transform: uppercase; letter-spacing: 1px;">Prediction Outlook (Horizon)</span>
                        <span style="font-size: 16px; font-weight: 700; color: #8e44ad;">{horizon} DAYS</span>
                    </div>
                </div>

                <!-- Reasoning Section (Mandarin) -->
                <div style="background-color: #e8f4fd; padding: 20px; border-radius: 8px; border-left: 6px solid #3498db; margin-bottom: 30px;">
                    <h3 style="margin-top: 0; color: #2980b9; font-size: 18px;">💡 Reasoning</h3>
                    <p style="font-size: 16px; margin-bottom: 0; color: #34495e;">{reasoning_zh}</p>
                </div>

                <!-- Visual Charts -->
                {img_html}

                <!-- Technical Log (Accordion-style implied) -->
                <div style="margin-top: 40px; border-top: 1px solid #eee; padding-top: 15px;">
                    <p style="font-size: 12px; color: #95a5a6; text-transform: uppercase;">Full Technical Payload:</p>
                    <pre style="background: #272822; color: #c5c8c6; padding: 15px; border-radius: 5px; font-size: 11px; overflow-x: auto; line-height: 1.4;"><code>{formatted_json}</code></pre>
                </div>

                <p style="text-align: center; color: #bdc3c7; font-size: 11px; margin-top: 30px;">
                    This is an automated notification from your <strong>Crypto System</strong>.
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
        msg.attach(MIMEText(body, 'html', 'utf-8'))

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
