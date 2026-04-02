#!/usr/bin/env python3
import os
import sys
import argparse
import json
from src.utils.pipeline_utils import resolve_data_root
from src.utils.json_utils import load_json, save_json
from src.utils.datetime_utils import sanitize_timestamp
from src.utils.path_utils import resolve_project_root

def main():
    """
    Strategy Exporter - Reverse Engineering Utility.
    Extracts the original strategy session from a forensic report and restores it to the strategies folder.
    """
    parser = argparse.ArgumentParser(description="Strategy Exporter - Reverse Engineering Utility")
    parser.add_argument("--file", required=True, help="Path to the forensic JSON report")
    
    # Standardize data root arguments
    from src.utils.pipeline_utils import add_data_root_argument, resolve_data_root
    add_data_root_argument(parser)
    
    args = parser.parse_args()
    
    # 1. Resolve Data Root: priority to --data_root, fallback to env_shortcut
    data_root = args.data_root or resolve_data_root(args.env_shortcut)
    
    if not data_root:
        print(f"Error: Could not resolve data root for shortcut '{args.env_shortcut}'")
        sys.exit(1)
        
    # 2. Load Forensic Report
    if not os.path.exists(args.file):
        print(f"Error: Forensic report not found at '{args.file}'")
        sys.exit(1)
        
    forensic_data = load_json(args.file)
    if not forensic_data:
        print(f"Error: Could not load or parse forensic report from '{args.file}'")
        sys.exit(1)
        
    # 3. Extract Strategy Session
    # The original strategy content is mirrored exactly in 'strategy_session'
    strategy_session = forensic_data.get("strategy_session")
    if not strategy_session:
        print(f"Error: 'strategy_session' block not found in the report.")
        sys.exit(1)
        
    # 4. Generate Filename from Metadata
    # We reconstruct the filename using the same logic as the strategist
    observation = strategy_session.get("observation", {})
    symbol = observation.get("symbol")
    timestamp = observation.get("timestamp")
    
    if not symbol or not timestamp:
        print("Error: Could not find 'symbol' or 'timestamp' in the strategy session observation.")
        sys.exit(1)
        
    ts_suffix = sanitize_timestamp(timestamp)
    filename = f"{symbol}_strategies_{ts_suffix}.json"
    
    # 5. Save to the standardized Strategies Directory
    project_root = resolve_project_root()
    output_dir = os.path.join(project_root, data_root, "strategies")
    output_path = os.path.join(output_dir, filename)
    
    # save_json handles directory creation and pretty-printing
    if save_json(strategy_session, output_path):
        print(f"--- Export Successful ---")
        print(f"Source: {args.file}")
        print(f"Exported: {output_path}")
    else:
        print(f"Error: Failed to write strategy file to {output_path}")
        sys.exit(1)

if __name__ == "__main__":
    main()
