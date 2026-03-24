#!/usr/bin/env python3
import os
import sys
import argparse
import yaml
import logging
from typing import Dict, Any
from dotenv import load_dotenv

# Add src to path if needed (though running from root should be fine)
from src.agent.observer_agent import ObserverAgent
from src.utils.json_utils import save_json
from src.utils.agent_utils import load_config
from src.utils.logger_utils import setup_logger
from src.utils.datetime_utils import parse_iso_to_utc, get_utc_now, FILE_TS_FORMAT

# Setup logging
logger = setup_logger("ObserverPipeline")


def main():
    parser = argparse.ArgumentParser(description="Observer Agent Pipeline")
    parser.add_argument("--symbol", type=str, required=True, help="Trading symbol (e.g., BTCUSDT)")
    parser.add_argument("--timestamp", type=str, help="Historical timestamp (ISO format, e.g., 2026-03-23T22:30:00)")
    parser.add_argument("--data_dir", type=str, help="Override base data directory")
    args = parser.parse_args()

    symbol = args.symbol

    load_dotenv()
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        logger.error("GEMINI_API_KEY not found in environment")
        return

    timestamp = None
    if args.timestamp:
        try:
            timestamp = parse_iso_to_utc(args.timestamp)
        except ValueError:
            logger.error(f"Invalid timestamp format: {args.timestamp}. Use ISO format (YYYY-MM-DDTHH:MM:SS)")
            return

    config = load_config()
    paths_config = config['paths']
    data_dir = args.data_dir or paths_config['data_dir']
    
        
    observerAgent = ObserverAgent(config, symbol=symbol, api_key=api_key)
    try:
        context = observerAgent.observe(timestamp=timestamp, data_dir=data_dir)
        
        observations_path = os.path.join(data_dir, paths_config['observations_dir'])
        os.makedirs(observations_path, exist_ok=True)
        
        timestamp_str = (timestamp or get_utc_now()).strftime(FILE_TS_FORMAT)
        output_file = f"{symbol}_observation_{timestamp_str}.json"
        final_observation = os.path.join(observations_path, output_file)
        
        save_json(context, final_observation)
        logger.info(f"Observation complete. Result saved to: {final_observation}")
        
    except Exception as e:
        logger.error(f"Observation failed: {e}", exc_info=True)
    finally:
        observerAgent.close()

if __name__ == "__main__":
    main()
