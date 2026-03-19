import os
import sys
import json
import logging
import yaml
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, List
from dotenv import load_dotenv

# Load environment variables from .env if it exists
load_dotenv()

# Setup paths
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJECT_ROOT)

from src.data_fetcher.binance_client import BinanceDataFetcher
from src.data_fetcher.storage import DataStorage
from src.agent.reviewer_agent import ReviewerAgent

# Setup logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("ReviewPipeline")

def load_config(config_path: str = "config/config.yaml") -> dict:
    try:
        with open(os.path.join(PROJECT_ROOT, config_path), 'r') as f:
            return yaml.safe_load(f)
    except Exception as e:
        logger.error(f"Failed to load config: {e}")
        return {}

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
        action = prediction.get('action', '').upper()
        tp = prediction.get('take_profit')
        sl = prediction.get('stop_loss')
        
        if action in ('BUY', 'SELL') and tp is not None and sl is not None:
            tp, sl = float(tp), float(sl)
            tp_reached = max_price >= tp if action == 'BUY' else min_price <= tp
            sl_reached = min_price <= sl if action == 'BUY' else max_price >= sl
            result["tp_reached"] = tp_reached
            result["sl_reached"] = sl_reached
        elif action == 'HOLD':
            result["tp_reached"] = False
            result["sl_reached"] = False
    
    return result

