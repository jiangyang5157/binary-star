#!/usr/bin/env python3
import os
import sys
import time
import argparse
import logging
from typing import Dict, Any

# Setup paths
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.analyzer.opportunity_scanner import OpportunityScanner
from src.utils.logger_utils import setup_logger
from src.utils.agent_utils import resolve_data_root, load_global_config

def main():
    parser = argparse.ArgumentParser(description="Pure Market Scanner (No Agents)")
    parser.add_argument("--symbol", type=str, help="Trading symbol (e.g., BTCUSDT)")
    parser.add_argument("--pulse", type=float, required=True, help="Scan interval in minutes")
    
    from src.utils.agent_utils import add_data_root_argument
    add_data_root_argument(parser)
    
    args = parser.parse_args()
    
    # Resolve data_root
    data_root = args.data_root or resolve_data_root(args.env_shortcut)
    if not data_root:
        print("Error: --data_root or environment shortcut (e.g., prod, live) must be provided.")
        sys.exit(1)
    
    global_cfg = load_global_config()
    symbol = args.symbol or global_cfg['system']['default_symbol']
    
    logger_name = "MarketScanner"
    log_path = os.path.join(data_root, "market_scanner.log")
    logger = setup_logger(logger_name, log_file=log_path)
    
    logger.info(f"=== Starting Pure Market Scanner for {symbol} ===")
    logger.info(f"Pulse: {args.pulse} minutes | Data Root: {data_root}")

    try:
        scanner = OpportunityScanner(symbol, data_root, logger=logger)
    except Exception as e:
        logger.error(f"Failed to initialize OpportunityScanner: {e}")
        sys.exit(1)

    interval_hours = args.pulse / 60.0
    
    try:
        while True:
            logger.info(f"--- Scan Triggered at {time.strftime('%Y-%m-%d %H:%M:%S')} ---")
            
            # 1. Observe
            observation = scanner.scan()
            
            # 2. Analyze 'Worth It' signals
            # Note: This will log all the internal signals within is_worth_it()
            is_triggered = scanner.should_trigger(observation)
            
            if is_triggered:
                logger.info(">>> SIGNAL: CRITERIA MET. (Suggested to trigger agents)")
            else:
                logger.info(">>> SIGNAL: NO OPPORTUNITY. (Waiting for next pulse)")
            
            logger.info(f"Next scan in {args.pulse} minutes...")
            time.sleep(args.pulse * 60)
            
    except KeyboardInterrupt:
        logger.info("Scanner Service received shutdown signal.")
    except Exception as e:
        logger.error(f"Scanner Service encountered a fatal error: {e}", exc_info=True)
        sys.exit(1)

if __name__ == "__main__":
    main()
