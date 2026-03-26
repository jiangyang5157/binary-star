#!/usr/bin/env python3
import os
import sys
import json
import argparse
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, List, Optional
from dotenv import load_dotenv

# Setup paths
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.infrastructure.binance.client import BinanceFuturesClient
from src.agent.reviewer_agent import ReviewerAgent
from src.agent.observer_agent import ObserverAgent
from src.utils.agent_utils import load_config
from src.utils.json_utils import load_json, save_json
from src.utils.logger_utils import setup_logger
from src.utils.datetime_utils import parse_iso_to_utc, sanitize_timestamp

# Initialize pipeline logger
logger = setup_logger("ReviewerOrchestrator")

class OutcomeCalculator:
    """
    Isolates the mathematical logic for auditing market performance.
    Determines TP/SL hits and MAE (Maximum Adverse Excursion).
    """
    @staticmethod
    def calculate(klines: List[List[Any]], entry_price: float, strategy: Dict[str, Any]) -> Dict[str, Any]:
        """Analyzes klines to determine the actual market outcome vs strategist hypothesis."""
        if not klines:
            return {}
        
        # Structure: [OpenTime, Open, High, Low, Close, Volume, CloseTime, ...]
        highs = [float(k[2]) for k in klines]
        lows = [float(k[3]) for k in klines]
        closes = [float(k[4]) for k in klines]
        
        max_price = max(highs)
        min_price = min(lows)
        final_close = closes[-1]
        
        result = {
            "entry_price_at_t0": entry_price,
            "highest_reached_price": max_price,
            "lowest_reached_price": min_price,
            "exit_price_at_t1": final_close,
            "total_price_change_pct": round(((final_close - entry_price) / entry_price) * 100, 2),
            "max_favorable_runup_pct": round(((max_price - entry_price) / entry_price) * 100, 2),
            "max_adverse_drawdown_pct": round(((min_price - entry_price) / entry_price) * 100, 2),
            "audit_duration_candles": len(klines),
            "trade_execution_metrics": None
        }
        
        opinion = strategy.get('opinion', '').upper()
        limit_order = strategy.get('limit_order') or {}
        target_entry = float(limit_order.get('entry', entry_price))
        tp = float(limit_order.get('take_profit', 0))
        sl = float(limit_order.get('stop_loss', 0))
        
        if opinion in ('BULLISH', 'BEARISH') and tp > 0 and sl > 0:
            entry_hit = False
            hit_result = "NEITHER"
            max_after = -float('inf')
            min_after = float('inf')
            
            for k in klines:
                high, low = float(k[2]), float(k[3])
                
                if not entry_hit:
                    if (opinion == 'BULLISH' and low <= target_entry) or \
                       (opinion == 'BEARISH' and high >= target_entry):
                        entry_hit = True
                
                if entry_hit:
                    max_after, min_after = max(max_after, high), min(min_after, low)
                    if hit_result == "NEITHER":
                        if opinion == 'BULLISH':
                            if low <= sl: hit_result = "SL_HIT"
                            elif high >= tp: hit_result = "TP_HIT"
                        else: # BEARISH
                            if high >= sl: hit_result = "SL_HIT"
                            elif low <= tp: hit_result = "TP_HIT"
            
            if entry_hit:
                sl_dist = abs(target_entry - sl)
                mae = max(0, target_entry - min_after) if opinion == 'BULLISH' else max(0, max_after - target_entry)
                stress = (mae / sl_dist * 100) if sl_dist > 0 else 0
                result["trade_execution_metrics"] = {"tp_sl_result": hit_result, "mae_stress_level": f"{round(stress, 1)}%"}
        
        return result

