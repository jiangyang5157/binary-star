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
from src.agent.coach_agent import CoachAgent

# Setup logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("ReviewerPipeline")

def load_config(config_path: str = "config/config.yaml") -> dict:
    try:
        with open(os.path.join(PROJECT_ROOT, config_path), 'r') as f:
            return yaml.safe_load(f)
    except Exception as e:
        logger.error(f"Failed to load config: {e}")
        return {}

def calculate_outcome(klines: List[List[Any]], entry_price: float) -> Dict[str, Any]:
    """
    Analyzes kline data to determine the actual market outcome.
    
    Metrics Explained:
    - start_price: 预测发出时的开盘价。
    - max_price_reached: 预测周期内的最高价（用于观察是否达到止盈逻辑）。
    - min_price_reached: 预测周期内的最低价（用于观察是否触发止损或遇到强支撑）。
    - final_close_price: 周期结束时的价格。
    - price_change_pct: 最终的累计涨跌幅百分比。
    - max_drawup_pct: 期间最大的浮盈比例（贪婪程度测试）。
    - max_drawdown_pct: 期间最大的回撤比例（风险承受测试）。
    - outcome_period_bars: 实际统计的K线柱数。
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
    
    return {
        "start_price": entry_price,
        "max_price_reached": max_price,
        "min_price_reached": min_price,
        "final_close_price": final_close,
        "price_change_pct": round(price_change_pct, 2),
        "max_drawup_pct": round(max_drawup, 2),
        "max_drawdown_pct": round(max_drawdown, 2),
        "outcome_period_bars": len(klines)
    }

def run_reviewer_pipeline(target_files: List[str] = None, override_now: datetime = None, force: bool = False):
    """
    Main logic for Agent B (The Reviewer):
    1. Scan for past predictions.
    2. Fetch what actually happened from Binance.
    3. Ask Gemini to analyze the gap.
    4. Save the "review" result.
    """
    logger.info("=== Starting Crypto Reviewer Pipeline (Agent B) ===")
    config = load_config()
    if not config:
        return

    predictions_dir = os.path.join(PROJECT_ROOT, config['paths']['raw_data_dir'], "predictions")
    reviews_dir = os.path.join(PROJECT_ROOT, config['paths']['raw_data_dir'], "reviews")
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
    reviewer = ReviewerAgent(
        model_name=config['agent']['reviewer_model'], 
        prompts_dir=os.path.join(PROJECT_ROOT, config['paths']['prompts_dir']),
        temperature=config['agent'].get('reviewer_temperature', 1.0)
    )

    for filename in files:
        pred_path = os.path.join(predictions_dir, filename)
        review_path = os.path.join(reviews_dir, f"review_{filename}")

        # Skip if already reviewed
        if os.path.exists(review_path):
            logger.info(f"Skipping {filename}, already reviewed.")
            continue

        prediction = DataStorage.load_json(pred_path)
        if not prediction or 'timestamp' not in prediction:
            logger.warning(f"Invalid prediction format in {filename}")
            continue

        try:
            # Parse timestamp and ensure it is UTC aware
            ts_str = prediction['timestamp'].replace('Z', '')
            dt_start = datetime.fromisoformat(ts_str).replace(tzinfo=timezone.utc)
            start_ts_ms = int(dt_start.timestamp() * 1000)
            
            # Review outcome window
            review_days = config.get('trading', {}).get('review_window_days', 7)
            dt_now = override_now if override_now else datetime.now(timezone.utc)
            dt_end = dt_start + timedelta(days=review_days)
            if dt_end > dt_now:
                dt_end = dt_now
                logger.info(f"Prediction {filename} is recent. Reviewing up to present time.")

            end_ts_ms = int(dt_end.timestamp() * 1000)

            # Minimum aging protection: Only review if a certain amount of time has passed
            min_delay_hours = config.get('automation', {}).get('minimum_review_age_hours', 168.0)
            if not force and (dt_now - dt_start).total_seconds() < min_delay_hours * 3600:
                logger.info(f"Skipping {filename}, too recent to review (needs {min_delay_hours} hours). Use --force to override.")
                continue

            symbol = config['trading']['symbol']
            logger.info(f"Fetching outcome data for {symbol} starting from {dt_start} to {dt_end}")
            
            # Fetch klines from the prediction time until now/end of window
            # Use interval from config (higher resolution reduces "missed" drawdowns)
            fetch_interval = config['trading'].get('review_evaluation_interval', '1h')
            duration_seconds = (dt_end - dt_start).total_seconds()
            
            # Map interval string to seconds for limit calculation
            interval_map = {
                "1m": 60, "3m": 180, "5m": 300, "15m": 900, "30m": 1800,
                "1h": 3600, "2h": 7200, "4h": 14400, "6h": 21600, "8h": 28800, "12h": 43200, "1d": 86400
            }
            interval_seconds = interval_map.get(fetch_interval, 3600)
            required_limit = int(duration_seconds / interval_seconds) + 1
                
            # Cap at Binance maximum per request (usually 1000-1500)
            target_limit = min(required_limit, 1500)
            
            logger.info(f"Fetching outcome data for {symbol} using {fetch_interval} interval (limit={target_limit})")
            
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
            outcome = calculate_outcome(klines, entry_price)

            # 3. Locate matching historical charts (Macro and Micro)
            ts_iso = prediction.get('timestamp', '')
            chart_paths = []
            if ts_iso:
                # Use same logic as ChartGenerator: 20260317_135130
                ts_readable = ts_iso.replace(":", "").replace("-", "").replace("T", "_").split(".")[0]
                
                # Check for intervals defined in config
                macro_tf = config['trading']['macro_timeframe']['interval']
                micro_tf = config['trading']['micro_timeframe']['interval']
                
                for suffix in [macro_tf, micro_tf]:
                    chart_filename = f"{symbol}_{suffix}_{ts_readable}_chart.png"
                    path = os.path.join(PROJECT_ROOT, config['paths']['images_dir'], chart_filename)
                    if os.path.exists(path):
                        chart_paths.append(path)
                        logger.info(f"Found matching historical {suffix} chart: {path}")
                    else:
                        logger.warning(f"Matching {suffix} chart not found: {path}")

            # 3. Invoke Agent B
            logger.info(f"Invoking Reviewer Agent for {filename}...")
            if not os.environ.get("GEMINI_API_KEY"):
                logger.warning("GEMINI_API_KEY missing. Using mock AI output for verification.")
                review_content = json.dumps({
                    "evaluation_score": 50,
                    "flaw_analysis": "MOCK: Market outcome calculated, but AI analysis requires GEMINI_API_KEY.",
                    "prompt_patch_suggestion": "N/A (Mock Mode)",
                    "config_update_suggestion": {}
                })
            else:
                review_content = reviewer.review(
                    historical_prediction=prediction,
                    actual_outcome=outcome,
                    current_config=config,
                    chart_image_paths=chart_paths
                )

            # 4. Save review
            try:
                parsed_review = json.loads(review_content)
                
                # Final structure of the review:
                # - evaluation_score: 给 Agent A 的判断打分 (0-100)。
                # - flaw_analysis: AI 分析该单盈亏的底层逻辑缺陷或成功要素。
                # - prompt_patch_suggestion: 核心产出：建议写入 TraderAgent 提示词的逻辑补丁。
                final_record = {
                    "prediction": {
                        "source": filename,
                        "content": prediction
                    },
                    "review_timestamp": datetime.now(timezone.utc).isoformat() + "Z",
                    "actual_market_outcome": outcome,
                    "analysis": parsed_review
                }
                DataStorage.save_json(final_record, review_path)
                logger.info(f"Successfully saved review to {review_path}")
            except json.JSONDecodeError:
                logger.error(f"Agent B returned invalid JSON for {filename}")

        except Exception as e:
            logger.error(f"Error processing {filename}: {e}")

def run_coach_pipeline(n: int):
    """
    Main logic for Agent C (The Coach):
    1. Scan for recent reviews of the same symbol.
    2. Load the latest N reviews.
    3. Ask Gemini for strategic patterns.
    4. Save the "coach_report".
    """
    logger.info(f"=== Starting Crypto Coach Pipeline (Agent C) - Batch Size: {n} ===")
    config = load_config()
    if not config:
        return

    symbol = config['trading']['symbol']
    reviews_dir = os.path.join(PROJECT_ROOT, config['paths']['raw_data_dir'], "reviews")
    coach_dir = os.path.join(PROJECT_ROOT, config['paths']['raw_data_dir'], "coach")
    os.makedirs(coach_dir, exist_ok=True)

    # 1. Filter and find latest N review reports for this symbol
    all_reviews_data = []
    if os.path.exists(reviews_dir):
        # We look for review files for this symbol
        # Files are named like review_BTCUSDT_prediction_...
        prefix = f"review_{symbol}"
        for f in sorted(os.listdir(reviews_dir), reverse=True):
            if f.endswith(".json") and f.startswith(prefix):
                path = os.path.join(reviews_dir, f)
                review = DataStorage.load_json(path)
                if review:
                    all_reviews_data.append({"filename": f, "content": review})
                    if n > 0 and len(all_reviews_data) >= n:
                         break

    if not all_reviews_data:
        logger.warning(f"No review reports found for {symbol} in {reviews_dir}")
        return

    # N logic
    available_count = len(all_reviews_data)
    if n > available_count:
        logger.info(f"Requested {n} reviews, but only {available_count} available. Using all.")
        target_items = all_reviews_data
    else:
        logger.info(f"Using latest {n} reviews for {symbol}.")
        target_items = all_reviews_data[:n]

    # 2. Invoke Coach Agent
    coach = CoachAgent(
        model_name=config['agent']['reviewer_model'],
        prompts_dir=os.path.join(PROJECT_ROOT, config['paths']['prompts_dir']),
        temperature=config['agent'].get('reviewer_temperature', 1.0)
    )

    logger.info("Invoking Coach Agent strategic analysis...")
    # Extract only the content for the agent
    coach_content = coach.coaching_session([item["content"] for item in target_items], config)

    # 3. Save report
    timestamp_str = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    report_path = os.path.join(coach_dir, f"coach_{symbol}_{timestamp_str}.json")
    
    try:
        parsed_coach = json.loads(coach_content)
        final_record = {
            "symbol": symbol,
            "sources": [item["filename"] for item in target_items],
            "timestamp": datetime.now(timezone.utc).isoformat() + "Z",
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
    parser = argparse.ArgumentParser(description="Run the Crypto Reviewer Agent B or Coach Agent C.")
    parser.add_argument("--force", action="store_true", help="Bypass the aging protection and review all predictions.")
    parser.add_argument("--batch", type=int, nargs='?', const=-1, help="Run a strategic coaching session for the latest N reviews. Usage: --batch 10")
    args = parser.parse_args()
    
    if args.batch is not None:
        if args.batch == -1:
            print("Error: Please provide a batch size N. Usage: --batch 10")
            sys.exit(1)
        run_coach_pipeline(n=args.batch)
    else:
        run_reviewer_pipeline(force=args.force)
