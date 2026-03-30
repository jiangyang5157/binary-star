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
from src.utils.agent_utils import load_config, add_data_root_argument, resolve_data_root
from src.utils.json_utils import load_json, save_json
from src.utils.logger_utils import setup_logger
from src.utils.datetime_utils import parse_iso_to_utc, sanitize_timestamp
from src.infrastructure.notifications.email_notifier import StrategyNotifier

# Initialize pipeline logger
logger = setup_logger("ReviewerOrchestrator")

class OutcomeCalculator:
    """
    Isolates the mathematical logic for auditing market performance.
    Determines TP/SL hits and MAE (Maximum Adverse Excursion).
    """
    @staticmethod
    def calculate(klines: List[List[Any]], entry_price: float, strategy: Dict[str, Any], 
                  atr_macro_t0: float = 0, atr_macro_t1: float = 0, interval_hours: float = 0) -> Dict[str, Any]:
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
        
        # [Architect's Fix]: Decouple Time and Space.
        # Use max(T0, T1) for MAE stress evaluation to prevent "Lagging Indicator Paradox".
        max_atr = max(atr_macro_t0, atr_macro_t1)
        
        # 1. Market Context (T0 -> T1 Full Window Reference)
        missed_range = max_price - min_price
        rel_range = (missed_range / max_atr) if max_atr > 0 else 0
        market_context = {
            "highest_reached_at_t1": max_price,
            "lowest_reached_at_t1": min_price,
            "total_move_pct": round(((final_close - entry_price) / entry_price) * 100, 2),
            "missed_relative_range": round(rel_range, 2),
            "audit_duration_candles": len(klines),
            "atr_t0": atr_macro_t0,
            "atr_t1": atr_macro_t1,
            "max_atr_used": max_atr,
            "visual_evidence": {} # To be populated by Orchestrator
        }

        # 2. Results baseline (Initialized as null for non-filled trades)
        result = {
            "tp_sl_result": "NEITHER",
            "is_filled": False,
            "entry_price_at_t0": entry_price,
            "highest_reached_price": None,
            "lowest_reached_price": None,
            "exit_price_at_t1": final_close,
            "total_price_change_pct": None,
            "max_favorable_runup_pct": None,
            "max_adverse_drawdown_pct": None,
            "market_context": market_context,
            "trade_execution_metrics": {}
        }
        
        opinion = strategy.get('opinion', '').upper()
        
        # Only process execution metrics for Directional orders
        if opinion in ('BULLISH', 'BEARISH'):
            limit_order = strategy.get('limit_order') or {}
            target_entry = float(limit_order.get('entry') or entry_price)
            tp = float(limit_order.get('take_profit') or 0)
            sl = float(limit_order.get('stop_loss') or 0)
            
            if tp > 0 and sl > 0:
                entry_hit = False
                hit_result = "NEITHER"
                hit_index = len(klines)
                max_after = -float('inf')
                min_after = float('inf')
                
                for i, k in enumerate(klines):
                    high, low = float(k[2]), float(k[3])
                    
                    if not entry_hit:
                        if (opinion == 'BULLISH' and low <= target_entry) or \
                           (opinion == 'BEARISH' and high >= target_entry):
                            entry_hit = True
                            max_after, min_after = high, low
                    
                    if entry_hit:
                        max_after, min_after = max(max_after, high), min(min_after, low)
                        if hit_result == "NEITHER":
                            if opinion == 'BULLISH':
                                if low <= sl: 
                                    hit_result = "SL_HIT"
                                    hit_index = i + 1
                                elif high >= tp: 
                                    hit_result = "TP_HIT"
                                    hit_index = i + 1
                            else: # BEARISH
                                if high >= sl: 
                                    hit_result = "SL_HIT"
                                    hit_index = i + 1
                                elif low <= tp: 
                                    hit_result = "TP_HIT"
                                    hit_index = i + 1
                
                if entry_hit:
                    sl_dist = abs(target_entry - sl)
                    tp_dist = abs(tp - target_entry)
                    mae = max(0, target_entry - min_after) if opinion == 'BULLISH' else max(0, max_after - target_entry)
                    stress = (mae / sl_dist * 100) if sl_dist > 0 else 0
                    mae_atr = (mae / max_atr) if max_atr > 0 else 0
                    mfe = max(0, max_after - target_entry) if opinion == 'BULLISH' else max(0, target_entry - min_after)
                    mfe_eff = (mfe / tp_dist * 100) if tp_dist > 0 else 0
                    
                    estimated_hours = float(limit_order.get('holding_time_hours', 1.0))
                    actual_hours = hit_index * interval_hours
                    time_multiplier = round(actual_hours / estimated_hours, 2) if estimated_hours > 0 else 0
                    
                    # Update top-level outcome to reflect "Trade Exposure Only"
                    result["is_filled"] = True
                    result["tp_sl_result"] = hit_result
                    result["highest_reached_price"] = max_after
                    result["lowest_reached_price"] = min_after
                    result["total_price_change_pct"] = round(((final_close - target_entry) / target_entry) * 100, 2)
                    result["max_favorable_runup_pct"] = round(((max_after - target_entry) / target_entry) * 100, 2)
                    result["max_adverse_drawdown_pct"] = round(((min_after - target_entry) / target_entry) * 100, 2)

                    result["trade_execution_metrics"] = {
                        "duration_candles": hit_index,
                        "actual_hours": actual_hours,
                        "mae_stress_level": f"{round(stress, 1)}%",
                        "mae_atr_ratio": round(mae_atr, 2),
                        "mfe_efficiency": f"{round(mfe_eff, 1)}%",
                        "time_efficiency_multiplier": time_multiplier
                    }
                else:
                    # Order never filled
                    result["tp_sl_result"] = "NEITHER"
                    result["trade_execution_metrics"] = {
                        "duration_candles": len(klines),
                        "actual_hours": len(klines) * interval_hours
                    }
        
        return result

