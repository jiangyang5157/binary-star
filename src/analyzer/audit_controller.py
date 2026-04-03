import os
import json
import logging
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone, timedelta

from src.analyzer.audit_assembler import AuditAssembler, AuditReviewConfig
from src.infrastructure.binance.client import BinanceFuturesClient
from src.utils.pipeline_utils import get_file_hash, load_config
from src.utils.path_utils import resolve_project_root
from src.analyzer.market_observer import MarketObserver, MarketObserverConfig
from src.analyzer.chart_generator import ChartGenerator

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
    
    def __init__(self, config_dict: Dict[str, Any], logger: Optional[logging.Logger] = None, data_root: str = "data/once"):
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
            output_dir=os.path.join(resolve_project_root(), self.data_root, "klines")
        )
        self.observer = MarketObserver(
            config=self.obs_config,
            symbol="BTCUSDT", # Default placeholder
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
            
        Raises:
            Exception: If the session file cannot be processed or analysis fails.
        """
        if not os.path.isabs(session_file_path):
            session_file_path = os.path.join(resolve_project_root(), session_file_path)
            
        with open(session_file_path, 'r', encoding='utf-8') as f:
            session = json.load(f)
            
        obs = session.get("observation", {})
        symbol = obs.get("symbol", "BTCUSDT")
        t0_str = obs.get("timestamp")
        
        # Local Time Conversion (Helper to handle multiple formats)
        def parse_to_local(ts_str):
            if not ts_str: return "N/A"
            try:
                # 1. Try Compact format YYYYMMDD_HHMMSS
                if "_" in ts_str and "-" not in ts_str:
                    dt = datetime.strptime(ts_str, "%Y%m%d_%H%M%S").replace(tzinfo=timezone.utc)
                else:
                    # 2. Try ISO format
                    dt = datetime.fromisoformat(ts_str.replace('Z', '+00:00'))
                return dt.astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")
            except Exception as e:
                logger.warning(f"Notifier: Time parse failed for audit '{ts_str}': {e}")
                return ts_str
        
        # Update Observer for the correct symbol
        self.observer.symbol = symbol
        
        # Robust timestamp parsing (Handles both ISO and Compact formats)
        try:
            if "_" in t0_str and "-" not in t0_str:
                t0_dt = datetime.strptime(t0_str, "%Y%m%d_%H%M%S").replace(tzinfo=timezone.utc)
            else:
                from src.utils.datetime_utils import parse_iso_to_utc
                t0_dt = parse_iso_to_utc(t0_str)
        except Exception as te:
            self.logger.error(f"Audit: Failed to parse session timestamp '{t0_str}': {te}")
            raise ValueError(f"Invalid timestamp format in session: {t0_str}")

        t1_dt = datetime.now(timezone.utc)
        
        # v6.2 Eligibility Gateway: Intent Check
        final_decision = session.get("final_decision", {})
        opinion = final_decision.get("opinion", "").upper()
        
        # 1. NEUTRAL SHORT-CIRCUIT: Mark as recorded result with null findings
        if opinion == "NEUTRAL":
            self.logger.info(f"Audit: Neutral signal detected for {symbol}. Short-circuiting to null-findings.")
            # Use original session timestamp for consistent deduplication
            ts_compact = t0_str.replace("-", "").replace(":", "").replace("T", "_").split(".")[0].split("+")[0]
            if len(ts_compact) < 15: # Fallback if not standard format
                ts_compact = t1_dt.strftime("%Y%m%d_%H%M%S")

            return {
                "symbol": symbol,
                "session": session,
                "outcome": {
                    "tp_sl_result": "NEUTRAL", 
                    "market_outcome": "JUSTIFIED_SURRENDER",
                    "forensic_verdict": {
                        "is_justified_surrender": True, 
                        "is_catastrophic_miss": False
                    }
                },
                "report": None, # audit_findings is null
                "audit_timestamp_compact": t1_dt.strftime("%Y%m%d_%H%M%S"),
                "session_timestamp_compact": ts_compact, 
                "metadata": {"config_hash": get_file_hash("config/strategy_config.yaml")}
            }

        self.logger.info(f"Audit: Reviewing {symbol} from {t0_str} to NOW ({t1_dt.isoformat()})")
        
        try:
            # 4. --- PHYSICAL FORENSIC: T1 Visual Capture ---
            self.logger.info(f"Audit: Capturing T1 visual evidence (Macro/Micro) for {symbol}...")
            t1_observation = self.observer.observe(persist=False)
            t1_assets = t1_observation.get("visual_assets", {})

            # 5. Fetch Outcome Klines
            client = self.binance_client
            klines = []
            try:
                # v6.10: Replaced legacy execution_timeframe_interval with forensic_resolution
                forensic_resolution = self.config['audit_review']['forensic_resolution']
                klines = client.fetch_historical_klines(
                    symbol=symbol,
                    interval=forensic_resolution,
                    limit=1000,
                    startTime=int(t0_dt.timestamp() * 1000),
                    endTime=int(t1_dt.timestamp() * 1000)
                )
            except Exception as ke:
                self.logger.warning(f"Audit: Could not fetch outcome klines: {ke}. Proceeding with visual-only audit.")

            # 6. Assemble Forensic Outcome
            from src.utils.datetime_utils import get_interval_seconds
            
            metrics_t0 = obs.get("quantitative_metrics", {})
            dynamics_t0 = metrics_t0.get("price_dynamics", {})
            sentiment_t0 = metrics_t0.get("sentiment_signals", {})
            atr_proto = dynamics_t0.get("atr_macro", 0)
            long_short_ratio_proto = sentiment_t0.get("ls_ratio_macro", 0)
            
            # Fetch T1 Environment Metrics
            metrics_t1 = t1_observation.get("quantitative_metrics", {})
            atr_t1 = metrics_t1.get("price_dynamics", {}).get("atr_macro", atr_proto)
            long_short_ratio_t1 = metrics_t1.get("sentiment_signals", {}).get("ls_ratio_macro", long_short_ratio_proto)
            
            # Dynamic interval calculation (Ensures accuracy for non-1h timeframes)
            interval_macro_hours = get_interval_seconds(self.config['analysis_window']['macro_context']['time_interval']) / 3600.0
            
            outcome = self.assembler.calculate_outcome(
                klines=klines,
                entry_price=dynamics_t0.get("current_price", 0),
                strategy=session,
                atr_macro_t0=float(atr_proto),
                atr_macro_t1=float(atr_t1),
                long_short_ratio_macro_t0=float(long_short_ratio_proto),
                long_short_ratio_macro_t1=float(long_short_ratio_t1),
                interval_hours=interval_macro_hours
            )
            
            # Inject T1 visual paths into the outcome for notification engine
            outcome["visual_context"] = {
                "t1_macro": t1_assets.get("macro_snapshot"),
                "t1_micro": t1_assets.get("micro_snapshot")
            }

            # 7. Final Review Analysis
            # v6.2 Eligibility Gateway: Maturity Filter
            res_type = outcome.get("tp_sl_result", "NEITHER")
            holding_hours = float(final_decision.get("tactical_parameters", {}).get("holding_time_hours", 0))
            is_expired = t1_dt > (t0_dt + timedelta(hours=holding_hours))
            
            if not force and res_type == "NEITHER" and not is_expired:
                # Still in position and haven't reached holding time limit
                raise ValueError(f"SESSION_MATURING: {symbol} is still active (Result: NEITHER). Waiting for TP/SL or expiration (T0+{holding_hours}h).")

            report = self.assembler.review(session, outcome, t1_observation)
            
            # Merge forensic findings into outcome (v6.12 flattening)
            outcome["forensic_verdict"] = report.get("forensic_verdict", {})
            
            return {
                "symbol": symbol,
                "session": session,
                "outcome": outcome,
                "audit_timestamp_compact": t1_dt.strftime("%Y%m%d_%H%M%S"),
                "session_timestamp_compact": t0_str.replace("-", "").replace(":", "").replace("T", "_").split(".")[0].split("+")[0],
                "metadata": {
                    "config_hash": get_file_hash("config/strategy_config.yaml")
                }
            }
            
        except Exception as e:
            self.logger.error(f"Audit: Forensic analysis failed for {symbol}: {e}", exc_info=True)
            raise

    def save_report(self, audit_result: Dict[str, Any]) -> str:
        """Standardized archival for forensic audit bundles."""
        symbol = audit_result["symbol"]
        outcome = audit_result["outcome"]
        session = audit_result["session"]
        audit_ts = audit_result.get("audit_timestamp_compact") or datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # v6.1 Refined Structural Bundle
        # Use session_timestamp_compact if available for filename consistency
        filename_ts = audit_result.get("session_timestamp_compact") or audit_ts
        
        bundle = {
            "session": session,
            "market_outcome": outcome,
            "metadata": {
                "config_hash": get_file_hash("config/strategy_config.yaml")
            }
        }
        
        output_dir = os.path.join(resolve_project_root(), self.data_root, "audits")
        os.makedirs(output_dir, exist_ok=True)
        
        filename = f"{symbol}_audit_{filename_ts}.json"
        output_file = os.path.join(output_dir, filename)
        
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(bundle, f, indent=2, ensure_ascii=False)
            
        self.logger.info(f"Audit: Forensic report archived: {os.path.basename(output_file)}")
        return output_file
