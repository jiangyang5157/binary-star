import os
import json
import logging
from typing import Dict, Any, Optional
from datetime import datetime, timezone, timedelta

from src.analyzer.audit_assembler import AuditAssembler, AuditReviewConfig
from src.infrastructure.binance.client import BinanceFuturesClient
from src.utils.pipeline_utils import get_file_hash
from src.utils.path_utils import resolve_project_root
from src.analyzer.market_observer import MarketObserver, MarketObserverConfig
from src.analyzer.chart_generator import ChartGenerator
from src.utils.datetime_utils import (
    parse_iso_to_utc, 
    get_interval_hours,
    to_iso_zulu,
    to_compact_timestamp,
    format_timestamp_for_filename
)

# Initialize standard hardened logger
logger = logging.getLogger(__name__)

class AuditController:
    """The Audit Orchestrator (v6.1).
    
    Coordinates forensic analysis by fetching historical outcomes, 
    triggering T1 visual capture, and assembling structural reports.
    
    Attributes:
        config: The global strategy configuration dictionary.
        data_root: The logical data repository (e.g., 'data/prod').
    """
    
    def __init__(self, config_dict: Dict[str, Any], data_root: str, logger: Optional[logging.Logger] = None):
        """Initializes the AuditController with required forensic components."""
        self.config = config_dict
        self.logger = logger or logging.getLogger(__name__)
        self.data_root = data_root
        
        # 1. Initialize Forensic Assembler
        review_cfg = AuditReviewConfig.from_dict(config_dict)
        self.assembler = AuditAssembler(review_cfg)
        
        # 2. Shared Infrastructure
        self.binance_client = BinanceFuturesClient()
        
        # 3. Visual Forensic Observer (T1)
        self.obs_config = MarketObserverConfig.from_dict(config_dict)
        self.chart_gen = ChartGenerator(
            output_dir=os.path.join(self.data_root, "klines"),
            up_color=self.obs_config.up_color,
            down_color=self.obs_config.down_color,
            bg_color=self.obs_config.bg_color,
            grid_color=self.obs_config.grid_color,
            poc_color=self.obs_config.poc_color,
            value_area_color=self.obs_config.value_area_color,
            liq_buy_color=self.obs_config.liq_buy_color,
            liq_sell_color=self.obs_config.liq_sell_color,
            current_price_color=self.obs_config.current_price_color,
            volume_profile_width_ratio=self.obs_config.volume_profile_width_ratio,
            volume_profile_smoothing_sigma=self.obs_config.volume_profile_smoothing_sigma,
            volume_profile_color=self.obs_config.volume_profile_color,
            volume_profile_alpha=self.obs_config.volume_profile_alpha,
            chart_main_panel_weight=self.obs_config.chart_main_panel_weight,
            chart_volume_panel_weight=self.obs_config.chart_volume_panel_weight,
            render_dpi=self.obs_config.render_dpi
        )
        
        default_symbol = config_dict['system']['default_symbol']
        self.observer = MarketObserver(
            config=self.obs_config,
            symbol=default_symbol,
            data_root=self.data_root,
            binance_client=self.binance_client,
            chart_generator=self.chart_gen
        )

    def is_already_audited(self, symbol: str, timestamp_compact: str) -> bool:
        """
        Deduplication check: Verify if the audit JSON already exists on disk.
        """
        output_dir = os.path.join(resolve_project_root(), self.data_root, "audits")
        filename = f"{symbol}_audit_{timestamp_compact}.json"
        return os.path.exists(os.path.join(output_dir, filename))

    def run_manual_audit(self, session_file_path: str, force: bool = False) -> Dict[str, Any]:
        """Performs a comprehensive forensic audit on a specific session.
        
        Args:
            session_file_path: Path to the target session JSON.
            force: If True, bypasses maturity checks (waiting for TP/SL or expiration).
            
        Returns:
            An audit result dictionary containing session, outcome, and report.
        """
        if not os.path.isabs(session_file_path):
            session_file_path = os.path.join(resolve_project_root(), session_file_path)
            
        with open(session_file_path, 'r', encoding='utf-8') as f:
            session = json.load(f)
            
        return self.audit_session_data(session, force=force)

    def audit_session_data(self, session: Dict[str, Any], force: bool = False, end_time: Optional[datetime] = None) -> Dict[str, Any]:
        """Forensic audit logic adapted for both file-based and in-memory replay flows.
        
        Args:
            session: The strategy/session dictionary.
            force: If True, bypasses maturity checks.
            end_time: Optional T1 boundary (historical audit time). Defaults to NOW.
        """
        obs = session.get("observation", {})
        symbol = obs.get("symbol", "UNKNOWN")
        t0_str = obs.get("observed_at")
        
        # Update Observer for the correct symbol
        self.observer.symbol = symbol
        
        # Robust timestamp parsing
        try:
            if "_" in t0_str and "-" not in t0_str:
                t0_dt = datetime.strptime(t0_str, "%Y%m%d_%H%M%S").replace(tzinfo=timezone.utc)
            else:
                t0_dt = parse_iso_to_utc(t0_str)
        except Exception as te:
            self.logger.error(f"Audit: Failed to parse session timestamp '{t0_str}': {te}")
            raise ValueError(f"Invalid timestamp format in session: {t0_str}")

        # v6.16: Strategic T1 Anchoring
        final_decision = session.get("final_decision", {})
        opinion = final_decision.get("opinion", "").upper()
        
        # If Neutral, we use the micro-context profile length (e.g. 15m * 192 = 48h) for forensic audit
        if opinion == "NEUTRAL":
            micro_ctx = self.config['analysis_window']['micro_context']
            interval_micro_hours = get_interval_hours(micro_ctx['time_interval'])
            lookback_candles = int(micro_ctx['lookback_candles'])
            expiry_dt = t0_dt + timedelta(hours=(interval_micro_hours * lookback_candles))
        else:
            params = final_decision.get("tactical_parameters", {})
            holding_hours = float(params.get("projected_holding_hours", 0) or 0)
            waiting_hours = float(params.get("projected_waiting_hours", 0) or 0)
            expiry_dt = t0_dt + timedelta(hours=(holding_hours + waiting_hours))
        
        now_dt = datetime.now(timezone.utc)
        max_boundary = min(expiry_dt, now_dt)
        
        self.logger.info(f"Audit: Reviewing {symbol} ({opinion}) from {t0_str} to Bound ({max_boundary.isoformat()})")
        
        try:
            # 1. Fetch Outcome Klines
            client = self.binance_client
            forensic_resolution = self.config['audit_review']['forensic_resolution']
            klines = []
            try:
                klines = client.fetch_historical_klines(
                    symbol=symbol,
                    interval=forensic_resolution,
                    limit=1000,
                    startTime=int(t0_dt.timestamp() * 1000),
                    endTime=int(max_boundary.timestamp() * 1000)
                )
            except Exception as ke:
                self.logger.warning(f"Audit: Could not fetch outcome klines: {ke}")

            # v6.17 early exit: If no market data is available, skip expensive visual-only audit.
            if not klines:
                raise ValueError("EMPTY_KLINES: No market data available for the forensic window.")

            # 2. Extract Data Suites
            metrics_t0 = obs.get("quantitative_metrics", {})
            dynamics_t0 = metrics_t0.get("price_dynamics", {})
            atr_proto = dynamics_t0.get("atr_macro", 0)
            ls_ratio_proto = metrics_t0.get("sentiment_signals", {}).get("ls_ratio_macro", 0)
            
            # 3. Initial Outcome Calculation
            interval_macro_hours = get_interval_hours(self.config['analysis_window']['macro_context']['time_interval'])
            
            outcome = self.assembler.calculate_outcome(
                klines=klines,
                entry_price=dynamics_t0.get("current_price", 0),
                strategy=session,
                atr_macro_t0=float(atr_proto),
                atr_macro_t1=float(atr_proto),
                long_short_ratio_macro_t0=float(ls_ratio_proto),
                long_short_ratio_macro_t1=float(ls_ratio_proto),
                interval_hours=interval_macro_hours,
                volume_profile=metrics_t0.get("volume_profile", {}).get("profile_data", [])
            )

            # 4. Final T1 Anchoring Logic
            res_type = outcome.get("tp_sl_result", "NEITHER")
            if res_type in ("TP_HIT", "SL_HIT"):
                hit_index = outcome.get("trade_execution_metrics", {}).get("actual_holding_candles", len(klines))
                t1_dt = datetime.fromtimestamp(klines[hit_index - 1][0] / 1000, tz=timezone.utc)
            else:
                t1_dt = expiry_dt if expiry_dt <= now_dt else now_dt

            # 5. --- PHYSICAL FORENSIC: T1 Visual Capture ---
            t1_observation = self.observer.observe(timestamp=t1_dt, persist=False)
            t1_assets = t1_observation.get("visual_context", {})

            # 6. Re-calculate outcome with correct T1 metrics
            metrics_t1 = t1_observation.get("quantitative_metrics", {})
            atr_t1 = metrics_t1.get("price_dynamics", {}).get("atr_macro", atr_proto)
            ls_ratio_t1 = metrics_t1.get("sentiment_signals", {}).get("ls_ratio_macro", ls_ratio_proto)
            
            outcome = self.assembler.calculate_outcome(
                klines=klines,
                entry_price=dynamics_t0.get("current_price", 0),
                strategy=session,
                atr_macro_t0=float(atr_proto),
                atr_macro_t1=float(atr_t1),
                long_short_ratio_macro_t0=float(ls_ratio_proto),
                long_short_ratio_macro_t1=float(ls_ratio_t1),
                interval_hours=interval_macro_hours,
                volume_profile=metrics_t1.get("volume_profile", {}).get("profile_data", [])
            )
            
            outcome["visual_context"] = {
                "t1_macro": t1_assets.get("macro_snapshot"),
                "t1_micro": t1_assets.get("micro_snapshot")
            }

            report = self.assembler.review(session, outcome)
            outcome["forensic_verdict"] = report.get("forensic_verdict", {})
            
            # Standard Bundle Return (v6.12 schema parity)
            return {
                "session": session,
                "market_outcome": outcome,
                "metadata": {
                    "config_hash": get_file_hash("config/strategy_config.yaml"),
                    "audit_at": to_iso_zulu(t1_dt)
                }
            }
            
        except Exception as e:
            if "SESSION_MATURING" not in str(e):
                self.logger.error(f"Audit: Forensic analysis failed for {symbol}: {e}", exc_info=True)
            raise

    def save_report(self, audit_result: Dict[str, Any]) -> str:
        """Standardized archival for forensic audit bundles."""
        # Extract metadata from the standard bundle (Unified schema)
        session = audit_result["session"]
        obs = session.get("observation", {})
        symbol = obs.get("symbol", "UNKNOWN")
        t0_str = obs.get("observed_at")
        
        # Consistent filename TS generation
        filename_ts = format_timestamp_for_filename(t0_str)
        
        output_dir = os.path.join(resolve_project_root(), self.data_root, "audits")
        os.makedirs(output_dir, exist_ok=True)
        
        filename = f"{symbol}_audit_{filename_ts}.json"
        output_file = os.path.join(output_dir, filename)
        
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(audit_result, f, indent=2, ensure_ascii=False)
            
        self.logger.info(f"Audit: Forensic report archived: {os.path.basename(output_file)}")
        return output_file