class ReviewerOrchestrator:
    """
    Manages the end-to-end review lifecycle: 
    Discovery -> Temporal Validation -> Outcome Retrieval -> AI Audit -> Archival.
    """
    def __init__(self, data_root: str):
        self.data_root = data_root
        self.config = load_config()
        load_dotenv()
        self.api_key = os.environ.get("GEMINI_API_KEY")
        self.reviewer = ReviewerAgent(self.config, api_key=self.api_key)
        self.fetcher = BinanceFuturesClient()
        self.observers = {}
        self.notifier = StrategyNotifier(data_root=data_root)

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
            existing_review = load_json(review_path)
            if existing_review:
                outcome = existing_review.get("market_outcome", {})
                intercept = outcome.get("intercept_status", {})
                is_intercepted = intercept.get("is_intercepted", False)
                
                # Check for AI execution failures in audit_findings
                audit_findings = existing_review.get("audit_findings", {})
                is_failure = audit_findings.get("error") in ("REVIEWER_EXECUTION_FAILURE", "JSON_PARSE_FAILURE")
                
                if not is_intercepted and not is_failure:
                    logger.info(f"Skipping {output_filename} - Finalized review already exists.")
                    return
                elif is_failure:
                    logger.info(f"Recovering {output_filename} - Previous review reported {audit_findings.get('error')}. Re-auditing...")
                else:
                    logger.info(f"Re-auditing {output_filename} - Previous review was a premature intercept.")
            else:
                # Corrupted file, allow overwrite
                pass

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
            is_premature = (dt_now < dt_end) and not force

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
            # Remove the 1500 hard cap to support paginated fetching
            target_limit = min(required_limit, 10000) 

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

            # 1. Fetch & Calculate Outcome
            metrics = session.get("observation", {}).get("quantitative_metrics", {})
            price_dynamics = metrics.get("price_dynamics", {})
            atr_macro_t0 = float(price_dynamics.get("atr_macro") or 0)
            interval_hours = interval_seconds / 3600
            
            # Use the target entry from the strategy if available, fallback to first kline's open
            strategy_obj = session.get("final_decision", {})
            limit_order = strategy_obj.get("limit_order") or {}
            target_entry = float(limit_order.get("entry") or klines[0][1])
            
            # Multimedia & Visual Forensic Context (T1 Data)
            if symbol not in self.observers:
                self.observers[symbol] = ObserverAgent(self.config, symbol, self.api_key, self.data_root)
            current_obs = self.observers[symbol].observe(timestamp=dt_fetch_end)
            
            current_metrics = current_obs.get("quantitative_metrics", {})
            current_price_dynamics = current_metrics.get("price_dynamics", {})
            atr_macro_t1 = float(current_price_dynamics.get("atr_macro") or 0)
            
            # 2. Execute Outcome Calculation (Decoupled Time and Space)
            outcome = OutcomeCalculator.calculate(
                klines, target_entry, strategy_obj, 
                atr_macro_t0=atr_macro_t0, 
                atr_macro_t1=atr_macro_t1, 
                interval_hours=interval_hours
            )

            # 3. Handle Premature/Intercepted Windows
            tp_sl_status = outcome.get("tp_sl_result", "NEITHER")
            const_is_intercepted = is_premature and tp_sl_status == "NEITHER"
            
            intercept_status = {
                "is_intercepted": const_is_intercepted,
                "reason": "PREMATURE_WINDOW" if const_is_intercepted else "NONE",
                "threshold_hours": round(window_hours, 2),
                "elapsed_hours": round((dt_fetch_end - dt_start).total_seconds() / 3600, 2),
                "message": "Market window not yet closed. Review intercepted to preserve compute." if const_is_intercepted else "Finalized"
            }
            outcome["intercept_status"] = intercept_status

            if const_is_intercepted:
                logger.info(f"Intercept status active for {symbol}. Bypassing AI audit.")
                visual_evidence = {}
                audit_result = {
                    "evaluation_score": 0,
                    "adversarial_audit": {
                        "protocol_breach": f"SYSTEM INTERCEPT: {intercept_status['message']}",
                        "shadow_evidence": [],
                        "hallucination_detected": False
                    },
                    "post_mortem": f"[TRAJECTORY REALITY] -> Market window open ({intercept_status['elapsed_hours']}h / {intercept_status['threshold_hours']}h). [PROTOCOL & DECISION CHAIN AUTOPSY] -> Skipped. [SCORING] -> Pending."
                }
            else:
                # current_obs is now pre-fetched for ATR calculation
                t0_assets = session.get("observation", {}).get("visual_assets", {})
                t1_assets = current_obs.get("visual_assets", {})

                visual_evidence = {
                    "t0_macro": t0_assets.get("macro_snapshot"),
                    "t0_micro": t0_assets.get("micro_snapshot"),
                    "t1_macro": t1_assets.get("macro_snapshot"),
                    "t1_micro": t1_assets.get("micro_snapshot")
                }
                
                # Inject visual evidence into nested market_context
                if "market_context" in outcome:
                    outcome["market_context"]["visual_evidence"] = visual_evidence

                audit_result = self.reviewer.review(
                    historical_strategy=session,
                    actual_outcome=outcome,
                    current_observation=current_obs,
                    visual_context=visual_evidence
                )
            # -------------------------------------------------------------------------

            # 4. Archive results (No standalone visual_context or top-level ATRs)
            audit_archive = {
                "audit_timestamp": dt_fetch_end.isoformat(),
                "strategy_session": session,
                "market_outcome": outcome,
                "audit_findings": audit_result
            }
            save_json(audit_archive, output_path)
            logger.info(f"Forensic audit archived: {output_path}")

            # 5. Notify Review Report
            symbol = session.get("observation", {}).get("symbol", "UNKNOWN")
            self.notifier.notify_review(symbol, audit_archive)

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
            # Neutral Audit: Use half of the micro-context lookback window (tactical half-cycle).
            micro_lookback = int(micro_cfg['historical_lookback_candles'])
            micro_window_sec = micro_interval_sec * micro_lookback
            return (micro_window_sec / 2.0) / 3600
        
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
    parser.add_argument("--force", action="store_true", help="Bypass temporal checks")
    
    from src.utils.agent_utils import add_data_root_argument, resolve_data_root
    add_data_root_argument(parser)
    
    args = parser.parse_args()
    
    # Resolve data_root
    data_root = args.data_root or resolve_data_root(args.env_shortcut)
    if not data_root:
        logger.error("Error: --data_root or environment shortcut (e.g., prod, live) must be provided.")
        sys.exit(1)
    
    orchestrator = ReviewerOrchestrator(data_root=data_root)
    orchestrator.run_review(target_file=args.file, force=args.force)

if __name__ == "__main__":
    main()
