#!/usr/bin/env python3
import os
import sys
import argparse
import logging
from datetime import datetime
from typing import Optional, Dict, Any
from dotenv import load_dotenv

# Setup paths
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJECT_ROOT)

from src.agent.observer_agent import ObserverAgent
from src.agent.strategist_agent import StrategistAgent
from src.agent.critic_agent import CriticAgent
from src.utils.agent_utils import load_config
from src.utils.logger_utils import setup_logger
from src.utils.json_utils import save_json
from src.utils.datetime_utils import parse_iso_to_utc

# Setup logging
logger = setup_logger("StrategistPipeline")

def run_full_triad_flow(observation: Dict[str, Any], strategist_agent: StrategistAgent, critic_agent: CriticAgent) -> Dict[str, Any]:
    """
    Standardizes the 3-pass reasoning interaction:
    1. Strategist Drafts
    2. Critic Audits (Adversarial)
    3. Strategist Synthesizes final decision
    """
    logger.info("Triad Step 1/3: Strategist is drafting initial plan...")
    draft = strategist_agent.draft(observation)
    
    logger.info("Triad Step 2/3: Critic is performing adversarial audit...")
    critique = critic_agent.audit(observation, draft)
    
    logger.info("Triad Step 3/3: Strategist is performing final synthesis...")
    final_decision = strategist_agent.synthesize(observation, draft, critique)
    
    return {
        "observation": observation,
        "draft": draft,
        "critique": critique,
        "final_decision": final_decision
    }

def archive_strategy_result(symbol: str, timestamp: datetime, result: Any, data_dir: str, target_dir: str):
    """
    Standardized archival for all pipeline results.
    Ensures synchronized timestamps and directory structure.
    """
    import os
    from src.utils.datetime_utils import sanitize_timestamp
    
    # Resolve directory relative to project root (in case of relative paths)
    from src.utils.path_utils import find_project_root
    project_root = find_project_root()
    output_dir = os.path.join(project_root, data_dir, target_dir)
    os.makedirs(output_dir, exist_ok=True)
    
    ts_str = timestamp.isoformat() if hasattr(timestamp, 'isoformat') else str(timestamp)
    ts_suffix = sanitize_timestamp(ts_str)
    filename = f"{symbol}_{target_dir}_{ts_suffix}.json"
    output_file = os.path.join(output_dir, filename)
    
    save_json(result, output_file)
    return output_file
    
def run_pipeline(symbol: str, timestamp_str: Optional[str] = None, data_dir: Optional[str] = None):
    """
    Main Fresh Pipeline: Observer -> (Draft -> Audit -> Synthesis)
    """
    logger.info(f"=== Starting Fresh Strategist Pipeline for {symbol} ===")
    
    config = load_config()
    # paths_config = config['paths']  # Removed
    load_dotenv()
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        logger.error("GEMINI_API_KEY not found in environment")
        return

    # Parse historical timestamp if provided
    timestamp = None
    if timestamp_str:
        try:
            timestamp = parse_iso_to_utc(timestamp_str)
        except ValueError:
            logger.error(f"Invalid timestamp format: {timestamp_str}")
            return

    # Use "data" as default if data_dir not provided
    final_data_dir = data_dir or "data"

    try:
        # 1. Initialize Agents
        observer = ObserverAgent(config, symbol, api_key=api_key)
        strategist = StrategistAgent(config, api_key=api_key)
        critic = CriticAgent(config, api_key=api_key)

        # 2. Stage 1: Observe
        logger.info(f"Stage 1: Gathering facts for {symbol}...")
        observation = observer.observe(timestamp=timestamp, data_dir=final_data_dir)
        
        # 3. Stages 2-4: Reasoning Triad (Draft -> Audit -> Synthesis)
        result = run_full_triad_flow(observation, strategist, critic)
        
        # 4. Notifications
        _handle_notification(symbol, result, config)

        # 5. Archive
        output_file = archive_strategy_result(
            symbol=symbol, 
            timestamp=observation.get('timestamp'), 
            result=result, 
            data_dir=final_data_dir, 
            target_dir="strategies"
        )
        logger.info(f"Full Strategy archived to: {output_file}")

    except Exception as e:
        logger.error(f"Pipeline failed: {e}", exc_info=True)
    finally:
        logger.info("=== Pipeline Complete ===")

def _handle_notification(symbol, session_result, config):
    """Helper to manage alerts based on confidence."""

    # notification_config = config['notification'] # Singular
    try:
        final_decision = session_result["final_decision"]
        confidence = final_decision.get('confidence', 0)
        min_confidence = config['strategist']['minimum_strategy_confidence_score']
        
        if confidence >= min_confidence:
            logger.info(f"Confidence {confidence}% >= Threshold {min_confidence}%. Triggering notification...")
            from src.utils.notifier import EmailNotifier
            notifier = EmailNotifier(config)
            if notifier.enabled:
                chart_paths = session_result["observation"].get("chart_path", {})
                notifier_charts = [p for p in chart_paths.values() if p]
                notifier.send_prediction_alert(symbol, final_decision, chart_paths=notifier_charts)
        else:
            logger.info(f"Confidence {confidence}% below threshold. Skipping notification.")
    except Exception as e:
        logger.error(f"Notification failure: {e}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Strategist Master - Fresh Prediction Pipeline")
    parser.add_argument("--symbol", type=str, required=True, help="Trading symbol (e.g., BTCUSDT)")
    parser.add_argument("--timestamp", type=str, help="Optional historical timestamp (ISO)")
    parser.add_argument("--data_dir", type=str, help="Data directory override")
    args = parser.parse_args()
    
    run_pipeline(symbol=args.symbol, timestamp_str=args.timestamp, data_dir=args.data_dir)
