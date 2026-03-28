#!/usr/bin/env python3
import os
import sys
import argparse
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Dict, Any
from dotenv import load_dotenv

from src.agent.observer_agent import ObserverAgent
from src.utils.json_utils import save_json
from src.utils.agent_utils import load_config
from src.utils.logger_utils import setup_logger
from src.utils.datetime_utils import parse_iso_to_utc, sanitize_timestamp

# Initialize standardized pipeline logger
logger = setup_logger("ObserverPipeline")


@dataclass(frozen=True)
class ObservationArgs:
    """Type-safe container for command-line arguments."""
    symbol: str
    timestamp_raw: Optional[str]
    data_root: str


class ObservationPersistor:
    """Handles the archival of observation results to the filesystem."""

    @staticmethod
    def save_result(context: Dict[str, Any], symbol: str, data_root: str) -> str:
        """
        Saves the observation JSON to its designated archival path.
        Returns the absolute path of the saved file.
        """
        observations_path = os.path.join(data_root, "observations")
        os.makedirs(observations_path, exist_ok=True)

        # Synchronize filename with the exact timestamp from the generated context
        observation_ts = context.get('timestamp')
        timestamp_clean = sanitize_timestamp(observation_ts)
        filename = f"{symbol}_observations_{timestamp_clean}.json"
        
        final_path = os.path.join(observations_path, filename)
        save_json(context, final_path)
        return final_path


class ObserverCLI:
    """
    Orchestrates the lifecycle of a high-fidelity market observation run.
    """

    def __init__(self, args: ObservationArgs):
        self.args = args
        load_dotenv()
        self.api_key = os.environ.get("GEMINI_API_KEY")
        self.config = load_config()

    def run(self):
        """Executes the observation pipeline end-to-end."""
        if not self.api_key:
            logger.error("Authentication failed: GEMINI_API_KEY not found in environment.")
            return

        at_time = self._parse_target_time()
        if self.args.timestamp_raw and not at_time:
            return # Parsing error already logged

        agent = ObserverAgent(self.config, symbol=self.args.symbol, api_key=self.api_key, data_root=self.args.data_root)
        
        try:
            logger.info(f"Pipeline: Initiating {self.args.symbol} mapping sequence...")
            context = agent.observe(timestamp=at_time, data_root=self.args.data_root)
            
            if "error" in context:
                logger.error(f"Observation failed: {context['error']}")
                return

            saved_path = ObservationPersistor.save_result(context, self.args.symbol, self.args.data_root)
            logger.info(f"Pipeline complete. Snapshot archived at: {saved_path}")

        except Exception as e:
            logger.error(f"Execution Error: {e}", exc_info=True)
        finally:
            agent.close()

    def _parse_target_time(self) -> Optional[datetime]:
        """Parses the raw timestamp string into a UTC-aware datetime."""
        if not self.args.timestamp_raw:
            return None
        try:
            return parse_iso_to_utc(self.args.timestamp_raw)
        except ValueError:
            logger.error(f"Malformed timestamp: {self.args.timestamp_raw}. Use ISO format (YYYY-MM-DDTHH:MM:SS)")
            return None


def main():
    """CLI entry point for standalone market topography."""
    parser = argparse.ArgumentParser(description="Elite Market Topographer CLI")
    parser.add_argument("--symbol", type=str, help="Symbol (e.g., BTCUSDT)")
    parser.add_argument("--timestamp", type=str, help="Optional ISO timestamp")
    
    from src.utils.agent_utils import add_data_root_argument, resolve_data_root
    add_data_root_argument(parser)
    
    args = parser.parse_args()
    
    # Resolve data_root
    data_root = args.data_root or resolve_data_root(args.env_shortcut)
    if not data_root:
        print("Error: --data_root or environment shortcut (e.g., prod, live) must be provided.")
        sys.exit(1)
    
    from src.utils.agent_utils import load_config, load_global_config
    config = load_config()
    global_cfg = load_global_config()
    
    symbol = args.symbol or global_cfg['system']['default_symbol']
    
    import os
    from dotenv import load_dotenv
    load_dotenv()
    api_key = os.environ.get("GEMINI_API_KEY")
    
    observer = ObserverAgent(config, symbol, api_key=api_key, data_root=data_root)
    result = observer.observe(timestamp=args.timestamp, data_root=data_root)
    
    if "error" in result:
        logger.error(f"Observation failed: {result['error']}")
        sys.exit(1)
    
    saved_path = ObservationPersistor.save_result(result, symbol, data_root)
    logger.info(f"Pipeline complete. Snapshot archived at: {saved_path}")


if __name__ == "__main__":
    main()
