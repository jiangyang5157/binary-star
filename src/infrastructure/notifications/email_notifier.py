import os
import json
import logging
from datetime import datetime, timezone
from typing import Dict, Any, Optional
import yaml
from src.utils.path_utils import find_project_root
from src.utils.datetime_utils import to_html_display, format_timestamp_for_filename

from .base_notifier import (
    NotificationConfig,
    BaseEmailTemplate,
    EmailDispatcher
)

from src.dashboard.session_html_renderer import SessionRenderer

from src.utils.logger_utils import setup_logger
logger = setup_logger(__name__)

class AlertEmailTemplate(BaseEmailTemplate):
    """
    Handles the generation of professional HTML templates for System Critical Alerts.
    Used for circuit breaker triggers, API failures, or resource depletion.
    """
    @staticmethod
    def render(alert_name: str, symbol: str, error_message: str, metadata: Optional[Dict[str, Any]] = None) -> str:
        """
        Renders a mission-critical alert into a clear HTML report.
        """
        display_time = to_html_display(datetime.now(timezone.utc).isoformat())
        
        return f"""
        <html>
        <head>{AlertEmailTemplate.get_styles()}</head>
        <body>
            <div class="container" style="border-top: 6px solid #ef4444;">
                <div style="text-align: center; margin-bottom: 35px; border-bottom: 2px solid #f1f5f9; padding-bottom: 25px;">
                    <div style="display: inline-block; padding: 6px 14px; border-radius: 50px; background-color: #ef444415; color: #ef4444; font-weight: 700; font-size: 13px; margin-bottom: 12px; border: 1px solid #ef444430;">
                        🚨 SYSTEM ALERT
                    </div>
                    <h1 style="color: #0f172a; margin: 0; font-size: 32px; letter-spacing: -0.025em;">{alert_name}</h1>
                    <p style="color: #64748b; margin-top: 8px; font-size: 14px; font-weight: 500;">
                        Target: {symbol} | Detected: {display_time}
                    </p>
                </div>

                <!-- ALERT CONTENT -->
                <div style="background-color: #fef2f2; padding: 25px; border-radius: 12px; border: 1px solid #fee2e2; margin-bottom: 35px;">
                    <h3 style="margin-top: 0; color: #b91c1c; font-size: 18px; margin-bottom: 15px;">🛑 Circuit Breaker Triggered</h3>
                    <p style="font-size: 15px; line-height: 1.7; color: #991b1b; font-weight: 600; margin-bottom: 0;">
                        {error_message}
                    </p>
                </div>

                <!-- METADATA BOX -->
                {f'''
                <div style="background-color: #f8fafc; padding: 20px; border-radius: 12px; border: 1px solid #e2e8f0;">
                    <h4 style="margin-top: 0; color: #475569; font-size: 13px; margin-bottom: 12px; text-transform: uppercase;">📊 Audit Context</h4>
                    <pre style="font-size: 12px; color: #334155; line-height: 1.5; margin: 0; white-space: pre-wrap;"><code>{json.dumps(metadata, indent=2, ensure_ascii=False)}</code></pre>
                </div>
                ''' if metadata else ""}

                <div style="margin-top: 40px; border-top: 1px solid #e2e8f0; padding-top: 25px; text-align: center; color: #94a3b8; font-size: 11px;">
                    System automated notification | AG-7 Circuit Breaker Protocols Active
                </div>
            </div>
        </body>
        </html>
        """

