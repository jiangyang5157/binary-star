#!/usr/bin/env python3
import os
import sys
import time
import argparse
import logging
from datetime import datetime, timezone

# Setup absolute project paths
PROJECT_ROOT = os.path.dirname(os.path.abspath(os.path.join(__file__, "../")))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.tools.sniper.scout import SniperScout
from src.tools.sniper.trigger import SniperTrigger
from src.utils.logger_utils import setup_logger

logger = setup_logger("SniperSandbox")

def main():
    parser = argparse.ArgumentParser(description="Singularity Sniper Mode Sandbox (Independent Test)")
    parser.add_argument("--symbol", type=str, default="BTCUSDT", help="Trading pair symbol")
    parser.add_argument("--loop", action="store_true", help="Run in continuous monitoring loop")
    parser.add_argument("--pulse", type=float, default=1.0, help="Wait time between scouts (minutes)")
    parser.add_argument("--config", type=str, default="config/sniper_config.yaml", help="Path to sniper config")
    
    args = parser.parse_args()
    
    scout = SniperScout(args.symbol)
    trigger = SniperTrigger(args.config)
    
    prev_metrics = None
    
    logger.info(f"--- Sniper Sandbox Initialized: {args.symbol} ---")
    
    try:
        while True:
            # 1. Harvest Data (No Images)
            result = scout.scout()
            metrics = result.metrics
            
            # 2. Evaluate Matrix
            is_noteworthy, t_type, reason = trigger.evaluate(metrics, prev_metrics)
            
            # 3. Report
            status_icon = "🔫 WAKE UP!" if is_noteworthy else "💤 SLEEPING"
            print(f"[{datetime.now().strftime('%H:%M:%S')}] {status_icon} | {t_type or 'NONE'} | {reason}")
            
            if is_noteworthy:
                logger.info(f"Trigger Detail: {reason}")
                # In a real system, we would call orchestrator.execute_flow() here.
                # Since this is a test script, we only mark it as triggered to start cooldown.
                trigger.set_triggered(t_type)
            
            if not args.loop:
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
