#!/usr/bin/env python3
import os
import sys
import argparse

# Setup absolute project paths
TOOLS_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(TOOLS_DIR, ".."))
if PROJECT_ROOT not in sys.path: sys.path.insert(0, PROJECT_ROOT)

from src.analyzer.topography_engine import TopographyEngine
from src.utils.pipeline_utils import load_config, load_global_config
from src.utils.logger_utils import setup_logger

# Initialize CLI-level logger
logger = setup_logger("MarketRecon")

def main():
    parser = argparse.ArgumentParser(description="Singularity Market Recon Tool")
    parser.add_argument("--symbol", type=str, required=True, help="Trading pair prefix (e.g. BTC)")
    parser.add_argument("--timestamp", "-ts", type=str, help="ISO-8601 timestamp (e.g., 2026-04-05T00:23:34Z)")
    parser.add_argument("--email", action="store_true", help="Dispatch email notification of the market scan.")
    from src.utils.pipeline_utils import add_data_path_argument
    add_data_path_argument(parser, required=True)
    args = parser.parse_args()
    
    data_root = args.path
        
    config = load_config()
    global_cfg = load_global_config()
    
    # Merge for full configuration awareness (visuals, network, etc.)
    merged_config = config.copy()
    merged_config.update(global_cfg)
    
    from src.utils.symbol_utils import resolve_symbol
    symbol = resolve_symbol(args.symbol)
    
    # Optional historical anchor
    at_time = None
    if args.timestamp:
        import pandas as pd
        at_time = pd.to_datetime(args.timestamp).to_pydatetime()
    
    # Delegate logic to controller
    try:
        controller = TopographyEngine(config_dict=merged_config, data_root=data_root, logger=logger)
        result = controller.reconstruct(symbol, at_time=at_time, dispatch_email=args.email)
        obs = result['observation']
        
        print("\n" + "="*50)
        print(f"MARKET TOPOGRAPHY: {symbol}")
        print("="*50)
        metrics = obs.get("quantitative_metrics", {})
        topo = metrics.get("volume_profile", {})
        dyn = metrics.get("price_dynamics", {})
        print(f"POC: {topo.get('poc')} | ATR: {dyn.get('atr_macro')}")
        print(f"VAH: {topo.get('vah')} | VAL: {topo.get('val')}")
        print("="*50 + "\n")
        
    except Exception as e:
        logger.error(f"market recon failed | error={e}", exc_info=True)
        sys.exit(1)

if __name__ == "__main__":
    main()
