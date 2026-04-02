#!/usr/bin/env python3
import os
import sys
import argparse

# Setup absolute project paths
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path: sys.path.insert(0, PROJECT_ROOT)

from src.analyzer.recon_controller import ReconController
from src.utils.pipeline_utils import load_config, resolve_data_root, load_global_config
from src.utils.logger_utils import setup_logger

# Initialize CLI-level logger
logger = setup_logger("MarketObserver")

def main():
    parser = argparse.ArgumentParser(description="Thin CLI Wrapper for Market Reconnaissance (v5.3)")
    parser.add_argument("--symbol", type=str, help="Symbol to observe (e.g., BTCUSDT)")
    from src.utils.pipeline_utils import add_data_root_argument
    add_data_root_argument(parser)
    args = parser.parse_args()
    
    data_root = args.data_root or resolve_data_root(args.env_shortcut)
    if not data_root:
        print("Error: --data_root or environment shortcut (e.g., prod, live) required.")
        sys.exit(1)
        
    config = load_config()
    global_cfg = load_global_config()
    symbol = args.symbol or global_cfg['system']['default_symbol']
    
    # Delegate logic to controller
    try:
        controller = ReconController(config_dict=config, data_root=data_root, logger=logger)
        result = controller.observe_market(symbol)
        obs = result['observation']
        
        print("\n" + "="*50)
        print(f"MARKET TOPOGRAPHY: {symbol}")
        print("="*50)
        metrics = obs.get("quantitative_metrics", {})
        topo = metrics.get("volume_topography", {})
        dyn = metrics.get("price_dynamics", {})
        print(f"POC: {topo.get('poc')} | ATR: {dyn.get('atr_macro')}")
        print(f"VAH: {topo.get('vah')} | VAL: {topo.get('val')}")
        print("="*50 + "\n")
        
    except Exception as e:
        logger.error(f"Market Recon Failed: {e}", exc_info=True)
        sys.exit(1)

if __name__ == "__main__":
    main()
