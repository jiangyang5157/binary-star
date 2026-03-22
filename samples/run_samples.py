import sys
import logging
import yaml
import re
from pathlib import Path
from datetime import datetime, timedelta, timezone

# Configure logging FIRST before any other imports that might set up logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("samples.log"),
        logging.StreamHandler(sys.stdout)
    ],
    force=True  # Important: Force clear any existing config from other modules
)

# Append root to path
sys.path.append(str(Path(__file__).parent.parent))

from predictor import run_predictor
from review import main_review as run_reviewer_pipeline
from coach import run_coach_pipeline

logger = logging.getLogger(__name__)

def get_timestamps_from_predictions(pred_dir):
    timestamps = []
    
    path = Path(pred_dir)
    if not path.exists():
        return timestamps
        
    for pred_file in path.glob("*_prediction_*.json"):
        match = re.search(r'([A-Z]+)_prediction_(\d{8}_\d{6})\.json', pred_file.name)
        if match:
            sym = match.group(1)
            time_str = match.group(2)
            try:
                dt = datetime.strptime(time_str, "%Y%m%d_%H%M%S").replace(tzinfo=timezone.utc)
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
            # Predictor will save images and predictions into samples/ due to base_dir
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
    
    # 3. Automatic Coaching
    logger.info("\n--- AUTOMATIC COACHING ON SAMPLES ---")
    run_coach_pipeline(n=len(timestamps), base_dir="samples")
    logger.info("=== All Pipelines Finished ===")

if __name__ == "__main__":
    run_samples()
