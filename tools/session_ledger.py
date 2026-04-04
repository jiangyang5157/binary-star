#!/usr/bin/env python3
import os
import sys
import argparse
from typing import Optional

# Setup absolute project paths
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path: sys.path.insert(0, PROJECT_ROOT)

from src.analyzer.ledger_visualizer import LedgerVisualizer
from src.utils.pipeline_utils import load_global_config, add_data_path_argument
from src.utils.logger_utils import setup_logger

# Initialize CLI-level logger
logger = setup_logger("LedgerDashboard")

def main():
    parser = argparse.ArgumentParser(description="Thin UI Wrapper for Execution Visualization (v5.3)")
    parser.add_argument("--symbol", type=str, help="Symbol to filter")
    parser.add_argument("--email", action="store_true", help="Dispatch email notification.")
    parser.add_argument("--recursive", "-r", action="store_true", help="Perform recursive history scan.")
    add_data_path_argument(parser, required=True)
    
    args = parser.parse_args()
    data_root = args.path
        
    global_cfg = load_global_config()
    symbol = args.symbol or global_cfg['system']['default_symbol']
    
    # Delegate and Execute
    try:
        controller = LedgerVisualizer(data_root=data_root, logger=logger)
        controller.generate_html_report(symbol, notify=args.email, recursive=args.recursive)
    except Exception as e:
        logger.error(f"Dashboard Generation Failed: {e}", exc_info=True)
        sys.exit(1)

if __name__ == "__main__":
    main()