class ReviewerOrchestrator:
    """
    Manages the end-to-end review lifecycle: 
    Discovery -> Temporal Validation -> Outcome Retrieval -> AI Audit -> Archival.
    """
    def __init__(self, data_root: str = "data"):
        self.data_root = data_root
        self.config = load_config()
        load_dotenv()
        self.api_key = os.environ.get("GEMINI_API_KEY")
        self.reviewer = ReviewerAgent(self.config, api_key=self.api_key)
        self.fetcher = BinanceFuturesClient()
        self.observers = {}

    def run_review(self, target_file: Optional[str] = None, force: bool = False):
        """Main entry point for review execution."""
        try:
            if target_file:
                self.execute_single(target_file, force=force)
            else:
                self.execute_batch(force=force)
        finally:
            self.fetcher.close()

    def execute_single(self, filename: str, force: bool = False):
        """Processes a specific strategy file for review."""
        # 1. Resolve Path & Load JSON
        if os.path.isabs(filename) or "/" in filename:
            pred_path = filename
        else:
            pred_path = os.path.join(PROJECT_ROOT, self.data_root, "strategies", filename)

        if not os.path.exists(pred_path):
            logger.error(f"Strategy file not found: {pred_path}")
            return

        session = load_json(pred_path)
        if not session:
            logger.error(f"Failed to load strategy session: {pred_path}")
            return

        # 2. Extract Metadata for Naming
        obs = session.get("observation", {})
        symbol = obs.get("symbol", "UNKNOWN")
        raw_ts = obs.get("timestamp", "")
        
        # Format timestamp: 2026-03-25T11:02:32.148369Z -> 20260325_110232
        import re
        match = re.search(r"(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})", raw_ts)
        if match:
            ts_str = f"{match.group(1)}{match.group(2)}{match.group(3)}_{match.group(4)}{match.group(5)}{match.group(6)}"
        else:
            ts_str = datetime.now().strftime("%Y%m%d_%H%M%S")

        output_filename = f"{symbol}_reviewers_{ts_str}.json"
        review_path = os.path.join(PROJECT_ROOT, self.data_root, "reviewers", output_filename)
        os.makedirs(os.path.dirname(review_path), exist_ok=True)

        # 3. Process
        if os.path.exists(review_path) and not force:
            logger.info(f"Skipping {output_filename} - Review already exists.")
            return

        self._process_session(session, review_path, force=force)

    def execute_batch(self, force: bool = False):
        """Scans for all pending strategy files and reviews them."""
        strat_dir = os.path.join(PROJECT_ROOT, self.data_root, "strategies")
        if not os.path.isdir(strat_dir):
            logger.error(f"Strategy directory not found: {strat_dir}")
            return

        files = [f for f in os.listdir(strat_dir) if f.endswith(".json")]
        logger.info(f"Found {len(files)} potential strategies for review.")
        for f in files:
            self.execute_single(f, force=force)

    def _process_session(self, session: Dict[str, Any], output_path: str, force: bool):
        """Internal logic for reviewing a single session."""
        try:
            strategy = session.get("final_decision", session)
            symbol = session.get("observation", {}).get("symbol")
            ts_str = session.get('observation', {}).get('timestamp') or strategy.get('timestamp')
            
            if not symbol or not ts_str:
                logger.warning("Session missing symbol or timestamp. Skipping.")
                return

            dt_start = parse_iso_to_utc(ts_str)
            dt_now = datetime.now(timezone.utc)
            
            # Temporal Window Logic
            window_hours = self._calculate_review_window(strategy)
            dt_end = dt_start + timedelta(hours=window_hours)

            if dt_now < dt_end and not force:
                logger.info(f"Window not reached for {symbol} (Target: {dt_end}). Skipping.")
                return

            # Cap end time at now for fetching
            dt_fetch_end = min(dt_end, dt_now)
            logger.info(f"Auditing {symbol} from {dt_start} to {dt_fetch_end}...")

            # 1. Fetch & Calculate Outcome
            # Use dynamic interval mapping to calculate how many klines we need
            # This ensures we get the exact history from T0 (dt_start) to T1 (now)
            fetch_interval = self.reviewer.config.execution_timeframe_interval
            # Strict interval mapping for required history limit calculation
            interval_map = {
                "1m": 60, "3m": 180, "5m": 300, "15m": 900, "30m": 1800,
                "1h": 3600, "4h": 14400, "1d": 86400, "1w": 604800, "1M": 2592000
            }
            if fetch_interval not in interval_map:
                raise ValueError(f"CRITICAL: Unknown execution_timeframe_interval '{fetch_interval}' in config.")
                
            interval_seconds = interval_map[fetch_interval]
            duration_seconds = (dt_fetch_end - dt_start).total_seconds()
            required_limit = int(duration_seconds / interval_seconds) + 2 # +2 safety buffer
            target_limit = min(required_limit, 1500)

            klines = self.fetcher.fetch_historical_klines(
                symbol=symbol, 
                interval=fetch_interval, 
                limit=target_limit,
                startTime=int(dt_start.timestamp() * 1000),
                endTime=int(dt_fetch_end.timestamp() * 1000)
            )
            if not klines:
                logger.warning(f"No klines found for {symbol}. Skipping.")
                return

            outcome = OutcomeCalculator.calculate(klines, float(klines[0][1]), strategy)

            # 2. Multimedia & Visual Forensic Context
            if symbol not in self.observers:
                self.observers[symbol] = ObserverAgent(self.config, symbol, self.api_key)
            current_obs = self.observers[symbol].observe(timestamp=dt_fetch_end)

            t0_assets = session.get("observation", {}).get("visual_assets", {})
            t1_assets = current_obs.get("visual_assets", {})

            # Resolve absolute paths for all assets
            visual_context = {
                "t0_macro": self._resolve_abs_path(t0_assets.get("macro_snapshot")),
                "t0_micro": self._resolve_abs_path(t0_assets.get("micro_snapshot")),
                "t1_macro": self._resolve_abs_path(t1_assets.get("macro_snapshot")),
                "t1_micro": self._resolve_abs_path(t1_assets.get("micro_snapshot"))
            }

            # 3. AI Forensic Audit
            audit_result = self.reviewer.review(
                historical_strategy=session,
                actual_outcome=outcome,
                current_observation=current_obs,
                visual_context=visual_context
            )

            # 4. Persist
            final_record = {
                "audit_timestamp": dt_fetch_end.isoformat(),
                "strategy_session": session,
                "market_outcome": outcome,
                "audit_findings": audit_result
            }
            save_json(final_record, output_path)
            logger.info(f"Forensic audit archived: {output_path}")

        except Exception as e:
            logger.error(f"Failed to process session: {e}", exc_info=True)

    def _calculate_review_window(self, strategy: Dict[str, Any]) -> float:
        """Determines the review duration based on strategy opinion and micro/macro context."""
        opinion = strategy.get("opinion", "").upper()
        limit_order = strategy.get("limit_order") or {}
        
        # 1. Base Holding Time for Directional Orders
        holding_time = float(limit_order.get("holding_time_hours", 24))

        # 2. Extract context parameters directly from config
        obs_cfg = self.config['observer']
        micro_cfg = obs_cfg['micro_analysis_context']
        macro_cfg = obs_cfg['macro_analysis_context']

        # Get interval seconds from standard utility
        from src.utils.datetime_utils import get_interval_seconds
        micro_interval_sec = get_interval_seconds(micro_cfg['time_interval'])
        macro_interval_sec = get_interval_seconds(macro_cfg['time_interval'])

        # 3. Dynamic Threshold Calculation
        if opinion == "NEUTRAL":
            # Neutral Audit: Wait until the micro-context (the 'lens' the AI used) has fully passed.
            micro_lookback = int(micro_cfg['historical_lookback_candles'])
            return (micro_interval_sec * micro_lookback) / 3600
        
        # Directional Audit: Use strategy's suggested holding time, capped by macro lookback duration
        macro_lookback = int(macro_cfg['historical_lookback_candles'])
        max_macro_hours = (macro_interval_sec * macro_lookback) / 3600
        
        return min(holding_time, max_macro_hours)

    def _resolve_abs_path(self, path: Optional[str]) -> Optional[str]:
        """Resolves a relative path to an absolute project-root path."""
        if not path:
            return None
        if os.path.isabs(path):
            return path
        abs_p = os.path.join(PROJECT_ROOT, path)
        return abs_p if os.path.exists(abs_p) else None

def main():
    parser = argparse.ArgumentParser(description="Reviewer Orchestrator - Post-Mortem Audit Pipeline")
    parser.add_argument("--file", type=str, help="Specific strategy JSON to review")
    parser.add_argument("--data_root", type=str, default="data", help="Data root directory")
    parser.add_argument("--force", action="store_true", help="Bypass temporal checks")
    args = parser.parse_args()
    
    orchestrator = ReviewerOrchestrator(data_root=args.data_root)
    orchestrator.run_review(target_file=args.file, force=args.force)

if __name__ == "__main__":
    main()
