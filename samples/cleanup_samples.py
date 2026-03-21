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

def cleanup_samples():
    """
    Removes "solved" samples from the samples/ directory.
    A sample is solved if the latest review shows TP_HIT or a high evaluation score.
    """
    config = load_config()
    samples_dir = Path("samples")
    
    # Strictly enforce configuration paths
    try:
        paths = config['paths']
        preds_dir = samples_dir / paths['predictions_dir']
        revs_dir = samples_dir / paths['reviews_dir']
        imgs_dir = samples_dir / paths['images_dir']
    except KeyError as e:
        error_msg = f"Config is missing required path key: {e}. Please check your config.yaml."
        logger.error(error_msg)
        raise RuntimeError(error_msg)

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
        if result == 'TP_HIT' or score > 75:
            logger.info(f"Sample solved: {review_file.name} (Result: {result}, Score: {score})")
            
            # Identify associated prediction and images
            pred_filename = review_file.name.replace("review_", "")
            pred_path = preds_dir / pred_filename
            
            # Extract symbol and timestamp for image search
            parts = pred_filename.replace(".json", "").split("_prediction_")
            if len(parts) == 2:
                symbol = parts[0]
                timestamp = parts[1]
                
                # Image format: {symbol}_{tf}_{timestamp}Z_chart.png
                for tf in ['15m', '1h']:
                    img_filename = f"{symbol}_{tf}_{timestamp}Z_chart.png"
                    img_path = imgs_dir / img_filename
                    if img_path.exists():
                        try:
                            img_path.unlink()
                            logger.info(f"  Removed image: {img_filename}")
                        except Exception as e:
                            logger.error(f"  Failed to remove image {img_filename}: {e}")

            # Remove prediction and review
            if pred_path.exists():
                try:
                    pred_path.unlink()
                    logger.info(f"  Removed prediction: {pred_filename}")
                except Exception as e:
                    logger.error(f"  Failed to remove prediction {pred_filename}: {e}")
            
            try:
                review_file.unlink()
                logger.info(f"  Removed review: {review_file.name}")
            except Exception as e:
                logger.error(f"  Failed to remove review {review_file.name}: {e}")
            
            removed_count += 1

    if removed_count > 0:
        logger.info(f"=== Cleanup Complete: Removed {removed_count} solved sample(s) ===")
    else:
        logger.info("=== Cleanup Complete: No solved samples found ===")

if __name__ == "__main__":
    cleanup_samples()
