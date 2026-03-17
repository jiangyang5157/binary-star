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

def run_reviewer_pipeline():
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

    if not os.path.exists(predictions_dir):
        logger.warning(f"No predictions directory found at {predictions_dir}")
        return

    files = [f for f in os.listdir(predictions_dir) if f.endswith(".json")]
    if not files:
        logger.info("No prediction files found to review.")
        return

    bf = BinanceDataFetcher()
    reviewer = ReviewerAgent(
        model_name=config['agent']['model_name'], 
        prompts_dir=os.path.join(PROJECT_ROOT, config['paths']['prompts_dir'])
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
            review_days = 14 
            dt_now = datetime.now(timezone.utc)
            dt_end = dt_start + timedelta(days=review_days)
            
            if dt_end > dt_now:
                dt_end = dt_now
                logger.info(f"Prediction {filename} is recent. Reviewing up to present time.")

            # Minimum 60 seconds for a meaningful outcome check (lowered for immediate testing)
            if (dt_end - dt_start).total_seconds() < 60:
                logger.info(f"Skipping {filename}, too recent to review (< 1 minute).")
                continue

            symbol = config['trading']['symbol']
            logger.info(f"Fetching outcome data for {symbol} starting from {dt_start}")
            
            # Fetch klines from the prediction time until now/end of window
            # Use 1m for very recent reviews to ensure we get data, else 4h
            fetch_interval = "1m" if (dt_end - dt_start).total_seconds() < 12 * 3600 else "4h"
            logger.info(f"Fetching outcome data for {symbol} using {fetch_interval} interval")
            
            klines = bf.fetch_historical_klines(
                symbol=symbol, 
                interval=fetch_interval, 
                limit=500, # Increased limit for 1m data
                startTime=start_ts_ms
            )

            if not klines:
                logger.warning(f"Could not fetch historical outcome for {filename}")
                continue

            entry_price = float(klines[0][1])
            outcome = calculate_outcome(klines, entry_price)

            # 3. Locate matching historical chart
            # We use the same formatting logic as main.py to find the .png
            # prediction['timestamp'] is ISO format: 2026-03-17T00:51:30.355512Z
            ts_iso = prediction.get('timestamp', '')
            chart_path = None
            if ts_iso:
                # Use same logic as ChartGenerator: 20260317_135130
                ts_readable = ts_iso.replace(":", "").replace("-", "").replace("T", "_").split(".")[0]
                chart_filename = f"{symbol}_4h_{ts_readable}_chart.png"
                chart_path = os.path.join(PROJECT_ROOT, config['paths']['images_dir'], chart_filename)
                
                if not os.path.exists(chart_path):
                    logger.warning(f"Matching chart not found: {chart_path}. Reviewer will proceed with text-only.")
                    chart_path = None
                else:
                    logger.info(f"Found matching historical chart: {chart_path}")

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
                    chart_image_path=chart_path
                )

            # 4. Save review
            try:
                parsed_review = json.loads(review_content)
                
                # Final structure of the review:
                # - evaluation_score: 给 Agent A 的判断打分 (0-100)。
                # - flaw_analysis: AI 分析该单盈亏的底层逻辑缺陷或成功要素。
                # - prompt_patch_suggestion: 核心产出：建议写入 TraderAgent 提示词的逻辑补丁。
                final_record = {
                    "prediction_source": filename,
                    "review_timestamp": datetime.now(timezone.utc).isoformat() + "Z",
                    "actual_market_outcome": outcome,
                    "agent_b_analysis": parsed_review
                }
                DataStorage.save_json(final_record, review_path)
                logger.info(f"Successfully saved review to {review_path}")
            except json.JSONDecodeError:
                logger.error(f"Agent B returned invalid JSON for {filename}")

        except Exception as e:
            logger.error(f"Error processing {filename}: {e}")

if __name__ == "__main__":
    run_reviewer_pipeline()
