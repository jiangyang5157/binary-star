import smtplib
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.image import MIMEImage
import os
import json
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

    def _get_prediction_header_html(self, symbol, prediction, local_time_str, action_color, action_icon):
        """
        Shared header for both prediction and review emails.
        """
        opinion = str(prediction.get('opinion', 'NEUTRAL')).upper()
        confidence = prediction.get('confidence', 0)
        action = str(prediction.get('action', 'WAIT')).upper()
        
        opinion_colors = {"BULLISH": "#27ae60", "BEARISH": "#e74c3c", "NEUTRAL": "#95a5a6"}
        opinion_icons = {"BULLISH": "📈", "BEARISH": "📉", "NEUTRAL": "↔️"}
        opinion_color = opinion_colors.get(opinion, "#f39c12")
        opinion_icon = opinion_icons.get(opinion, "💡")
        
        return f"""
                <div style="text-align: center; margin-bottom: 30px;">
                    <div style="display: inline-block; padding: 8px 16px; border-radius: 50px; background-color: {opinion_color}15; color: {opinion_color}; font-weight: bold; font-size: 14px; margin-bottom: 10px; border: 1px solid {opinion_color}30;">
                        {opinion_icon} Market {opinion}
                    </div>
                    <h1 style="color: {action_color}; margin: 0; font-size: 32px; letter-spacing: 1px;">{action_icon} {action} {symbol}</h1>
                    <p style="color: #7f8c8d; margin-top: 8px; font-size: 14px;">Signal Confidence: <span style="color: {action_color}; font-weight: 700;">{confidence}%</span> | Detected at: <span style="color: #34495e; font-weight: 600;">{local_time_str}</span></p>
                </div>
        """

    def _get_review_dashboard_html(self, symbol, prediction, local_time_str, score, tp_sl_result, mae_stress, time_elapsed_str):
        """
        Consolidated review results dashboard with mirrored prediction header style and Chinese labels.
        """
        action = str(prediction.get('action', 'WAIT')).upper()
        confidence = prediction.get('confidence', 0)
        
        # Color logic for Score
        if score >= 80: score_color = "#27ae60"
        elif score >= 50: score_color = "#f39c12"
        else: score_color = "#e74c3c"
        
        # Color logic for Outcome
        result_colors = {"TP_HIT": "#27ae60", "SL_HIT": "#e74c3c", "NEITHER": "#f39c12", "N/A": "#95a5a6"}
        result_color = result_colors.get(tp_sl_result, "#95a5a6")
        
        # Color logic for MAE Stress (Lower is Better)
        mae_color = "#334155" # Default
        try:
            val = float(mae_stress.replace('%', ''))
            if val <= 5.0: mae_color = "#27ae60"
            elif val <= 15.0: mae_color = "#f39c12"
            else: mae_color = "#e74c3c"
        except: pass

        return f"""
                <div style="background-color: #f8fafc; border: 1px solid #e2e8f0; border-radius: 12px; padding: 35px; margin-bottom: 30px; text-align: center;">
                    <!-- Mirrored Header Style -->
                    <div style="margin-bottom: 30px;">
                        <div style="display: inline-block; padding: 8px 16px; border-radius: 50px; background-color: #8e44ad15; color: #8e44ad; font-weight: bold; font-size: 14px; margin-bottom: 10px; border: 1px solid #8e44ad30;">
                            📋 Review Signal
                        </div>
                        <h1 style="color: #1e293b; margin: 0; font-size: 32px; letter-spacing: 1px;">{action} {symbol}</h1>
                        <p style="color: #7f8c8d; margin-top: 8px; font-size: 14px;">Signal Confidence: <span style="color: #334155; font-weight: 700;">{confidence}%</span> | Detected at: <span style="color: #34495e; font-weight: 600;">{local_time_str}</span></p>
                    </div>

                    <!-- Horizontal Stats Row (Adaptive Spacing & Chinese Labels) -->
                    <div style="display: flex; justify-content: space-between; align-items: center; background: #ffffff; border-radius: 12px; padding: 25px; border: 1px solid #f1f5f9; box-shadow: 0 1px 3px rgba(0,0,0,0.02); margin: 0 10px;">
                        <div style="flex: 1; padding: 0 10px;">
                            <span style="display: block; font-size: 11px; color: #94a3b8; text-transform: uppercase; font-weight: 700; margin-bottom: 6px;">持续时间</span>
                            <span style="font-size: 15px; font-weight: 700; color: #334155; white-space: nowrap;">{time_elapsed_str}</span>
                        </div>
                        <div style="width: 1px; height: 35px; background-color: #f1f5f9;"></div>
                        <div style="flex: 1; padding: 0 10px;">
                            <span style="display: block; font-size: 11px; color: #94a3b8; text-transform: uppercase; font-weight: 700; margin-bottom: 6px;">操作结果</span>
                            <span style="font-size: 15px; font-weight: 800; color: {result_color}; white-space: nowrap;">{tp_sl_result}</span>
                        </div>
                        <div style="width: 1px; height: 35px; background-color: #f1f5f9;"></div>
                        <div style="flex: 1; padding: 0 10px;">
                            <span style="display: block; font-size: 11px; color: #94a3b8; text-transform: uppercase; font-weight: 700; margin-bottom: 6px;">预测评分</span>
                            <span style="font-size: 15px; font-weight: 800; color: {score_color};">{score}</span>
                        </div>
                        <div style="width: 1px; height: 35px; background-color: #f1f5f9;"></div>
                        <div style="flex: 1; padding: 0 10px;">
                            <span style="display: block; font-size: 11px; color: #94a3b8; text-transform: uppercase; font-weight: 700; margin-bottom: 6px;">环境压力</span>
                            <span style="font-size: 15px; font-weight: 700; color: {mae_color}; white-space: nowrap;">{mae_stress}</span>
                        </div>
                    </div>
                </div>
        """

    def _get_prediction_ui_html(self, symbol, prediction, local_time_str, action_color, action_icon, confidence):
        """
        Generate the standardized UI for a prediction summary (Single-row flex layout).
        """
        action = str(prediction.get('action', 'WAIT')).upper()
        opinion = str(prediction.get('opinion', 'NEUTRAL')).upper()
        pos_context = prediction.get('position_context', {})
        pos_type = str(pos_context.get('position_type', 'NONE')).upper()
        entry_price = pos_context.get('entry_price')
        current_price = prediction.get('current_price', 'N/A')
        tp = prediction.get('take_profit', 'N/A')
        sl = prediction.get('stop_loss', 'N/A')
        horizon = prediction.get('config_context', {}).get('prediction_horizon_days', 'N/A')
        
        reasoning_zh = prediction.get('reasoning_zh')
        if not reasoning_zh:
            reasoning_zh = prediction.get('content', {}).get('reasoning_zh', 'N/A')

        tpsl_ratio = "N/A"
        try:
            base_price = float(entry_price) if entry_price is not None else float(current_price)
            tp_f = float(tp); sl_f = float(sl)
            is_long = action == "LONG" or opinion == "BULLISH"
            is_short = action == "SHORT" or opinion == "BEARISH"
            if is_long and base_price > sl_f:
                tpsl_ratio = f"{(tp_f - base_price) / (base_price - sl_f):.2f}"
            elif is_short and sl_f > base_price:
                tpsl_ratio = f"{(base_price - tp_f) / (sl_f - base_price):.2f}"
        except: pass

        return f"""
                <div style="margin-bottom: 25px;">
                    <!-- Single-row Target Summary (Mirrored Dashboard Style) -->
                    <div style="display: flex; justify-content: space-between; align-items: center; background-color: #ffffff; border: 1px solid #f1f5f9; border-radius: 12px; padding: 25px; margin-bottom: 25px; box-shadow: 0 1px 3px rgba(0,0,0,0.02);">
                        <div style="text-align: center; flex: 1; padding: 0 10px;">
                            <span style="display: block; font-size: 11px; color: #94a3b8; text-transform: uppercase; font-weight: 700; margin-bottom: 6px;">Market Price</span>
                            <span style="font-size: 15px; font-weight: 700; color: #334155;">{current_price}</span>
                        </div>
                        <div style="width: 1px; height: 35px; background-color: #f1f5f9;"></div>
                        <div style="text-align: center; flex: 1; padding: 0 10px;">
                            <span style="display: block; font-size: 11px; color: #94a3b8; text-transform: uppercase; font-weight: 700; margin-bottom: 6px;">Position</span>
                            <span style="font-size: 15px; font-weight: 700; color: #334155;">{f"{pos_type}@{entry_price}" if pos_type != "NONE" else "NONE"}</span>
                        </div>
                        <div style="width: 1px; height: 35px; background-color: #f1f5f9;"></div>
                        <div style="text-align: center; flex: 1; padding: 0 10px;">
                            <span style="display: block; font-size: 11px; color: #ef4444; text-transform: uppercase; font-weight: 700; margin-bottom: 6px;">Stop Loss</span>
                            <span style="font-size: 15px; font-weight: 700; color: #ef4444;">{sl}</span>
                        </div>
                        <div style="width: 1px; height: 35px; background-color: #f1f5f9;"></div>
                        <div style="text-align: center; flex: 1; padding: 0 10px;">
                            <span style="display: block; font-size: 11px; color: #10b981; text-transform: uppercase; font-weight: 700; margin-bottom: 6px;">Take Profit</span>
                            <span style="font-size: 15px; font-weight: 700; color: #10b981;">{tp}</span>
                        </div>
                        <div style="width: 1px; height: 35px; background-color: #f1f5f9;"></div>
                        <div style="text-align: center; flex: 1; padding: 0 10px;">
                            <span style="display: block; font-size: 11px; color: #3b82f6; text-transform: uppercase; font-weight: 700; margin-bottom: 6px;">TP/SL Ratio</span>
                            <span style="font-size: 15px; font-weight: 700; color: #3b82f6;">{tpsl_ratio}</span>
                        </div>
                        <div style="width: 1px; height: 35px; background-color: #f1f5f9;"></div>
                        <div style="text-align: center; flex: 1.2; padding: 0 10px;">
                            <span style="display: block; font-size: 11px; color: #8e44ad; text-transform: uppercase; font-weight: 700; margin-bottom: 6px;">Outlook</span>
                            <span style="font-size: 15px; font-weight: 700; color: #8e44ad;">{horizon} DAYS</span>
                        </div>
                    </div>

                    <div style="background-color: #e8f4fd; padding: 20px; border-radius: 8px; border-left: 6px solid #3498db; margin-bottom: 30px;">
                        <h3 style="margin-top: 0; color: #2980b9; font-size: 18px;">💡 Reasoning</h3>
                        <p style="font-size: 16px; margin-bottom: 0; color: #34495e;">{reasoning_zh}</p>
                    </div>
                </div>
        """

    def send_prediction_alert(self, symbol, prediction, chart_paths=None):
        if not self.enabled or not self.recipient or not self.recipient_app_password:
            return False

        action = str(prediction.get('action', 'WAIT')).upper()
        local_time_str = "N/A"
        try:
            timestamp_str = prediction.get('timestamp')
            if timestamp_str:
                utc_dt = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
                local_dt = utc_dt.astimezone(ZoneInfo(self.timezone))
                local_time_str = local_dt.strftime(f"%Y-%m-%d %H:%M:%S {self.timezone}")
        except: pass
        
        action_colors = {"LONG": "#27ae60", "SHORT": "#e74c3c", "HOLD": "#3498db", "WAIT": "#95a5a6", "CLOSE": "#e67e22"}
        action_icons = {"LONG": "🚀", "SHORT": "🐻", "HOLD": "💎", "WAIT": "⏳", "CLOSE": "🚪"}
        action_color = action_colors.get(action, "#f39c12")
        action_icon = action_icons.get(action, "🔔")
        
        opinion = str(prediction.get('opinion', 'NEUTRAL')).upper()
        confidence = prediction.get('confidence', 0)
        subject = f"Crypto: {symbol} | {local_time_str} | {opinion} ({confidence}% confidence) | {action}"
        formatted_json = json.dumps(prediction, indent=4, ensure_ascii=False)

        prediction_header_html = self._get_prediction_header_html(symbol, prediction, local_time_str, action_color, action_icon)
        prediction_ui = self._get_prediction_ui_html(symbol, prediction, local_time_str, action_color, action_icon, confidence)

        img_html = ""
        if chart_paths:
            img_html = "<div style='margin-top: 20px;'>"
            for i, path in enumerate(chart_paths):
                if os.path.exists(path):
                    cid = f"image_{i}"
                    img_html += f"""
                    <div style='margin-bottom: 25px; text-align: center;'>
                        <h4 style='color: #64748b; margin-bottom: 10px; font-size: 12px; text-transform: uppercase;'>📊 {'Macro Chart' if i == 0 else 'Micro Chart'}</h4>
                        <img src='cid:{cid}' style='max-width: 100%; border: 1px solid #e2e8f0; border-radius: 8px;'>
                    </div>"""
            img_html += "</div>"

        body = f"""
        <html><body style="font-family: 'Segoe UI', Arial, sans-serif; color: #1e293b; background: #f8fafc; padding: 20px;">
            <div style="max-width: 800px; margin: 0 auto; background: #ffffff; padding: 30px; border-radius: 12px; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.1); border: 1px solid #e2e8f0;">
                {prediction_header_html}
                {prediction_ui}
                {img_html}

                <div style="margin-top: 40px; border-top: 1px solid #e2e8f0; padding-top: 20px; margin-bottom: 40px;">
                    <pre style="background: #0f172a; color: #cbd5e1; padding: 15px; border-radius: 6px; font-size: 11px; overflow-x: auto;"><code>{formatted_json}</code></pre>
                </div>
            </div>
        </body></html>
        """

        msg = MIMEMultipart('related')
        msg['From'] = self.recipient; msg['To'] = self.recipient; msg['Subject'] = subject
        msg.attach(MIMEText(body, 'html', 'utf-8'))
        if chart_paths:
            for i, path in enumerate(chart_paths):
                if os.path.exists(path):
                    with open(path, 'rb') as f:
                        image = MIMEImage(f.read())
                        image.add_header('Content-ID', f'<image_{i}>')
                        image.add_header('Content-Disposition', 'inline', filename=os.path.basename(path))
                        msg.attach(image)

        try:
            with smtplib.SMTP(self.smtp_server, self.smtp_port) as server:
                server.starttls(); server.login(self.recipient, self.recipient_app_password); server.send_message(msg)
            return True
        except: return False

    def send_review_alert(self, symbol, review_record, chart_paths=None):
        if not self.enabled or not self.recipient or not self.recipient_app_password:
            return False

        # Robust extraction supporting both legacy nested and flat formats
        prediction_root = review_record.get('prediction', {})
        prediction = prediction_root.get('content', prediction_root)
        
        analysis = review_record.get('analysis', review_record)
        outcome = review_record.get('actual_market_outcome', review_record)
        
        score = analysis.get('evaluation_score', review_record.get('evaluation_score', 0))
        tp_sl_result = str(analysis.get('tp_sl_result', review_record.get('tp_sl_result', 'N/A'))).upper()
        if tp_sl_result == "NA": tp_sl_result = "N/A"
        mae_stress = analysis.get('adversarial_audit', {}).get('mae_stress_level', 
                        review_record.get('mae_stress_level', 'N/A'))
        post_mortem_zh = analysis.get('prediction_post_mortem_zh', 
                        review_record.get('prediction_post_mortem_zh', 'N/A'))
        
        local_time_str = "N/A"; time_elapsed_str = "N/A"
        try:
            timestamp_str = prediction.get('timestamp')
            review_ts_str = review_record.get('review_timestamp')
            if timestamp_str:
                utc_dt = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
                local_dt = utc_dt.astimezone(ZoneInfo(self.timezone))
                local_time_str = local_dt.strftime(f"%Y-%m-%d %H:%M:%S {self.timezone}")
                if review_ts_str:
                    rev_utc_dt = datetime.fromisoformat(review_ts_str.replace('Z', '+00:00'))
                    delta = rev_utc_dt - utc_dt; hours = delta.total_seconds() / 3600
                    time_elapsed_str = f"{hours:.1f} hours" if hours < 24 else f"{delta.days} d, {int((delta.seconds)/3600)} h"
        except: pass

        action = str(prediction.get('action', 'WAIT')).upper()
        action_colors = {"LONG": "#27ae60", "SHORT": "#e74c3c", "HOLD": "#3498db", "WAIT": "#95a5a6", "CLOSE": "#e67e22"}
        action_icons = {"LONG": "🚀", "SHORT": "🐻", "HOLD": "💎", "WAIT": "⏳", "CLOSE": "🚪"}
        action_color = action_colors.get(action, "#f39c12")
        action_icon = action_icons.get(action, "🔔")
        confidence = prediction.get('confidence', 0)
        
        subject = f"Crypto: {symbol} | {local_time_str} | {score} ({mae_stress} stress) | {tp_sl_result}"
        formatted_json = json.dumps(review_record, indent=4, ensure_ascii=False)

        review_dashboard_html = self._get_review_dashboard_html(symbol, prediction, local_time_str, score, tp_sl_result, mae_stress, time_elapsed_str)
        prediction_header_html = self._get_prediction_header_html(symbol, prediction, local_time_str, action_color, action_icon)
        prediction_ui = self._get_prediction_ui_html(symbol, prediction, local_time_str, action_color, action_icon, confidence)
        
        body = f"""
        <html><body style="font-family: 'Segoe UI', Arial, sans-serif; color: #1e293b; background: #f1f5f9; padding: 20px;">
            <div style="max-width: 850px; margin: 0 auto; background: #ffffff; padding: 35px; border-radius: 16px; box-shadow: 0 10px 15px -3px rgba(0,0,0,0.1); border: 1px solid #e2e8f0;">
                {review_dashboard_html}

                <div style="background-color: #fffaf0; border-left: 5px solid #f6ad55; padding: 20px; border-radius: 8px; margin-bottom: 40px;">
                    <h3 style="margin-top: 0; color: #c05621; font-size: 16px;">🔍 Post-Mortem 分析</h3>
                    <p style="font-size: 15px; color: #744210; margin-bottom: 0; line-height: 1.7;">{post_mortem_zh}</p>
                </div>

                <div style="margin-top: 40px; border-top: 1px solid #e2e8f0; padding-top: 20px; margin-bottom: 40px;">
                    <pre style="background: #0f172a; color: #cbd5e1; padding: 15px; border-radius: 6px; font-size: 11px; overflow-x: auto;"><code>{formatted_json}</code></pre>
                </div>

                <div style="border-top: 2px dashed #e2e8f0; padding-top: 20px;">
                    {prediction_header_html}
                    {prediction_ui}
                </div>
            </div>
        </body></html>
        """

        msg = MIMEMultipart('related')
        msg['From'] = self.recipient; msg['To'] = self.recipient; msg['Subject'] = subject
        msg.attach(MIMEText(body, 'html', 'utf-8'))
        try:
            with smtplib.SMTP(self.smtp_server, self.smtp_port) as server:
                server.starttls(); server.login(self.recipient, self.recipient_app_password); server.send_message(msg)
            return True
        except: return False
