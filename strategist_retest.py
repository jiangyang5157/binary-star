#!/usr/bin/env python3
import os
import sys
import argparse
import logging
import json
from typing import Optional
from dotenv import load_dotenv

# Setup paths
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJECT_ROOT)

from src.agent.strategist_agent import StrategistAgent
from src.agent.critic_agent import CriticAgent
from strategist import run_full_triad_flow, archive_strategy_result
from src.utils.agent_utils import load_config
from src.utils.logger_utils import setup_logger
# No extra imports needed for archival here

# Setup logging
logger = setup_logger("StrategistRetestPipeline")

def run_retest(file_path: str, data_root: Optional[str] = None):
    """
    Offline Retest Pipeline: JSON Observation -> (Draft -> Audit -> Synthesis)
    """
    logger.info(f"=== Starting Strategist Retest Pipeline from file: {file_path} ===")
    
    if not os.path.exists(file_path):
        logger.error(f"Observation file not found: {file_path}")
        return

    config = load_config()
    # paths_config = config['paths']  # Removed

    load_dotenv()
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        logger.error("GEMINI_API_KEY not found in environment")
        return

    # Use "data" as default if data_root not provided
    final_data_root = data_root or "data"

    try:
        # 1. Load Observation
        with open(file_path, 'r', encoding='utf-8') as f:
            observation = json.load(f)
        
        symbol = observation.get('symbol')
        logger.info(f"Loaded observation for {symbol} at {observation.get('timestamp')}")

        # 2. Initialize Agents
        strategist = StrategistAgent(config, api_key=api_key)
        critic = CriticAgent(config, api_key=api_key)

        # 3. Stages 2-4: Reasoning Triad (Draft -> Audit -> Synthesis)
        result = run_full_triad_flow(observation, strategist, critic)
        
        # 4. Archive
        output_file = archive_strategy_result(
            symbol=symbol, 
            timestamp=observation.get('timestamp'), 
            result=result, 
            data_root=final_data_root, 
            target_dir="strategies"
        )
        logger.info(f"Retest Session archived to: {output_file}")

    except Exception as e:
        logger.error(f"Retest failed: {e}", exc_info=True)
    finally:
        logger.info("=== Retest Complete ===")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Strategist Retest - Reasoning from File")
    parser.add_argument("--file", type=str, required=True, help="Path to observation JSON file.")
    parser.add_argument("--data_root", type=str, help="Data directory override")
    args = parser.parse_args()
    
    run_retest(file_path=args.file, data_root=args.data_root)
