#!/usr/bin/env python3
import os
import sys
import time
import argparse
import logging
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv

# Setup absolute project paths
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# Load environment
load_dotenv()

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
    """
    
    def __init__(self, args):
        self.args = args
        self.global_cfg = load_global_config()
        self.symbol = args.symbol or self.global_cfg['system']['default_symbol']
        
        # 1. Initialize Lightweight Sniper Tools
        self.scout = SniperScout(self.symbol)
        self.trigger = SniperTrigger()
        
        # 2. Initialize Heavyweight Session Engine (Optional)
        self.session_engine = None
        if args.trigger:
            # We pass the same args to SessionEngine for email/path parity
            self.session_engine = SessionEngine(self.symbol, args.path, args=args)
        
        self.prev_metrics = None
        
        # v6.50: Sniper Quiet-Monitoring Protocol
        # We default to CRITICAL level during pulsars to keep logs clean from Binance noise.
        logging.getLogger("src.infrastructure.binance.client").setLevel(logging.CRITICAL)

    def run_forever(self):
        pulse_mins = self.args.pulse
        logger.info(f"--- Sniper Monitoring Started: {self.symbol} (Pulse: {pulse_mins}m) ---")
        
        while True:
            try:
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
                    
                    logger.info(f"WAKE UP! [{t_type}] | {reason}")
                    
                    if self.session_engine:
                        # 4. Trigger Binary Star Protocol
                        logger.info("SniperDaemon: Activating Binary Star reasoning loop (Blocking Pulse)...")
                        # v6.50: Restore Forensic Logging Level for Session Cycle
                        logging.getLogger("src.infrastructure.binance.client").setLevel(logging.INFO)
                        
                        # This is a blocking call (Synchronous/Serial)
                        # It will generate images, run AI, and send emails if --email is on.
                        self.session_engine.execute_cycle()
                        
                        # Restore Quiet Protocol after session completion
                        logging.getLogger("src.infrastructure.binance.client").setLevel(logging.CRITICAL)
                        logger.info("SniperDaemon: Session cycle complete. Returning to pulse monitoring.")
                    
                    # 5. Mark Triggered to start Cooldown (System Safety)
                    self.trigger.set_triggered(t_type)

                # 6. Housekeeping
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

def main():
    parser = argparse.ArgumentParser(description="Singularity Sniper Daemon (Intelligence-Led Execution)")
    parser.add_argument("--symbol", type=str, default=None, help="Trading pair (e.g. BTCUSDT)")
    parser.add_argument("--pulse", type=float, default=5.0, help="Sniper check interval in minutes")
    parser.add_argument("--trigger", action="store_true", help="Enable automatic activation of AI sessions")
    parser.add_argument("--email", action="store_true", help="Enable high-conviction email alerts for sessions")
    parser.add_argument("--path", type=str, default="data/prod", help="Path for session archival")

    args = parser.parse_args()
    
    daemon = SniperDaemon(args)
    daemon.run_forever()

if __name__ == "__main__":
    main()
