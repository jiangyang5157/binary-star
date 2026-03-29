#!/usr/bin/env python3
import os
import sys
import argparse
import logging
import json
from typing import Optional, Dict, Any
from dotenv import load_dotenv

# Ensure project root is in path for relative imports
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.agent.strategist_agent import StrategistAgent
from src.agent.critic_agent import CriticAgent
from strategist import run_full_triad_flow, archive_strategy_result
from src.utils.agent_utils import load_config, load_global_config
from src.utils.logger_utils import setup_logger

class StrategyReplayOrchestrator:
    """
    Orchestrates the offline replay pipeline for trading strategies.
    
    This class manages the environment setup, data ingestion, and execution
    of the reasoning triad (Draft -> Audit -> Synthesis) from historical 
    observation files.
    """
    
    def __init__(self, data_root: str):
        """
        Initializes the orchestrator with required configurations and credentials.
        """
        self.logger = setup_logger("StrategyReplay")
        self.config = load_config()
        self.data_root = data_root
        
        load_dotenv()
        self.api_key = os.environ.get("GEMINI_API_KEY")
        
        if not self.api_key:
            self.logger.error("Environment Error: GEMINI_API_KEY not found")
            raise EnvironmentError("Missing GEMINI_API_KEY")

    def execute_session(self, file_path: str):
        """
        Executes a full replay session for a specific observation file.
        """
        self.logger.info(f"--- Starting Offline Replay Session: {os.path.basename(file_path)} ---")
        
        if not os.path.exists(file_path):
            self.logger.error(f"IO Error: Observation file not found at {file_path}")
            return

        try:
            # 1. Ingest Observation Data
            # Note: The source file might be a 'raw' observation or a 'final' strategy result.
            # We must strip any existing AI layers (draft, critique, etc.) to ensure a clean replay.
            raw_data = self._load_observation(file_path)
            
            # Unpack the Forensic Layer if it exists
            if "observation" in raw_data and isinstance(raw_data["observation"], dict):
                observation = raw_data["observation"]
                self.logger.info("Forensic Layer detected. Unpacking inner observation telemetry...")
            else:
                observation = raw_data
                self.logger.info("Raw telemetry detected. Using top-level object...")

            symbol = observation.get('symbol', 'UNKNOWN')
            timestamp = observation.get('timestamp', 'UNKNOWN')
            self.logger.info(f"Loaded high-fidelity observation for {symbol} ({timestamp})")

            # 2. Instantiate Reasoning Agents
            strategist = StrategistAgent(self.config, api_key=self.api_key)
            critic = CriticAgent(self.config, api_key=self.api_key)

            # 3. Execute Reasoning Triad (Draft -> Audit -> Synthesis)
            self.logger.info("Engaging Reasoning Triad (Draft -> Audit -> Synthesis)...")
            # We pass ONLY the observation telemetry to the agents to ensure a fresh reasoning cycle.
            result = run_full_triad_flow(observation, strategist, critic)
            
            # 4. Persistence & Archival
            archive_path = self._persist_result(symbol, timestamp, result)
            self.logger.info(f"Session results archived to: {archive_path}")

        except Exception as e:
            self.logger.error(f"Replay Execution Failed: {e}", exc_info=True)
        finally:
            self.logger.info("--- Replay Session Concluded ---")

    def _load_observation(self, file_path: str) -> Dict[str, Any]:
        """Loads and parses the target observation JSON."""
        with open(file_path, 'r', encoding='utf-8') as f:
            return json.load(f)

    def _persist_result(self, symbol: str, timestamp: str, result: Dict[str, Any]) -> str:
        """Saves the strategy result to the forensic archive."""
        return archive_strategy_result(
            symbol=symbol,
            timestamp=timestamp,
            result=result,
            data_root=self.data_root,
            target_dir="strategies"
        )

def main():
    """CLI entry point for the Strategy Replay Utility."""
    parser = argparse.ArgumentParser(
        description="Strategist Replay - Re-runs the synthesis phase on a saved observation."
    )
    parser.add_argument("--symbol", type=str, help="Trading symbol (e.g., BTCUSDT)")
    parser.add_argument("--file", type=str, required=True, help="Path to the source observation JSON file")
    
    from src.utils.agent_utils import add_data_root_argument, resolve_data_root
    add_data_root_argument(parser)
    
    args = parser.parse_args()
    
    # Resolve data_root
    data_root = args.data_root or resolve_data_root(args.env_shortcut)
    if not data_root:
        print("Error: --data_root or environment shortcut (e.g., prod, live) must be provided.")
        sys.exit(1)
        
    global_cfg = load_global_config()
    symbol = args.symbol or global_cfg['system']['default_symbol']
    
    try:
        orchestrator = StrategyReplayOrchestrator(data_root=data_root)
        orchestrator.execute_session(file_path=args.file)
    except Exception as e:
        print(f"Failed to initialize replay orchestrator: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