class SessionNotifier:
    """
    High-level facade for dispatching trading strategy alerts.
    Orchestrates template rendering and email dispatching.
    """
    
    def __init__(self, data_root: str):
        self.config = NotificationConfig.from_env()
        self.dispatcher = EmailDispatcher(self.config)
        self.data_root = data_root
        
        # Load both configurations to maintain strict parameter isolation
        self.global_cfg = self._load_config("global_config.yaml")
        self.strategy_cfg = self._load_config("strategy_config.yaml")
        
        # 1. Source global system settings (Notification Threshold)
        bs_cfg = self.global_cfg.get('llm', {}).get('binary_star', {})
        self.confidence_threshold = int(bs_cfg.get('session_confidence_threshold', 60))
        
        # 2. Source strategy-specific physics
        # Sourced from binary_star -> session node in strategy_config.yaml

    def _load_config(self, filename: str) -> Dict[str, Any]:
        """Loads a YAML configuration file from the standardized config directory."""
        try:
            cfg_path = os.path.join(find_project_root(), "config", filename)
            if os.path.exists(cfg_path):
                with open(cfg_path, 'r') as f:
                    return yaml.safe_load(f)
        except Exception as e:
            logger.error(f"Failed to load {filename}: {e}")
        return {}

    def _load_global_config(self) -> Dict[str, Any]:
        # Deprecated: usage replaced by generic _load_config
        return self._load_config("global_config.yaml")

    def _get_timestamp_suffix(self, obs: Dict[str, Any]) -> str:
        """
        Derives a filename-friendly timestamp from market observation data.
        Uses standardized formatting (no 'Z').
        """
        market_ts = obs.get("observed_at", '')
        if not market_ts:
            return datetime.now().strftime("%Y%m%d_%H%M%S")
            
        return format_timestamp_for_filename(market_ts)

    @property
    def enabled(self) -> bool:
        return self.config.enabled

    def notify_session(self, symbol: str, session_data: Dict[str, Any], save_local: bool = False, dispatch_email: bool = True) -> bool:
        """
        Parses strategy result and dispatches an actionable email alert.
        """
        # Always generate HTML for potential preview even if email is disabled
        html_body = SessionRenderer.render(session_data or {})
        
        # Collect Visual Attachments
        obs = (session_data or {}).get("observation") or {}
        assets = obs.get("visual_context") or {}
        attachments = {
            "macro_snapshot": str(assets.get("macro_snapshot") or ""),
            "micro_snapshot": str(assets.get("micro_snapshot") or "")
        }

        # 1. Local Preview (Useful for debugging/UI verification)
        if save_local:
            ts_suffix = self._get_timestamp_suffix(obs)
            self.save_html_preview(f"{symbol}_session_{ts_suffix}.html", html_body, attachments)

        # Dispatch Check: Only send if BOTH are true
        if not self.enabled or not dispatch_email: return False

        final_decision = (session_data or {}).get("final_decision") or {}
        confidence = final_decision.get("confidence_score", 0)
        
        # Only notify if confidence >= threshold
        if confidence < self.confidence_threshold:
            logger.info(f"Notifier: Confidence too low ({confidence}% < {self.confidence_threshold}%). Skipping dispatch.")
            return False

        opinion = final_decision.get("opinion") or "NEUTRAL"

        # Only notify if opinion is BULLISH / BEARISH
        if opinion.upper() not in ["BULLISH", "BEARISH"]:
            logger.info(f"Notifier: Opinion is {opinion}. Skipping dispatch (only BULLISH / BEARISH allowed).")
            return False
            
        icons = {"BULLISH": "🟢", "BEARISH": "🔴", "NEUTRAL": "⏸️"}
        indicator = icons.get(opinion.upper(), '⚡')
        subject = f"{indicator} Signal | {symbol} | {opinion.upper()} ({confidence}%)"
        
        # 2. Dispatch Email
        try:
            logger.info(f"Notifier: Dispatching alert: {subject}")
            return self.dispatcher.dispatch(subject, html_body, attachments)
        except Exception as e:
            logger.error(f"Notifier: Failed to dispatch strategy notification: {e}")
            return False

    def notify_market_recon(self, symbol: str, session_data: Dict[str, Any], save_local: bool = True, dispatch_email: bool = False):
        """
        Specialized notification for independent market reconnaissance audits.
        Ensures clear nomenclature and skips signal-specific logic filters.
        """
        html_body = SessionRenderer.render(session_data or {})
        obs = (session_data or {}).get("observation") or {}
        assets = obs.get("visual_context") or {}
        
        # Collect context snapshots
        attachments = {
            "macro_snapshot": str(assets.get("macro_snapshot") or ""),
            "micro_snapshot": str(assets.get("micro_snapshot") or "")
        }

        # Local Preview
        if save_local:
            ts_suffix = self._get_timestamp_suffix(obs)
            self.save_html_preview(f"{symbol}_market_{ts_suffix}.html", html_body, attachments)

        if not self.enabled or not dispatch_email: return False
        
        subject = f"🔍 Market Audit | {symbol} | TOPOGRAPHY_RECON"
        try:
            logger.info(f"Notifier: Dispatching market audit: {subject}")
            return self.dispatcher.dispatch(subject, html_body, attachments)
        except Exception as e:
            logger.error(f"Notifier: Failed to dispatch market audit: {e}")
            return False

    def save_html_preview(self, filename: str, html_body: str, attachments: Optional[Dict[str, str]] = None) -> Optional[str]:
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
            
            file_path = os.path.join(output_dir, filename)
            
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(preview_html)
            
            logger.info(f"Notifier: HTML preview saved to {file_path}")
            return file_path
        except Exception as e:
            logger.error(f"Notifier: Failed to save HTML preview: {e}")
            return None


    def notify_alert(self, alert_name: str, symbol: str, error_message: str, metadata: Optional[Dict[str, Any]] = None) -> bool:
        """
        Dispatches a high-priority system alert email.
        Used for catastrophic failures or circuit breaker triggers.
        """
        html_body = AlertEmailTemplate.render(alert_name, symbol, error_message, metadata)
        subject = f"🛑 {alert_name} | {symbol}"
        
        logger.error(f"Notifier: DISPATCHING CRITICAL ALERT: {subject}")
        
        try:
            return self.dispatcher.dispatch(subject, html_body)
        except Exception as e:
            logger.error(f"Notifier: Failed to dispatch critical alert: {e}")
            return False