#!/usr/bin/env python3
import os
import sys
import time
import argparse
import logging
from datetime import datetime, timezone
from dotenv import load_dotenv

# Setup absolute project paths
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# Load environment
load_dotenv()

from src.infrastructure.binance.client import BinanceFuturesClient
from src.sniper.scout import SniperScout
from src.sniper.trigger import SniperTrigger
from run_session import SessionEngine
from src.utils.logger_utils import setup_logger
from src.utils.pipeline_utils import load_global_config

logger = setup_logger("SniperDaemon")

class SniperDaemon:
    """
    The Intelligence-Led Pulse Micro-Orchestrator.
    
    Monitors market topography at high-frequency (Lightweight) and 
    activates the 'Binary Star' reasoning engine (Heavyweight) 
    only when a Wake-Up Matrix condition is met.
    
    When --trade is enabled, also acts as the Position Guardian,
    protecting open positions with OCO orders every pulse cycle.
    """
    
    def __init__(self, args):
        self.args = args
        self.global_cfg = load_global_config()
        self.symbol = args.symbol or self.global_cfg['system']['default_symbol']
        
        # 0. Global Forensic Logging Initialization (Standardized v7.1)
        # Ensure all pulse and guardian telemetry is persistent from startup
        from src.utils.path_utils import resolve_project_root
        session_log_path = os.path.join(resolve_project_root(), args.path, "sniper.log")
        setup_logger("", log_level=logging.INFO, log_file=session_log_path,
                     max_bytes=10 * 1024 * 1024, backup_count=5)  # 10MB x 5 = 50MB max
        
        # v7.6 Shared Infrastructure: Centralized client to prevent duplicate logs/init
        self.futures_client = BinanceFuturesClient()

        # 1. Initialize Lightweight Sniper Tools
        self.scout = SniperScout(self.symbol, exchange_client=self.futures_client)
        self.trigger = SniperTrigger()
        
        logger.info(f"SniperDaemon: Trigger Cooldown is active at {self.trigger.cooldown_minutes}m.")
        
        # 2. Initialize Heavyweight Session Engine (Optional)
        self.session_engine = None
        if args.trigger:
            # We pass the same args to SessionEngine for email/path parity
            self.session_engine = SessionEngine(self.symbol, args.path, args=args, 
                                                exchange_client=self.futures_client)
        
        # 3. Initialize Trade Execution (Optional: --trade flag)
        self.trade_enabled = getattr(args, 'trade', False)
        self.executor = None
        self.trade_state = {}  # In-memory state for Guardian
        if self.trade_enabled:
            from src.infrastructure.binance.margin_client import BinanceMarginClient
            from src.agent.order_executor import MarginOrderExecutor
            margin_client = BinanceMarginClient()
            self.executor = MarginOrderExecutor(client=margin_client)
            logger.info("SniperDaemon: Trade execution ENABLED. Guardian will monitor positions every pulse.")
        
        self.prev_metrics = None
        
        # v6.50: Sniper Quiet-Monitoring Protocol
        # We default to CRITICAL level during pulsars to keep logs clean from Binance noise.
        logging.getLogger("src.infrastructure.binance.client").setLevel(logging.CRITICAL)

    def run_forever(self):
        pulse_mins = load_global_config()['sniper']['pulse_interval_minutes']
        logger.info(f"--- Sniper Monitoring Started: {self.symbol} (Pulse: {pulse_mins}m) ---")
        
        while True:
            try:
                # 0. [GUARDIAN] Position protection check (every pulse, regardless of trigger state)
                if self.trade_enabled and self.executor:
                    self._guardian_check()

                # 1. Capture Topography (No Images, No AI)
                result = self.scout.scout()
                metrics = result.metrics
                
                if not metrics:
                    logger.warning("SniperDaemon: Scout returned empty metrics. Skipping pulse.")
                    time.sleep(60)
                    continue

                # 2. Check Wake-Up Matrix (Interest Evaluation)
                is_noteworthy, t_type, reason = self.trigger.evaluate(metrics, self.prev_metrics)
                
                # 3. Report Status
                now_str = datetime.now().strftime("%H:%M:%S")
                if self.prev_metrics is None:
                    logger.info(f"--- Sniper Monitoring Started: Initial Baseline Established ({self.symbol}) ---")

                if not is_noteworthy:
                    # Low-entropy log for sleeping state
                    status = reason if "COOLDOWN" in reason else "SLEEPING"
                    print(f"[{now_str}] 💤 {status} | No actionable asymmetry detected.")
                else:
                    # High-fidelity event logging with prominent UI
                    print("\n" + "!"*60)
                    print(f"       🔫 SNIPER WAKE UP! [{t_type}]")
                    print("!"*60)
                    print(f"REASON: {reason}")
                    print("!"*60 + "\n")
                    if self.session_engine:
                        # 4. Trigger Binary Star Protocol
                        logger.info("SniperDaemon: Activating Binary Star reasoning loop (Blocking Pulse)...")
                        # v6.50: Restore Forensic Logging Level for Session Cycle
                        logging.getLogger("src.infrastructure.binance.client").setLevel(logging.INFO)
                        
                        # This is a blocking call (Synchronous/Serial)
                        # It will generate images, run AI, and send emails if --email is on.
                        session_result = self.session_engine.execute_cycle()
                        
                        # 5. Attempt Trade Execution (if enabled and session succeeded)
                        if self.trade_enabled and self.executor and session_result and "error" not in session_result:
                            self._attempt_trade_execution(session_result)
                        
                        # Restore Quiet Protocol after session completion
                        logging.getLogger("src.infrastructure.binance.client").setLevel(logging.CRITICAL)
                        logger.info("SniperDaemon: Session cycle complete. Returning to pulse monitoring.")
                    
                    # 6. Mark Triggered to start Cooldown (System Safety)
                    self.trigger.set_triggered(t_type)

                # 7. Housekeeping
                self.prev_metrics = metrics
                
                # Sleep until next pulse
                logger.debug(f"SniperDaemon: Waiting {pulse_mins}m for next check...")
                time.sleep(pulse_mins * 60)

            except KeyboardInterrupt:
                logger.warning("SniperDaemon terminated by user.")
                break
            except Exception as e:
                logger.error(f"SniperDaemon Loop Failure: {e}", exc_info=True)
                time.sleep(60) # Wait a minute before retrying on error

    # ================================================================
    # TRADE GATE: Evaluates AI decision and triggers entry
    # ================================================================

    def _attempt_trade_execution(self, session_result):
        """
        Evaluates session result against confidence threshold and triggers trade execution.
        Migrated from SessionEngine to SniperDaemon for Guardian lifecycle management.
        """
        try:
            final_decision = session_result.get('final_decision', {})
            opinion = str(final_decision.get('opinion', 'NEUTRAL')).upper()
            confidence = float(final_decision.get('confidence_score', 0))
            tactical = final_decision.get('tactical_parameters', {})
            
            logger.info(f"TradeGate: Evaluating session -> Opinion={opinion}, Confidence={confidence}%")
            
            # Gate 1: Directional opinion required
            if opinion not in ('BULLISH', 'BEARISH'):
                logger.info(f"TradeGate: Opinion is {opinion}. No trade action.")
                return
            
            # Gate 2: Confidence threshold
            threshold = int(self.global_cfg['session']['confidence_threshold'])
            if confidence < threshold:
                logger.info(f"TradeGate: Confidence {confidence}% < threshold {threshold}%. Skipping trade.")
                return
            
            # Gate 3: Tactical parameters must be present
            entry = tactical.get('entry')
            tp = tactical.get('take_profit')
            sl = tactical.get('stop_loss')
            if not all([entry, tp, sl]):
                logger.warning(f"TradeGate: Missing tactical parameters (Entry={entry}, TP={tp}, SL={sl}). Skipping trade.")
                return
            
            # Map AI opinion to executor direction
            direction = 'LONG' if opinion == 'BULLISH' else 'SHORT'
            
            # Extract projected waiting time for Guardian timeout
            projected_waiting = tactical.get('projected_waiting_hours', 4.0)
            
            logger.info(f"TradeGate: ALL GATES PASSED. Executing {direction} for {self.symbol} "
                        f"(Confidence: {confidence}%, Entry: {entry}, TP: {tp}, SL: {sl}, "
                        f"Projected Wait: {projected_waiting}h)")
            
            order_id = self.executor.sync_with_opinion(
                symbol=self.symbol,
                opinion_direction=direction,
                entry_price=float(entry),
                tp_price=float(tp),
                sl_price=float(sl)
            )
            
            # Update trade state for Guardian tracking
            if order_id:
                self.trade_state = {
                    "direction": direction,
                    "entry_price": float(entry),
                    "tp_price": float(tp),
                    "sl_price": float(sl),
                    "entry_order_id": order_id,
                    "entry_placed_at": datetime.now(timezone.utc),
                    "projected_waiting_hours": float(projected_waiting),
                }
                logger.info(f"TradeGate: Trade state updated. Guardian will monitor order {order_id}.")
            else:
                # sync_with_opinion returned None — could be SAME_DIRECTION optimization
                # Keep existing trade_state if it has a direction (position is being managed)
                if not self.trade_state.get("direction"):
                    logger.info("TradeGate: No entry order placed and no active trade state.")
                    
        except Exception as e:
            logger.error(f"TradeGate: Trade execution failed: {e}", exc_info=True)

    # ================================================================
    # GUARDIAN: Position protection every pulse
    # ================================================================

    def _guardian_check(self):
        """Delegates to MarginOrderExecutor.guardian_check() and updates trade_state."""
        try:
            logger.debug(f"Guardian: Checking position state for {self.symbol}...")
            updated_state = self.executor.guardian_check(self.symbol, self.trade_state)
            
            if updated_state != self.trade_state:
                if not updated_state:
                    logger.info("Guardian: Trade state cleared (position closed or entry expired).")
                self.trade_state = updated_state or {}
                
        except Exception as e:
            logger.error(f"Guardian: Check failed: {e}", exc_info=True)

def main():
    parser = argparse.ArgumentParser(description="Singularity Sniper Daemon v7.1 (Zero-Entropy Architecture)")
    parser.add_argument("--symbol", type=str, default=None, help="Trading pair (e.g. BTCUSDT)")
    parser.add_argument("--trigger", action="store_true", help="Enable automatic activation of AI sessions")
    parser.add_argument("--email", action="store_true", help="Enable high-conviction email alerts for sessions")
    parser.add_argument("--trade", action="store_true", help="Enable automated margin trading execution")
    from src.utils.pipeline_utils import add_data_path_argument
    add_data_path_argument(parser)

    args = parser.parse_args()
    
    # v7.1: Zero-Entropy Path Resolution
    if not args.path:
        args.path = "data/prod"
    
    daemon = SniperDaemon(args)
    daemon.run_forever()

if __name__ == "__main__":
    main()
