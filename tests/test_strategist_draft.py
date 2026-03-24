import os
import sys
import json
import yaml
import logging
from datetime import datetime
from dotenv import load_dotenv

# Ensure we can find the 'src' package
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from src.agent.strategist_agent import StrategistAgent

# Setup simple logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("TestStrategist")

def test_draft_cli():
    load_dotenv()
    
    parser = argparse.ArgumentParser(description="Test StrategistAgent Draft with an observation file.")
    parser.add_argument("--observation", "-o", type=str, help="Path to the observation JSON file.")
    args = parser.parse_args()
    
    api_key = os.environ.get("GEMINI_API_KEY")
    
    # 1. Load Config
    config_path = os.path.join(PROJECT_ROOT, "config/config.yaml")
    with open(config_path, 'r') as f:
        config = yaml.safe_load(f)
    
    # 2. Determine Observation Path
    obs_path = args.observation
    if not obs_path:
        # Default fallback for convenience
        obs_path = os.path.join(PROJECT_ROOT, "data/observations/BTCUSDT_observation_20260324_053515.json")
        logger.info(f"No observation file provided, using default: {obs_path}")

    if not os.path.exists(obs_path):
        logger.error(f"Observation file not found at: {obs_path}")
        return
        
    with open(obs_path, 'r') as f:
        observation = json.load(f)
    
    # 3. Initialize Strategist
    agent = StrategistAgent(config, api_key=api_key)
    
    # 4. Run Draft
    logger.info(f"--- Running Isolated Strategist Draft Test using: {os.path.basename(obs_path)} ---")
    try:
        result = agent.draft(observation)
        
        print("\n=== STRATEGIST DRAFT RESULT ===")
        print(json.dumps(result, indent=2, ensure_ascii=False))
        print("===============================\n")
        
    except Exception as e:
        logger.error(f"Draft test failed: {e}", exc_info=True)

if __name__ == "__main__":
    import argparse
    test_draft_cli()
