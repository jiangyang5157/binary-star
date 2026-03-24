import os
import sys
import json
import logging
import yaml
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional
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
            
        # Pre-flight check for ONLY required keys for Coach
        try:
            _ = config['coach']['model']
            _ = config['coach']['temperature']
        except KeyError as e:
            error_msg = f"Config is missing required key for Coach: {e}. Please check your config.yaml."
            logger.error(error_msg)
            raise RuntimeError(error_msg) from e
            
        return config
    except Exception as e:
        logger.error(f"Failed to load config: {e}")
        raise

def run_coach_pipeline(symbol: Optional[str] = None, batch_size: Optional[int] = None, base_dir: Optional[str] = None):
    """
    Main logic for Agent C (The Coach):
    1. Scan for all reviews of the specified symbol.
    2. Load strategist and critic prompts as context.
    3. Invoke Coach Agent for systemic analysis.
    4. Save the "coach_report".
    """
    logger.info(f"=== Starting Crypto Coach Pipeline (Agent C) ===")
    config = load_config()
    if not config:
        return

    data_dir = base_dir or "data"
    symbol = symbol or config.get('symbol', 'BTCUSDT')
    reviews_dir = os.path.join(PROJECT_ROOT, data_dir, "reviews")
    coach_dir = os.path.join(PROJECT_ROOT, data_dir, "coaches")
    os.makedirs(coach_dir, exist_ok=True)

    # 1. Filter and find latest N review reports for this symbol
    all_reviews_context = []
    if os.path.exists(reviews_dir):
        prefix = f"review_{symbol}_strategies_"
        files = sorted([f for f in os.listdir(reviews_dir) if f.endswith(".json") and f.startswith(prefix)], reverse=True)
        
        # If batch_size is provided, limit the number of reports
        if batch_size and batch_size > 0:
            files = files[:batch_size]
            
        for f in files:
            path = os.path.join(reviews_dir, f)
            review = DataStorage.load_json(path)
            if review:
                all_reviews_context.append({"filename": f, "content": review})

    if not all_reviews_context:
        logger.warning(f"No review reports found for {symbol} in {reviews_dir}")
        return

    # 2. Load Prompts and Config
    def read_prompt(path):
        abs_path = os.path.join(PROJECT_ROOT, path)
        if os.path.exists(abs_path):
            with open(abs_path, 'r', encoding='utf-8') as f:
                return f.read()
        return ""

    strategist_prompt = read_prompt(config['strategist']['prompt_path'])
    critic_prompt = read_prompt(config['critic']['prompt_path'])

    # 3. Invoke Coach Agent
    coach_config = config['coach']
    api_key = os.environ.get("GEMINI_API_KEY")
    coach = CoachAgent(
        model_name=coach_config['model'], 
        prompt_path=os.path.join(PROJECT_ROOT, coach_config['prompt_path']),
        temperature=coach_config['temperature'],
        api_key=api_key
    )

    logger.info(f"Invoking Coach Agent for symbol: {symbol} ({len(all_reviews_context)} reports)...")
    coach_content = coach.coaching_session(
        [item["content"] for item in all_reviews_context],
        config, # Full config as requested
        strategist_prompt,
        critic_prompt
    )

    # 4. Save report
    timestamp_str = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    report_path = os.path.join(coach_dir, f"coach_{symbol}_{timestamp_str}.json")
    
    try:
        parsed_coach_analysis = json.loads(coach_content)
        
        # Standardize the output JSON as requested
        final_record = {
            "sources": sorted([item["filename"] for item in all_reviews_context]),
            "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "analysis": parsed_coach_analysis
        }
        
        # If the agent returned a wrapped analysis (sometimes it adds its own wrapper), unwrap it
        if "analysis" in parsed_coach_analysis and len(parsed_coach_analysis) == 3:
             # If it already follows the schema, use it directly
             final_record = parsed_coach_analysis
             final_record["timestamp"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

        DataStorage.save_json(final_record, report_path)
        logger.info(f"Successfully saved Coach Report to {report_path}")
    except json.JSONDecodeError:
        logger.error("Coach Agent returned invalid JSON. Saving raw output as fallback.")
        with open(report_path.replace(".json", ".txt"), 'w', encoding='utf-8') as f:
            f.write(coach_content)

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Run the Crypto Coach Agent C.")
    parser.add_argument("--symbol", type=str, help="Symbol to analyze (defaults to config).")
    parser.add_argument("--batch", type=int, help="Optional: Number of recent reviews to analyze.")
    parser.add_argument("--base-dir", type=str, default=None, help="Base directory override (e.g., 'samples').")
    args = parser.parse_args()
    
    run_coach_pipeline(symbol=args.symbol, batch_size=args.batch, base_dir=args.base_dir)
