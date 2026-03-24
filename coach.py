import os
import sys
import json
import logging
import yaml
from datetime import datetime, timezone
from typing import Dict, Any, List
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Setup paths
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJECT_ROOT)

from src.data_fetcher.storage import DataStorage
from src.agent.coach_agent import CoachAgent

# Setup logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s", stream=sys.stdout)
logger = logging.getLogger("CoachPipeline")

def load_config(config_path: str = "config/config.yaml") -> dict:
    abs_config_path = os.path.join(PROJECT_ROOT, config_path)
    if not os.path.exists(abs_config_path):
        raise FileNotFoundError(f"Config file not found at: {abs_config_path}")
    try:
        with open(abs_config_path, 'r') as f:
            config = yaml.safe_load(f)
            if config is None:
                raise ValueError(f"Config file is empty: {abs_config_path}")
            
        # Pre-flight check for ALL required keys to enforce Strict Config
        try:
            # Paths
            data_dir = "data"
            _ = os.path.exists(os.path.join(PROJECT_ROOT, data_dir))
            
            # Symbol
            _ = config['symbol']
            
            # Agent
            _ = config['coach']['model']
            _ = config['coach']['temperature']
            
            # Automation & Intervals
            _ = config['automation']['review_interval_hours']
        except KeyError as e:
            error_msg = f"Config is missing required key: {e}. Please check your config.yaml."
            logger.error(error_msg)
            raise RuntimeError(error_msg) from e
            
        return config
    except Exception as e:
        logger.error(f"Failed to load config or missing required key: {e}")
        raise

def run_coach_pipeline(n: int, base_dir: str = None):
    """
    Main logic for Agent C (The Coach):
    1. Scan for recent reviews of the same symbol.
    2. Load the latest N reviews.
    3. Ask Gemini for strategic patterns.
    4. Save the "coach_report".
    """
    if n <= 0:
        logger.warning(f"Invalid batch size: {n}. Must be a positive integer. Aborting.")
        return

    logger.info(f"=== Starting Crypto Coach Pipeline (Agent C) - Batch Size: {n} ===")
    config = load_config()
    if not config:
        return

    data_dir = base_dir or "data"

    symbol = config['symbol']
    reviews_dir = os.path.join(PROJECT_ROOT, data_dir, "reviews")
    coach_dir = os.path.join(PROJECT_ROOT, data_dir, "coaches")
    os.makedirs(coach_dir, exist_ok=True)

    # 1. Filter and find latest N review reports for this symbol
    all_reviews_data = []
    if os.path.exists(reviews_dir):
        prefix = f"review_{symbol}"
        for f in sorted(os.listdir(reviews_dir), reverse=True):
            if f.endswith(".json") and f.startswith(prefix):
                path = os.path.join(reviews_dir, f)
                review = DataStorage.load_json(path)
                if review:
                    all_reviews_data.append({"filename": f, "content": review})
                    if len(all_reviews_data) >= n:
                         break

    if not all_reviews_data:
        logger.warning(f"No review reports found for {symbol} in {reviews_dir}")
        return

    # 2. Invoke Coach Agent
    coach_config = config['coach']
    coach = CoachAgent(
        model_name=coach_config['model'], 
        prompt_path=os.path.join(PROJECT_ROOT, coach_config['prompt_path']),
        temperature=coach_config['temperature']
    )

    logger.info("Invoking Coach Agent strategic analysis...")
    base_prompt_path = os.path.join(PROJECT_ROOT, config['strategist']['prompt_path'])
    base_prompt = ""
    if os.path.exists(base_prompt_path):
        with open(base_prompt_path, 'r', encoding='utf-8') as f:
            base_prompt = f.read()

    # Extract only the content for the agent
    target_reviews = all_reviews_data[:n] if n > 0 else all_reviews_data
    coach_content = coach.coaching_session(
        [item["content"] for item in target_reviews], 
        config,
        base_prompt
    )

    # 3. Save report
    timestamp_str = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    report_path = os.path.join(coach_dir, f"coach_{symbol}_{timestamp_str}.json")
    
    try:
        parsed_coach = json.loads(coach_content)
        if isinstance(parsed_coach, list) and len(parsed_coach) > 0:
            parsed_coach = parsed_coach[0]
            
        final_record = {
            "symbol": symbol,
            "sources": [item["filename"] for item in target_reviews],
            "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "analysis": parsed_coach
        }
        DataStorage.save_json(final_record, report_path)
        logger.info(f"Successfully saved Coach Report to {report_path}")
    except json.JSONDecodeError:
        logger.error("Coach Agent returned invalid JSON. Saving raw output as fallback.")
        with open(report_path.replace(".json", ".txt"), 'w', encoding='utf-8') as f:
            f.write(coach_content)

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Run the Crypto Coach Agent C.")
    parser.add_argument("--batch", type=int, required=True, help="Number of recent reviews to analyze (must be > 0).")
    parser.add_argument("--base-dir", type=str, default=None, help="Base directory override (e.g., 'samples').")
    args = parser.parse_args()
    
    run_coach_pipeline(n=args.batch, base_dir=args.base_dir)
