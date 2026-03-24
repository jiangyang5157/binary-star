import os
import sys
import json
import logging
from datetime import datetime, timezone

# Add project root to sys.path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from src.agent.observer_agent import ObserverAgent
import yaml
from dotenv import load_dotenv

# Setup logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("TestObserverAgent")

def load_config(config_path: str = "config/config.yaml") -> dict:
    abs_config_path = os.path.join(PROJECT_ROOT, config_path)
    with open(abs_config_path, 'r') as f:
        return yaml.safe_load(f)

def main():
    load_dotenv()
    logger.info("Starting Observer Agent Test...")
    
    # 1. Load config
    config = load_config()
    
    # 2. Initialize Observer Agent
    observer = ObserverAgent(config)
    
    try:
        # 3. Perform Observation
        logger.info("Step 1: Running observe()...")
        context = observer.observe()
        
        # 4. Save results for inspection
        from src.utils.json_utils import save_json
        data_dir = config.get('paths', {}).get('data_dir', 'data')
        test_dir = os.path.join(PROJECT_ROOT, data_dir, "test")
        os.makedirs(test_dir, exist_ok=True)
        
        output_file = os.path.join(test_dir, "sample_observer_agent_output.json")
        save_json(context, output_file)
            
        logger.info(f"Step 2: Observation results saved to {output_file}")
        
        # 5. Quick verification
        print("\n--- OBSERVER AGENT TEST SUMMARY ---")
        print(f"Symbol: {context['symbol']}")
        print(f"Price: {context['metrics']['price']['current']}")
        print(f"VAH/POC/VAL: {context['metrics']['volume_profile']}")
        print(f"Macro Chart: {context['chart_path']['snapshot_macro']}")
        print(f"Micro Chart: {context['chart_path']['snapshot_micro']}")
        print("\n--- SEMANTIC OBSERVATIONS ---")
        for obs in context['observations']:
            print(f"- {obs}")
            
    except Exception as e:
        logger.error(f"Observer agent test failed: {e}", exc_info=True)
    finally:
        observer.close()

if __name__ == "__main__":
    main()
