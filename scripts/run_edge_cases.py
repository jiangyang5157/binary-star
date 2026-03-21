import sys
import json
import logging
from pathlib import Path
from datetime import datetime, timedelta

# Make sure we can import from the root module
sys.path.append(str(Path(__file__).parent.parent))

from src.pipeline.predictor import run_from_simulator as run_predictor
from src.pipeline.review import review_historical_predictions as run_reviewer_pipeline
from src.utils.logger import setup_logging
import yaml

setup_logging(log_file="edge_cases.log", level=logging.INFO, force=True)
logger = logging.getLogger(__name__)

def run_edge_cases(manifest_path="tests/edge_cases/manifest.json"):
    with open("config/config.yaml", "r") as f:
        config = yaml.safe_load(f)

    path = Path(manifest_path)
    if not path.exists():
        logger.error(f"Manifest not found at {manifest_path}")
        return

    with open(path, 'r') as f:
        manifest = json.load(f)

    samples = manifest.get('samples', [])
    logger.info(f"Loaded {len(samples)} edge cases from manifest.")

    for i, sample in enumerate(samples, 1):
        timestamp_str = sample['timestamp']
        try:
            dt = datetime.strptime(timestamp_str, "%Y-%m-%dT%H:%M:%SZ")
        except ValueError:
            logger.error(f"Invalid timestamp {timestamp_str}")
            continue

        logger.info(f"\n--- RE-TESTING EDGE CASE {i}/{len(samples)}: {dt} ---")
        
        symbol = sample.get('symbol', 'BTCUSDT')
        pred_filename = f"{symbol}_prediction_{dt.strftime('%Y%m%d_%H%M%S')}.json"
        
        try:
            # 1. Run Predictor Agent
            run_predictor(override_timestamp=dt)
            logger.info(f"Successfully finished prediction: {pred_filename}")
            
            # 2. Run Reviewer
            review_days = config['prediction']['prediction_horizon_days']
            future_dt = dt + timedelta(days=review_days)
            logger.info(f"Fast-forwarding to {future_dt} for review...")
            
            run_reviewer_pipeline(target_files=[pred_filename], override_now=future_dt, force=True)
            logger.info(f"Successfully finished review for: {pred_filename}")
            
        except Exception as e:
            logger.error(f"Edge case testing failed for {dt}: {e}")

    logger.info("\n=== Edge Case Testing Complete ===")

if __name__ == "__main__":
    run_edge_cases()
