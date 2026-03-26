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
from src.utils.agent_utils import load_config, load_global_config
from src.utils.logger_utils import setup_logger
from src.utils.json_utils import save_json
from src.utils.datetime_utils import parse_iso_to_utc, sanitize_timestamp
from src.utils.path_utils import find_project_root

# Initialize pipeline logger
logger = setup_logger("StrategistOrchestrator")

def run_full_triad_flow(observation: Dict[str, Any], strategist_agent: StrategistAgent, critic_agent: CriticAgent) -> Dict[str, Any]:
    """
    Standardizes the 3-pass reasoning interaction (Triad logic).
    Maintained as a public function for backward compatibility with offline audit scripts.
    """
    logger.info("Triad Step 1/3: Drafting initial strategic plan...")
    draft = strategist_agent.draft(observation)
    
    logger.info("Triad Step 2/3: Performing adversarial audit...")
    critique = critic_agent.audit(observation, draft)
    
    logger.info("Triad Step 3/3: Synthesizing final decision...")
    final_decision = strategist_agent.synthesize(observation, draft, critique)
    
    return {
        "observation": observation,
        "draft": draft,
        "critique": critique,
        "final_decision": final_decision
    }

def archive_strategy_result(symbol: str, timestamp: datetime, result: Any, data_root: str, target_dir: str) -> str:
    """
    Standardized archival for all pipeline results.
    Maintained as a public function for consistency.
    """
    project_root = find_project_root()
    output_dir = os.path.join(project_root, data_root, target_dir)
    os.makedirs(output_dir, exist_ok=True)
    
    ts_str = timestamp.isoformat() if hasattr(timestamp, 'isoformat') else str(timestamp)
    ts_suffix = sanitize_timestamp(ts_str)
    filename = f"{symbol}_{target_dir}_{ts_suffix}.json"
    output_file = os.path.join(output_dir, filename)
    
    save_json(result, output_file)
    return output_file

class StrategistOrchestrator:
    """
    Orchestrates the end-to-end trading intelligence pipeline:
    Observation -> Drafting -> Auditing -> Synthesis -> Notification -> Archival.
    """
    def __init__(self, symbol: str, data_root: str):
        self.symbol = symbol
        self.data_root = data_root
        self.config = load_config()
        
        load_dotenv()
        self.api_key = os.environ.get("GEMINI_API_KEY")
        if not self.api_key:
            raise ValueError("GEMINI_API_KEY not found in environment")
            
        # Initialize specialized agents
        self.observer = ObserverAgent(self.config, symbol, api_key=self.api_key, data_root=data_root)
        self.strategist = StrategistAgent(self.config, api_key=self.api_key)
        self.critic = CriticAgent(self.config, api_key=self.api_key)

    def execute_pipeline(self, timestamp_str: Optional[str] = None):
        """Runs the complete fresh prediction cycle."""
        logger.info(f"=== Starting Trading Pipeline for {self.symbol} ===")
        
        # 1. Prepare temporal context
        timestamp = parse_iso_to_utc(timestamp_str) if timestamp_str else None

        try:
            # 2. Stage 1: Observe (Market Topography)
            logger.info("Stage 1: Gathering market facts...")
            observation = self.observer.observe(timestamp=timestamp, data_root=self.data_root)
            
            # 3. Stages 2-4: Reasoning Triad (Draft -> Audit -> Synthesis)
            session_result = run_full_triad_flow(observation, self.strategist, self.critic)
            
            # 4. Stage 5: Notification (Actionable Alerts)
            self._handle_notifications(session_result)

            # 5. Stage 6: Archival (Forensic History)
            output_file = archive_strategy_result(
                symbol=self.symbol, 
                timestamp=observation.get('timestamp'), 
                result=session_result, 
                data_root=self.data_root, 
                target_dir="strategies"
            )
            logger.info(f"Pipeline complete. Strategy archived at: {output_file}")

        except Exception as e:
            logger.error(f"Pipeline execution failed: {e}", exc_info=True)
        finally:
            logger.info("=== Pipeline Operation Concluded ===")

    def _handle_notifications(self, session_result: Dict[str, Any]):
        """Delegates notification filtering to the Smart Notifier."""
        try:
            from src.infrastructure.notifications.email_notifier import StrategyNotifier
            notifier = StrategyNotifier(data_root=self.data_root)
            notifier.notify_strategy(self.symbol, session_result, save_local=False)
        except Exception as e:
            logger.error(f"Notification service failure: {e}")

def main():
    """CLI entry point for the Trading Orchestrator."""
    parser = argparse.ArgumentParser(description="Strategist Master - Fresh Prediction Pipeline")
    parser.add_argument("--symbol", type=str, help="Trading symbol (e.g., BTCUSDT)")
    parser.add_argument("--timestamp", type=str, help="Optional historical timestamp (ISO)")
    parser.add_argument("--data_root", type=str, required=True, help="Data directory root")
    args = parser.parse_args()
    
    # Load global defaults for missing CLI args
    global_cfg = load_global_config()
    symbol = args.symbol or global_cfg['system']['default_symbol']
    
    if not symbol:
        logger.error("Error: Symbol not provided and no default found in global_config.yaml")
        sys.exit(1)
        
    try:
        orchestrator = StrategistOrchestrator(symbol=symbol, data_root=args.data_root)
        orchestrator.execute_pipeline(timestamp_str=args.timestamp)
    except Exception as e:
        logger.error(f"Failed to initialize orchestrator: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
