#!/usr/bin/env python3
import os
import sys
import time
import argparse
from datetime import datetime, timezone

# Setup absolute project paths
PROJECT_ROOT = os.path.dirname(os.path.abspath(os.path.join(__file__, "../")))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.sniper.scout import SniperScout
from src.sniper.trigger import SniperTrigger
from src.utils.logger_utils import setup_logger

logger = setup_logger("SniperSandbox")

def main():
    parser = argparse.ArgumentParser(description="Singularity Sniper Mode Sandbox (Independent Test)")
    parser.add_argument("--symbol", type=str, default="BTCUSDT", help="Trading pair symbol")
    parser.add_argument("--pulse", type=float, default=0.0, help="Wait time between scouts (minutes). 0 for one-shot.")
    
    args = parser.parse_args()
    
    scout = SniperScout(args.symbol)
    trigger = SniperTrigger()
    
    prev_metrics = None
    
    logger.info(f"--- Sniper Sandbox Initialized: {args.symbol} (Pulse: {args.pulse}m) ---")
    
    try:
        while True:
            # 1. Harvest Data (No Images)
            result = scout.scout()
            metrics = result.metrics
            
            # 2. Evaluate Matrix
            is_noteworthy, t_type, reason = trigger.evaluate(metrics, prev_metrics)
            
            # 3. Report
            if is_noteworthy:
                print("\n" + "="*50)
                print(f"       🔫 SNIPER WAKE UP! [{t_type}]")
                print("="*50)
                print(f"REASON: {reason}")
                print("="*50 + "\n")
                
                logger.info(f"Trigger Detail: {reason}")
                trigger.set_triggered(t_type)
            else:
                print(f"[{datetime.now().strftime('%H:%M:%S')}] 💤 SLEEPING | No actionable asymmetry.")
            
            # 4. Loop Logic
            if args.pulse <= 0:
                break
                
            prev_metrics = metrics
            logger.info(f"Waiting {args.pulse}m for next scout...")
            time.sleep(args.pulse * 60)
            
    except KeyboardInterrupt:
        logger.warning("Sniper Sandbox terminated by user.")
    finally:
        scout.close()

if __name__ == "__main__":
    main()
