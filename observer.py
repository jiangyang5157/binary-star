#!/usr/bin/env python3
import os
import argparse
import yaml
import logging
from datetime import datetime, timezone
from dotenv import load_dotenv

# Add src to path if needed (though running from root should be fine)
from src.agent.observer_agent import ObserverAgent
from src.utils.json_utils import save_json

# Setup logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("ObserverRunner")

def load_config(config_path: str = "config/config.yaml") -> dict:
    with open(config_path, 'r') as f:
        return yaml.safe_load(f)

def main():
    load_dotenv()
    
    parser = argparse.ArgumentParser(description="Observer Agent Runner")
    parser.add_argument("--symbol", type=str, help="Trading symbol (e.g., BTCUSDT)")
    parser.add_argument("--data_dir", type=str, help="Override base data directory")
    parser.add_argument("--timestamp", type=str, help="Historical timestamp (ISO format, e.g., 2026-03-23T22:30:00)")
    args = parser.parse_args()

    # 1. Load Config
    config = load_config()
    symbol = args.symbol or config.get('symbol', 'BTCUSDT')
    base_data_dir = args.data_dir or config['paths']['data_dir']
    
    # 2. Parse Timestamp if provided
    override_ts = None
    if args.timestamp:
        try:
            override_ts = datetime.fromisoformat(args.timestamp).replace(tzinfo=timezone.utc)
        except ValueError:
            logger.error(f"Invalid timestamp format: {args.timestamp}. Use ISO format (YYYY-MM-DDTHH:MM:SS)")
            return

    # 3. Initialize and Run Observer
    observer = ObserverAgent(config, symbol=symbol)
    try:
        context = observer.observe(override_timestamp=override_ts, base_data_dir=base_data_dir)
        
        # 4. Save Observation JSON
        obs_dir_name = config['paths']['observations_dir']
        obs_path = os.path.join(base_data_dir, obs_dir_name)
        os.makedirs(obs_path, exist_ok=True)
        
        # Naming: BTCUSDT_observation_20260323_231347.json
        ts_str = (override_ts or datetime.now(timezone.utc)).strftime('%Y%m%d_%H%M%S')
        filename = f"{symbol}_observation_{ts_str}.json"
        final_file_path = os.path.join(obs_path, filename)
        
        save_json(context, final_file_path)
        logger.info(f"Observation complete. Result saved to: {final_file_path}")
        
    except Exception as e:
        logger.error(f"Observation failed: {e}", exc_info=True)
    finally:
        observer.close()

if __name__ == "__main__":
    main()
