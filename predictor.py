import os
import sys
import argparse
import logging
import json
from datetime import datetime, timezone
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Setup paths
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJECT_ROOT)

from src.agent.observer_agent import ObserverAgent
from src.agent.strategist_agent import StrategistAgent
from src.agent.critic_agent import CriticAgent
from src.utils.agent_utils import load_config
from src.utils.logger_utils import setup_logger
from src.utils.datetime_utils import sanitize_timestamp
from src.utils.json_utils import save_json

# Setup logging
logger = setup_logger("PredictionPipeline")

def run_predictor(symbol: str = "BTCUSDT", override_timestamp: datetime = None, base_dir: str = None):
    """
    Orchestrated Pipeline Execution:
    Directly manages the 'Pure JSON Triad': Observer -> Strategist -> Critic -> Strategist.
    """
    logger.info(f"=== Starting Multi-Agent Prediction Pipeline for {symbol} ===")
    
    config = load_config()
    if base_dir:
        config['paths']['base_dir'] = base_dir

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        logger.error("GEMINI_API_KEY not found in environment")
        return

    try:
        # 1. Initialize Agents
        observer = ObserverAgent(config, symbol, api_key=api_key)
        strategist = StrategistAgent(config, api_key=api_key)
        critic = CriticAgent(config, api_key=api_key)

        # 2. Stage-by-Stage Orchestration
        logger.info("Stage 1/4: Observer (Fact Gathering)")
        observation = observer.observe(override_timestamp)
        
        logger.info("Stage 2/4: Strategist (Drafting)")
        draft = strategist.draft(observation)
        
        logger.info("Stage 3/4: Critic (Adversarial Audit)")
        critique = critic.audit(observation, draft)
        
        logger.info("Stage 4/4: Strategist (Final Synthesis)")
        final_decision = strategist.synthesize(observation, draft, critique)

        # 3. Notification & Result Handling
        session_result = {
            "observation": observation,
            "draft": draft,
            "critique": critique,
            "final_decision": final_decision
        }

        # Decide whether to notify based on confidence
        confidence = final_decision.get('confidence', 0)
        min_confidence = config.get('notifications', {}).get('min_confidence_threshold', 60)
        
        if confidence >= min_confidence:
            logger.info(f"Confidence {confidence}% >= Threshold {min_confidence}%. Triggering notification...")
            _handle_notifications(symbol, session_result, config)
        else:
            logger.info(f"Confidence {confidence}% below threshold. Skipping notification.")

        # 4. Archiving
        _archive_session(symbol, session_result, config, base_dir)

    except Exception as e:
        logger.error(f"Pipeline failed: {e}", exc_info=True)
    finally:
        logger.info("=== Pipeline Complete ===")

def _handle_notifications(symbol, session_result, config):
    """Helper to manage alerts."""
    try:
        from src.utils.notifier import EmailNotifier
        notifier = EmailNotifier(config)
        if notifier.enabled:
            final_decision = session_result["final_decision"]
            chart_paths = session_result["observation"].get("chart_path", {})
            notifier_charts = [p for p in chart_paths.values() if p]
            notifier.send_prediction_alert(symbol, final_decision, chart_paths=notifier_charts)
    except Exception as e:
        logger.error(f"Notification failure: {e}")

def _archive_session(symbol, session_result, config, base_dir):
    """Saves the complete session state."""
    data_root = base_dir or config['paths'].get('data_dir', 'data')
    predictions_dir = config['paths'].get('predictions_dir', 'predictions')
    output_dir = os.path.join(PROJECT_ROOT, data_root, predictions_dir)
    os.makedirs(output_dir, exist_ok=True)
    
    # Use the synchronized timestamp from the observation
    obs_ts = session_result["observation"].get("timestamp", "")
    ts_suffix = sanitize_timestamp(obs_ts)
    output_file = os.path.join(output_dir, f"{symbol}_session_{ts_suffix}.json")
    
    save_json(session_result, output_file)
    logger.info(f"Full Session archived to: {output_file}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Crypto Predictor CLI")
    parser.add_argument("--symbol", type=str, default="BTCUSDT", help="Trading symbol")
    parser.add_argument("--base-dir", type=str, default=None, help="Base directory override")
    args = parser.parse_args()
    
    run_predictor(symbol=args.symbol, base_dir=args.base_dir)