def main_review(target_files: List[str] = None, override_now: datetime = None, force: bool = False):
    """
    Main logic for Agent B (The Reviewer):
    1. Scan for past predictions.
    2. Fetch what actually happened from Binance.
    3. Ask Gemini to analyze the gap.
    4. Save the "review" result.
    """
    logger.info("=== Starting Crypto Review Pipeline (Agent B) ===")
    config = load_config()
    if not config:
        return

    # Pre-flight check for ALL required keys to enforce Strict Config
    try:
        # Paths
        _ = config['paths']['predictions_dir']
        _ = config['paths']['reviews_dir']
        _ = config['paths']['prompts_dir']
        
        # Symbol
        _ = config['symbol']
        
        # Prediction (used to show horizon in reviews)
        _ = config['prediction']['trade_horizon_days']
        
        # Agent
        _ = config['agent']['reviewer_model']
        _ = config['agent']['review_temperature']
        
        # Review Specific
        _ = config['review']['review_kline_interval']
        _ = config['review']['minimum_review_age_hours']

        # Automation & Intervals
        _ = config['automation']['review_interval_hours']

    except KeyError as e:
        logger.error(f"Config is missing required key: {e}. Please check your config.yaml.")
        return

    predictions_dir = os.path.join(PROJECT_ROOT, config['paths']['predictions_dir'])
    reviews_dir = os.path.join(PROJECT_ROOT, config['paths']['reviews_dir'])
    os.makedirs(reviews_dir, exist_ok=True)

    # Use target_files if provided, otherwise scan directory
    if target_files:
        files = target_files
    else:
        files = [f for f in os.listdir(predictions_dir) if f.endswith(".json")]
    
    if not files:
        logger.info("No prediction files found to review.")
        return

    bf = BinanceDataFetcher()
    try:
        reviewer = ReviewerAgent(
            model_name=config['agent']['reviewer_model'], 
            prompts_dir=os.path.join(PROJECT_ROOT, config['paths']['prompts_dir']),
            temperature=config['agent']['review_temperature']
        )

        for filename in files:
            pred_path = os.path.join(predictions_dir, filename)
            review_path = os.path.join(reviews_dir, f"review_{filename}")

            # Skip if already reviewed, unless forced
            if os.path.exists(review_path) and not force:
                logger.info(f"Skipping {filename}, already reviewed.")
                continue

            prediction = DataStorage.load_json(pred_path)
            if not prediction or 'timestamp' not in prediction:
                logger.warning(f"Invalid prediction format in {filename}")
                continue

            try:
                ts_str = prediction['timestamp']
                dt_start = datetime.fromisoformat(ts_str)
                if dt_start.tzinfo is None:
                    dt_start = dt_start.replace(tzinfo=timezone.utc)
                start_ts_ms = int(dt_start.timestamp() * 1000)
                
                # Review outcome window
                review_days = config['prediction']['trade_horizon_days']
                dt_now = override_now if override_now else datetime.now(timezone.utc)
                dt_end = dt_start + timedelta(days=review_days)
                if dt_end > dt_now:
                    dt_end = dt_now
                    logger.info(f"Prediction {filename} is recent. Reviewing up to present time.")

                end_ts_ms = int(dt_end.timestamp() * 1000)

                min_delay_hours = config['review']['minimum_review_age_hours']
                if not force and (dt_now - dt_start).total_seconds() < min_delay_hours * 3600:
                    logger.info(f"Skipping {filename}, too recent to review (needs {min_delay_hours} hours). Use --force to override.")
                    continue

                symbol = config['symbol']
                logger.info(f"Fetching outcome data for {symbol} starting from {dt_start} to {dt_end}")
                
                fetch_interval = config['review']['review_kline_interval']
                duration_seconds = (dt_end - dt_start).total_seconds()
                
                interval_map = {
                    "1m": 60, "3m": 180, "5m": 300, "15m": 900, "30m": 1800,
                    "1h": 3600, "2h": 7200, "4h": 14400, "6h": 21600, "8h": 28800, "12h": 43200, "1d": 86400
                }
                interval_seconds = interval_map.get(fetch_interval, 3600)
                required_limit = int(duration_seconds / interval_seconds) + 1
                target_limit = min(required_limit, 1500)
                
                klines = bf.fetch_historical_klines(
                    symbol=symbol, 
                    interval=fetch_interval, 
                    limit=target_limit,
                    startTime=start_ts_ms,
                    endTime=end_ts_ms
                )

                if not klines:
                    logger.warning(f"Could not fetch historical outcome for {filename}")
                    continue

                entry_price = float(klines[0][1])
                outcome = calculate_outcome(klines, entry_price, prediction=prediction)

                # Locate matching historical charts (Macro and Micro)
                ts_iso = prediction.get('timestamp', '')
                chart_paths = []
                if ts_iso:
                    # Strip timezone info (Z or +00:00) to match the file naming convention from main.py
                    clean_ts = ts_iso.replace('Z', '').replace('+00:00', '')
                    ts_readable = clean_ts.replace(":", "").replace("-", "").replace("T", "_").split(".")[0]
                    macro_tf = config['prediction']['macro_timeframe']['interval']
                    micro_tf = config['prediction']['micro_timeframe']['interval']
                    
                    for suffix in [macro_tf, micro_tf]:
                        chart_filename = f"{symbol}_{suffix}_{ts_readable}_chart.png"
                        path = os.path.join(PROJECT_ROOT, config['paths']['images_dir'], chart_filename)
                        if os.path.exists(path):
                            chart_paths.append(path)
                
                # Invoke Agent B
                logger.info(f"Invoking Reviewer Agent for {filename}...")
                if not os.environ.get("GEMINI_API_KEY"):
                    logger.warning("GEMINI_API_KEY missing. Using mock AI output.")
                    review_content = json.dumps({
                        "evaluation_score": 50,
                        "tp_sl_result": "NEITHER",
                        "trade_post_mortem": "MOCK: Market outcome calculated, but AI analysis requires API key.",
                        "trade_post_mortem_zh": "由于缺少 API KEY，仅计算了市场结果。"
                    })
                else:
                    prompt_path = os.path.join(PROJECT_ROOT, config['paths']['prompts_dir'], "prompt_trader.txt")
                    base_prompt = ""
                    if os.path.exists(prompt_path):
                        with open(prompt_path, 'r', encoding='utf-8') as f:
                            base_prompt = f.read()

                    review_content = reviewer.review(
                        historical_prediction=prediction,
                        actual_outcome=outcome,
                        config=config,
                        chart_image_paths=chart_paths,
                        base_prompt=base_prompt
                    )

                # Save review
                try:
                    parsed_review = json.loads(review_content)
                    final_record = {
                        "prediction": {
                            "source": filename,
                            "content": prediction
                        },
                        "review_timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                        "actual_market_outcome": outcome,
                        "analysis": parsed_review
                    }
                    DataStorage.save_json(final_record, review_path)
                    logger.info(f"Successfully saved review to {review_path}")
                except (json.JSONDecodeError, TypeError):
                    logger.error(f"Agent B returned invalid JSON content for {filename}")

            except Exception as e:
                logger.error(f"Error processing {filename}: {e}")
    finally:
        bf.close()
        logger.info("=== Review Pipeline Complete ===")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Run the Crypto Review Agent B.")
    parser.add_argument("--force", action="store_true", help="Bypass aging protection.")
    args = parser.parse_args()
    
    main_review(force=args.force)
