import os
import sys
import logging
from datetime import datetime
from dotenv import load_dotenv

# Ensure project root is in path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.agent.observer_agent import ObserverAgent
from src.utils.agent_utils import load_config
from src.utils.json_utils import save_json
from src.utils.datetime_utils import get_utc_now, sanitize_timestamp, to_iso_zulu

# Setup basic logging for the test
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("TestObserverLive")

def test_observer_agent_live():
    """
    Live integration test for ObserverAgent.
    Fetches real data from Binance and uses Gemini for synthesis.
    """
    load_dotenv()
    
    symbol = "BTCUSDT"
    data_root = "data/test"
    api_key = os.environ.get("GEMINI_API_KEY")
    
    if not api_key:
        logger.error("GEMINI_API_KEY not found in environment. Please check your .env file.")
        return

    logger.info(f"Initializing ObserverAgent for {symbol} with data_root={data_root}")
    
    try:
        # Load standard configuration
        config = load_config()
        
        # Initialize the agent
        agent = ObserverAgent(config, symbol=symbol, api_key=api_key, data_root=data_root)
        
        # Capture current UTC time for the observation
        timestamp = get_utc_now()
        logger.info(f"Starting observation at {to_iso_zulu(timestamp)}")
        
        # Execute observation
        context = agent.observe(timestamp=timestamp)
        
        # Verify basic structure
        required_keys = ["symbol", "timestamp", "observation_specs", "visual_assets", "quantitative_metrics", "semantic_analysis"]
        for key in required_keys:
            if key not in context:
                logger.error(f"Missing required key in observation result: {key}")
            else:
                logger.info(f"Verified key: {key}")

        # Save the result to {data_root}/observations/
        observations_path = os.path.join(data_root, "observations")
        os.makedirs(observations_path, exist_ok=True)
        
        # Use synchronized timestamp for filename
        observation_ts = context.get('timestamp')
        timestamp_clean = sanitize_timestamp(observation_ts)
        output_filename = f"{symbol}_observations_{timestamp_clean}.json"
        final_path = os.path.join(observations_path, output_filename)
        
        # Save using the standard utility
        save_json(context, final_path)
        logger.info(f"Observation successful. Result saved to: {final_path}")
        
        # Final cleanup
        agent.close()
        logger.info("Test completed successfully.")
        
        return final_path

    except Exception as e:
        logger.error(f"Test failed with error: {e}", exc_info=True)
        return None

if __name__ == "__main__":
    result_path = test_observer_agent_live()
    if result_path:
        print(f"\nSUCCESS: Result saved to {result_path}")
    else:
        print("\nFAILURE: Test did not complete successfully.")
        sys.exit(1)
