import os
import sys
import json
import logging
import yaml
import argparse
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, List
from dotenv import load_dotenv

# Load environment variables from .env if it exists
load_dotenv()

# Setup logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s", stream=sys.stdout)
logger = logging.getLogger("ReviewPipeline")

# Setup paths
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJECT_ROOT)

from src.data_fetcher.binance_client import BinanceDataFetcher
from src.data_fetcher.storage import DataStorage
from src.agent.reviewer_agent import ReviewerAgent

def load_config(config_path: str = "config/config.yaml") -> dict:
    abs_config_path = os.path.join(PROJECT_ROOT, config_path)
    if not os.path.exists(abs_config_path):
        raise FileNotFoundError(f"Config file not found at: {abs_config_path}")
    try:
        with open(abs_config_path, 'r') as f:
            config = yaml.safe_load(f)
            if config is None:
                raise ValueError(f"Config file is empty: {abs_config_path}")
            return config
    except Exception as e:
        logger.error(f"Failed to load config: {e}")
        raise

def calculate_outcome(klines: List[List[Any]], entry_price: float, prediction: Dict[str, Any] = None) -> Dict[str, Any]:
    """
    Analyzes kline data to determine the actual market outcome.
    Optionally pre-computes TP/SL hit hints if prediction data is provided.
    """
    if not klines:
        return {}
    
    # Binance kline structure: [OpenTime, Open, High, Low, Close, Volume, CloseTime, ...]
    highs = [float(k[2]) for k in klines]
    lows = [float(k[3]) for k in klines]
    closes = [float(k[4]) for k in klines]
    
    max_price = max(highs)
    min_price = min(lows)
    final_close = closes[-1]
    
    price_change_pct = ((final_close - entry_price) / entry_price) * 100
    max_drawup = ((max_price - entry_price) / entry_price) * 100
    max_drawdown = ((min_price - entry_price) / entry_price) * 100
    
    result = {
        "start_price": entry_price,
        "max_price_reached": max_price,
        "min_price_reached": min_price,
        "final_close_price": final_close,
        "price_change_pct": round(price_change_pct, 2),
        "max_drawup_pct": round(max_drawup, 2),
        "max_drawdown_pct": round(max_drawdown, 2),
        "outcome_period_bars": len(klines)
    }
    
    # Pre-compute TP/SL hit hints for the Reviewer
    if prediction:
        opinion = prediction.get('opinion', '').upper()
        tp = prediction.get('take_profit')
        sl = prediction.get('stop_loss')
        
        if opinion in ('BULLISH', 'BEARISH') and tp is not None and sl is not None:
            tp, sl = float(tp), float(sl)
            tp_reached = max_price >= tp if opinion == 'BULLISH' else min_price <= tp
            sl_reached = min_price <= sl if opinion == 'BULLISH' else max_price >= sl
            result["tp_reached"] = tp_reached
            result["sl_reached"] = sl_reached
        elif opinion == 'NEUTRAL':
            result["tp_reached"] = False
            result["sl_reached"] = False
    
    return result

def main_review(target_files: List[str] = None, override_now: datetime = None, force: bool = False, base_dir: str = None):
    """
    Agent B Strategy Reviewer:
    1. Scans for archived predictions.
    2. Measures market outcome vs hypothesis.
    3. Triggers ReviewerAgent for post-mortem audit.
    """
    logger.info("=== Starting Crypto Review Pipeline (Agent B) ===")
    config = load_config()
    if base_dir:
        config['paths']['base_dir'] = base_dir

    predictions_dir = os.path.join(PROJECT_ROOT, config['paths']['base_dir'], config['paths']['predictions_dir'])
    reviews_dir = os.path.join(PROJECT_ROOT, config['paths']['base_dir'], config['paths']['reviews_dir'])
    os.makedirs(reviews_dir, exist_ok=True)

    files = target_files or [f for f in os.listdir(predictions_dir) if f.endswith(".json")]
    if not files:
        logger.info("No predictions found for review.")
        return

    bf = BinanceDataFetcher()
    try:
        reviewer = ReviewerAgent(config)

        for filename in files:
            pred_path = os.path.join(predictions_dir, filename)
            review_path = os.path.join(reviews_dir, f"review_{filename}")

            if os.path.exists(review_path) and not force:
                continue

            session = DataStorage.load_json(pred_path)
            # Support both old format (flat) and new format (nested session)
            prediction = session.get("final_decision", session) if "final_decision" in session else session
            
            if 'timestamp' not in prediction:
                continue

            try:
                # 1. Determine Window
                ts_str = prediction['timestamp'].replace('Z', '+00:00')
                dt_start = datetime.fromisoformat(ts_str).replace(tzinfo=timezone.utc)
                dt_now = override_now or datetime.now(timezone.utc)
                
                prediction_horizon = config['prediction']['prediction_horizon_days']
                dt_end = min(dt_start + timedelta(days=prediction_horizon), dt_now)

                min_delay_hours = config['review']['minimum_review_age_hours']
                if not force and (dt_now - dt_start).total_seconds() < min_delay_hours * 3600:
                    logger.info(f"Skipping {filename} (too recent)")
                    continue

                symbol = session.get("observation", {}).get("symbol")
                if not symbol:
                    # Fallback for old files if necessary, but we moved away from config['symbol']
                    logger.warning(f"Skipping {filename} (no symbol found in session)")
                    continue
                    
                logger.info(f"Reviewing {filename} for {symbol}...")
                
                # 2. Fetch Outcome
                fetch_interval = config['review']['review_kline_interval']
                klines = bf.fetch_historical_klines(
                    symbol=symbol, 
                    interval=fetch_interval, 
                    startTime=int(dt_start.timestamp() * 1000),
                    endTime=int(dt_end.timestamp() * 1000)
                )

                if not klines:
                    continue

                outcome = calculate_outcome(klines, float(klines[0][1]), prediction=prediction)

                # 3. Handle Multimodal Context (Look for archived charts)
                chart_paths = []
                obs = session.get("observation", {})
                if "chart_path" in obs:
                    for p in obs["chart_path"].values():
                        if not p: continue
                        abs_p = os.path.join(PROJECT_ROOT, p)
                        if os.path.exists(abs_p):
                            chart_paths.append(abs_p)

                # 4. Invoke AI Audit
                review_content = reviewer.review(
                    historical_prediction=session, 
                    actual_outcome=outcome,
                    chart_image_paths=chart_paths
                )

                # 5. Save Result
                parsed_review = json.loads(review_content)
                final_record = {
                    "prediction_source": filename,
                    "review_timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                    "actual_market_outcome": outcome,
                    "analysis": parsed_review
                }
                
                DataStorage.save_json(final_record, review_path)
                logger.info(f"Review archived: {review_path}")

            except Exception as e:
                logger.error(f"Error reviewing {filename}: {e}")
    finally:
        bf.close()
        logger.info("=== Review Pipeline Complete ===")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run the Crypto Review Agent B.")
    parser.add_argument("--force", action="store_true", help="Bypass aging protection.")
    parser.add_argument("--base-dir", type=str, default=None, help="Base directory override")
    args = parser.parse_args()
    
    main_review(force=args.force, base_dir=args.base_dir)
