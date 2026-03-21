import os
import json
import logging
import yaml
from pathlib import Path

# Setup logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("SampleCleanup")

def load_config(config_path: str = "config/config.yaml") -> dict:
    if not os.path.exists(config_path):
        raise FileNotFoundError(f"Config file not found at: {config_path}")
    with open(config_path, 'r') as f:
        return yaml.safe_load(f)

def cleanup_samples(score_threshold: int = 75):
    """
    Removes "solved" samples from the samples/ directory.
    A sample is solved if the latest review shows TP_HIT or a high evaluation score.
    """
    config = load_config()
    paths = config.get('paths', {})
    
    samples_dir = Path("samples")
    preds_dir = samples_dir / paths.get('predictions_dir', 'predictions')
    revs_dir = samples_dir / paths.get('reviews_dir', 'reviews')
    imgs_dir = samples_dir / paths.get('images_dir', 'images')

    if not revs_dir.exists():
        logger.warning(f"Reviews directory not found: {revs_dir}")
        return

    removed_count = 0
    
    # Iterate through all reviews in samples/reviews
    for review_file in revs_dir.glob("review_*.json"):
        try:
            with open(review_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except Exception as e:
            logger.error(f"Failed to load {review_file}: {e}")
            continue

        analysis = data.get('analysis', {})
        if not isinstance(analysis, dict):
            continue

        result = analysis.get('tp_sl_result', 'NEITHER')
        score = analysis.get('evaluation_score', 0)
        
        # Logic: Remove if TP_HIT or high score
        if result == 'TP_HIT' or score > score_threshold:
            logger.info(f"Sample solved: {review_file.name} (Result: {result}, Score: {score})")
            
            # Identify associated prediction and images
            # review_BTCUSDT_prediction_20260321_000000.json -> BTCUSDT_prediction_20260321_000000.json
            pred_filename = review_file.name.replace("review_", "")
            pred_path = preds_dir / pred_filename
            
            # Extract symbol and timestamp for image search
            # BTCUSDT_prediction_20260321_000000.json
            parts = pred_filename.replace(".json", "").split("_prediction_")
            if len(parts) == 2:
                symbol = parts[0]
                timestamp = parts[1] # e.g. 20260321_000000
                
                # Image format: {symbol}_{tf}_{timestamp}Z_chart.png
                for tf in ['15m', '1h']:
                    img_filename = f"{symbol}_{tf}_{timestamp}Z_chart.png"
                    img_path = imgs_dir / img_filename
                    if img_path.exists():
                        os.remove(img_path)
                        logger.info(f"  Removed image: {img_filename}")

            # Remove prediction and review
            if pred_path.exists():
                os.remove(pred_path)
                logger.info(f"  Removed prediction: {pred_filename}")
            
            os.remove(review_file)
            logger.info(f"  Removed review: {review_file.name}")
            
            removed_count += 1

    if removed_count > 0:
        logger.info(f"=== Cleanup Complete: Removed {removed_count} solved sample(s) ===")
    else:
        logger.info("=== Cleanup Complete: No solved samples found ===")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Cleanup solved samples from the training set.")
    parser.add_argument("--score", type=int, default=75, help="Score threshold for removal (default 75)")
    args = parser.parse_args()
    
    cleanup_samples(score_threshold=args.score)
