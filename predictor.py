import os
import sys
import yaml
import json
import logging
import argparse
from datetime import datetime, timezone
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Setup paths
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJECT_ROOT)

from src.agent.predictor_agent import PredictorAgent
from src.data_fetcher.storage import DataStorage
from src.utils.agent_utils import load_config
from src.utils.logger_utils import setup_logger

# Setup logging
logger = setup_logger("PredictionPipeline")


def run_predictor(symbol: str = "BTCUSDT", override_timestamp: datetime = None, base_dir: str = None):
    """
    Orchestrated Pipeline Execution:
    1. Initialize PredictorAgent (Orchestrator).
    2. Run the 3-Agent Cycle (Observer -> Strategist -> Critic -> Strategist).
    3. Handle Notifications and Storage.
    """
    logger.info(f"=== Starting Multi-Agent Prediction Pipeline for {symbol} ===")
    
    config = load_config()
    if base_dir:
        config['paths']['base_dir'] = base_dir

    try:
        # 1. Initialize Orchestrator with mandatory parameters
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("GEMINI_API_KEY not found in environment")
            
        agent = PredictorAgent(config, symbol, api_key=api_key)
        
        # 2. Execute Full Cycle (symbol no longer needed here)
        session_result = agent.run_cycle(
            override_timestamp=override_timestamp
        )
        
        if "error" in session_result:
            logger.error(f"Pipeline execution aborted: {session_result['error']}")
            return

        final_decision = session_result.get("final_decision", {})
        
        # 3. Notification Logic
        try:
            from src.utils.notifier import EmailNotifier
            notifier = EmailNotifier(config)
            
            if notifier.enabled:
                confidence = final_decision.get('confidence', 0)
                min_confidence = config['notifications']['min_confidence_threshold']
                
                if confidence >= min_confidence:
                    # Note: chart_path is inside observation
                    chart_paths = session_result["observation"].get("chart_path", {})
                    # Convert dict values to list for notifier
                    notifier_charts = [p for p in chart_paths.values() if p]
                    
                    notifier.send_prediction_alert(symbol, final_decision, chart_paths=notifier_charts)
        except Exception as e:
            logger.error(f"Notification failure: {e}")

        # 4. Save the Unified Global Review JSON
        logger.info("Final Step: Archiving Global Review...")
        data_root = base_dir or config['paths']['base_dir']
        output_dir = os.path.join(PROJECT_ROOT, data_root, config['paths']['predictions_dir'])
        os.makedirs(output_dir, exist_ok=True)
        
        ts_str = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        output_file = os.path.join(output_dir, f"{symbol}_global_review_{ts_str}.json")
        
        DataStorage.save_json(session_result, output_file)
        logger.info(f"Full Session archived to: {output_file}")
        
    except Exception as e:
        logger.error(f"Pipeline failed: {e}", exc_info=True)
    finally:
        logger.info("=== Pipeline Complete ===")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Crypto Predictor CLI")
    parser.add_argument("--base-dir", type=str, default=None, help="Base directory override")
    args = parser.parse_args()
    
    run_predictor(base_dir=args.base_dir)
