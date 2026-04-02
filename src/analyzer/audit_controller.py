import os
from datetime import datetime, timedelta, timezone
from typing import Dict, Any

from src.infrastructure.binance.client import BinanceFuturesClient
from src.analyzer.audit_assembler import AuditAssembler, AuditReviewConfig
from src.utils.json_utils import load_json
from src.utils.datetime_utils import parse_iso_to_utc

class AuditController:
    """Orchestrates the end-to-end audit review flow for a single session."""
    def __init__(self, config_dict: Dict[str, Any], logger):
        self.config = config_dict
        self.logger = logger
        self.audit_config = AuditReviewConfig.from_dict(config_dict)
        self.assembler = AuditAssembler(config=self.audit_config)

    def run_manual_audit(self, file_path: str) -> Dict[str, Any]:
        """Loads a session from disk, fetches market data, and returns an audit report."""
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"Strategy file not found: {file_path}")

        session = load_json(file_path)
        obs = session.get("observation", {})
        symbol = obs.get("symbol")
        ts_start_str = obs.get("timestamp")
        
        if not symbol or not ts_start_str:
            raise ValueError("Malformed session JSON: missing symbol or timestamp.")

        dt_start = parse_iso_to_utc(ts_start_str)
        limit_order = session.get("final_decision", {}).get("limit_order", {})
        window_hours = float(limit_order.get("holding_time_hours", 24))
        dt_fetch_end = min(dt_start + timedelta(hours=window_hours), datetime.now(timezone.utc))

        self.logger.info(f"Auditing {symbol} from {ts_start_str} to {dt_fetch_end.isoformat()}")

        client = BinanceFuturesClient()
        try:
            # 1. Fetch Market Data
            interval = self.audit_config.micro_interval
            interval_map = {"1m": 60, "3m": 180, "5m": 300, "15m": 900, "1h": 3600}
            sec = interval_map.get(interval, 60)
            limit = int((dt_fetch_end - dt_start).total_seconds() / sec) + 10

            klines = client.fetch_historical_klines(
                symbol=symbol,
                interval=interval,
                limit=limit,
                startTime=int(dt_start.timestamp() * 1000),
                endTime=int(dt_fetch_end.timestamp() * 1000)
            )

            if not klines:
                raise RuntimeError("No market data found for the requested audit window.")

            # 2. Execute Deterministic Audit
            price_dynamics = obs.get("quantitative_metrics", {}).get("price_dynamics", {})
            atr_t0 = float(price_dynamics.get("atr_macro") or 0)
            target_entry = float(limit_order.get("entry") or klines[0][1])

            outcome = self.assembler.calculate_outcome(
                klines=klines,
                entry_price=target_entry,
                strategy=session,
                atr_macro_t0=atr_t0,
                atr_macro_t1=atr_t0,
                interval_hours=sec/3600.0
            )

            report = self.assembler.review(session, outcome)
            return {"outcome": outcome, "report": report, "symbol": symbol, "session": session}

        finally:
            client.close()

    def save_report(self, audit_result: Dict[str, Any]) -> str:
        """
        Persists the audit review to a standardized JSON file.
        Returns the absolute path to the saved report.
        """
        symbol = audit_result["symbol"]
        report = audit_result["report"]
        outcome = audit_result["outcome"]
        session = audit_result["session"]
        
        # Build the final audit bundle
        bundle = {
            "strategy_session": session,
            "market_outcome": outcome,
            "audit_findings": report,
            "audit_timestamp": datetime.now(timezone.utc).isoformat()
        }
        
        # Resolve paths via project standards
        from src.utils.pipeline_utils import resolve_data_root
        from src.utils.path_utils import resolve_project_root
        from src.utils.json_utils import save_json
        
        # Use 'once' as default data root for audit context if not provided
        data_root = resolve_data_root("once")
        output_dir = os.path.join(resolve_project_root(), data_root, "audits")
        
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{symbol}_audit_{ts}.json"
        path = os.path.join(output_dir, filename)
        
        if save_json(bundle, path):
            self.logger.info(f"Audit: Report persisted to {path}")
            return path
        else:
            raise RuntimeError(f"Audit: Failed to save report to {path}")
