import sys
import logging
from pathlib import Path
from datetime import datetime, timedelta
import yaml
import re

# Append root to path
sys.path.append(str(Path(__file__).parent.parent))

from src.pipeline.predictor import run_from_simulator as run_predictor
from src.pipeline.review import review_historical_predictions as run_reviewer_pipeline
from src.utils.logger import setup_logging

setup_logging(log_file="samples/samples.log", level=logging.INFO, force=True)
logger = logging.getLogger(__name__)

def get_timestamps_from_predictions(pred_dir):
    timestamps = []
    
    path = Path(pred_dir)
    if not path.exists():
        return timestamps
        
    for pred_file in path.glob("*_prediction_*.json"):
        # Format: BTCUSDT_prediction_20260312_000000.json
        match = re.search(r'([A-Z]+)_prediction_(\d{8}_\d{6})\.json', pred_file.name)
        if match:
            sym = match.group(1)
            time_str = match.group(2)
            try:
                dt = datetime.strptime(time_str, "%Y%m%d_%H%M%S")
                timestamps.append((dt, sym))
            except ValueError:
                pass
                
    # Sort chronologically
    timestamps.sort(key=lambda x: x[0])
    return timestamps

def run_samples():
    with open("config/config.yaml", "r") as f:
        config = yaml.safe_load(f)

    predictions_dir = "samples/predictions"
    timestamps = get_timestamps_from_predictions(predictions_dir)

    if not timestamps:
        logger.error(f"No samples found in {predictions_dir}")
        return

    logger.info(f"Loaded {len(timestamps)} samples.")

    for i, (dt, symbol) in enumerate(timestamps, 1):
        logger.info(f"\n--- RE-TESTING SAMPLE {i}/{len(timestamps)}: {dt} ---")
        
        pred_filename = f"{symbol}_prediction_{dt.strftime('%Y%m%d_%H%M%S')}.json"
        
        try:
            # 1. Predictor
            # Ensure images go to normal data/images
            run_predictor(override_timestamp=dt, base_dir="samples")
            logger.info(f"Successfully finished prediction: {pred_filename}")
            
            # 2. Reviewer
            review_days = config['prediction']['prediction_horizon_days']
            future_dt = dt + timedelta(days=review_days)
            logger.info(f"Fast-forwarding to {future_dt} for review...")
            
            run_reviewer_pipeline(target_files=[pred_filename], override_now=future_dt, force=True, base_dir="samples")
            logger.info(f"Successfully finished review for: {pred_filename}")
            
        except Exception as e:
            logger.error(f"Sample testing failed for {dt}: {e}")

    logger.info("\n=== Sample Testing Complete ===")

if __name__ == "__main__":
    run_samples()
