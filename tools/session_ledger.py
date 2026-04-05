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
    parser = argparse.ArgumentParser(description="Thin UI Wrapper for Execution Visualization (v5.5)")
    parser.add_argument("--symbol", type=str, help="Symbol to filter")
    parser.add_argument("--email", action="store_true", help="Dispatch email notification.")
    parser.add_argument("--recursive", "-r", action="store_true", help="Perform recursive history scan.")
    parser.add_argument("--file", "-f", type=str, help="Directly parse a sandbox result JSON file.")
    add_data_path_argument(parser, required=False) # Make path optional if file is provided
    
    args = parser.parse_args()
    
    # Validation: Must have either --path or --file
    if not args.path and not args.file:
        logger.error("Usage Error: You must provide either --path (-p) for directory scan OR --file for direct sandbox parsing.")
        sys.exit(1)

    global_cfg = load_global_config()
    symbol = args.symbol or global_cfg['system']['default_symbol']
    data_root = args.path
    if not data_root:
        logger.error("Context Error: --path (-p) is required to resolve forensic assets and output reports (even in direct --file mode).")
        sys.exit(1)
        
    # Delegate and Execute
    try:
        controller = LedgerVisualizer(data_root=data_root, logger=logger)
        
        if args.file:
            # Mode A: Direct Sandbox File Parsing
            controller.generate_from_sandbox_file(args.file, symbol, notify=args.email)
        else:
            # Mode B: Standard Directory Scan
            controller.generate_html_report(symbol, notify=args.email, recursive=args.recursive)
            
    except Exception as e:
        logger.error(f"Dashboard Generation Failed: {e}", exc_info=True)
        sys.exit(1)

if __name__ == "__main__":
    main()
