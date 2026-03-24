import os
import sys
import json
import logging
import yaml
import argparse
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, List, Optional
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
from src.agent.observer_agent import ObserverAgent

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

def calculate_outcome(klines: List[List[Any]], entry_price: float, prediction: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Analyzes kline data to determine the actual market outcome.
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

def main_review(target_files: Optional[List[str]] = None, override_now: Optional[datetime] = None, force: bool = False, base_dir: Optional[str] = None):
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

    base_sub = config['paths'].get('data_dir', '')
    potential_strat_dirs = [
        config['paths'].get('strategies_dir', 'strategies'),
        config['paths'].get('predictions_dir', 'predictions'),
        'strategies',
        'predictions'
    ]
    
    predictions_dir = None
    for d in potential_strat_dirs:
        p = os.path.join(PROJECT_ROOT, base_sub, d)
        if os.path.isdir(p):
            predictions_dir = p
            break
            
    if not predictions_dir:
        logger.error(f"Could not find strategy directory in {os.path.join(PROJECT_ROOT, base_sub)}")
        return

    reviews_dir = os.path.join(PROJECT_ROOT, base_sub, config['paths'].get('reviews_dir', 'reviews'))
    os.makedirs(reviews_dir, exist_ok=True)

    files = target_files or [f for f in os.listdir(predictions_dir) if f.endswith(".json")]
    if not files:
        logger.info("No predictions found for review.")
        return

    bf = BinanceDataFetcher()
    try:
        reviewer = ReviewerAgent(config)
        observers = {}
        api_key = os.environ.get("GEMINI_API_KEY")

        for filename in files:
            pred_path = os.path.join(predictions_dir, filename)
            review_path = os.path.join(reviews_dir, f"review_{filename}")

            if os.path.exists(review_path) and not force:
                continue

            if not os.path.exists(pred_path):
                logger.warning(f"File not found: {pred_path}")
                continue

            session = DataStorage.load_json(pred_path)
            # Use nested session if available
            prediction = session.get("final_decision", session)
            limit_order = prediction.get("limit_order") or {}
            
            timestamp_str = session.get('observation', {}).get('timestamp') or prediction.get('timestamp')
            if not timestamp_str:
                logger.warning(f"Skipping {filename} (no timestamp found)")
                continue

            try:
                # 1. Determine Review Time based on Duration and Force Flag
                ts_str = timestamp_str.replace('Z', '')
                dt_start = datetime.fromisoformat(ts_str).replace(tzinfo=timezone.utc)
                dt_now = override_now if override_now is not None else datetime.now(timezone.utc)
                
                # Fetch macro window duration
                macro_config = config['observer']['macro_timeframe']
                m_interval = macro_config['interval']
                m_limit = int(macro_config.get('limit', 336))
                m_mapping = {"m": 1/60, "h": 1, "d": 24}
                macro_duration_hours = int(m_interval[:-1]) * m_mapping.get(m_interval[-1], 1) * m_limit

                holding_time_hours: float = float(limit_order.get("holding_time_hours", 24))
                
                if not force:
                    # target = min(start + holding, start + macro)
                    target_duration = float(min(holding_time_hours, macro_duration_hours))
                    target_review_dt: datetime = dt_start + timedelta(hours=target_duration)
                    
                    if dt_now < target_review_dt:
                        logger.info(f"Skipping {filename} (target review date {target_review_dt} not reached)")
                        continue
                    
                    review_dt = target_review_dt
                else:
                    # target = min(start + holding, start + macro, now)
                    # Forcing means we review at the earliest available data point or target
                    review_dt = min(
                        dt_start + timedelta(hours=holding_time_hours),
                        dt_start + timedelta(hours=macro_duration_hours),
                        dt_now
                    )

                dt_end: datetime = review_dt

                symbol = session.get("observation", {}).get("symbol")
                if not symbol:
                    logger.warning(f"Skipping {filename} (no symbol found)")
                    continue
                    
                logger.info(f"Reviewing {filename} for {symbol} at {review_dt}...")
                
                # 2. Fetch Outcome
                fetch_interval = config['review']['review_kline_interval']
                klines = bf.fetch_historical_klines(
                    symbol=symbol, 
                    interval=fetch_interval, 
                    limit=1500,
                    startTime=int(dt_start.timestamp() * 1000),
                    endTime=int(dt_end.timestamp() * 1000)
                )

                if not klines:
                    logger.warning(f"No klines found for {symbol} in window.")
                    continue

                outcome = calculate_outcome(klines, float(klines[0][1]), prediction=prediction)

                # 3. Handle Multimodal Context
                chart_paths = []
                obs = session.get("observation", {})
                if "chart_path" in obs:
                    for p in obs["chart_path"].values():
                        if not p: continue
                        abs_p = os.path.join(PROJECT_ROOT, p)
                        if os.path.exists(abs_p):
                            chart_paths.append(abs_p)

                # 4. Fresh Observation at review_dt
                if symbol not in observers:
                    observers[symbol] = ObserverAgent(config, symbol, api_key)
                current_observation = observers[symbol].observe(timestamp=review_dt)

                # 5. Invoke AI Audit
                review_content = reviewer.review(
                    historical_prediction=session, 
                    actual_outcome=outcome,
                    current_observation=current_observation,
                    chart_image_paths=chart_paths
                )

                # 6. Save Standardized Record
                parsed_review = json.loads(review_content)
                # Ensure analysis is a single object (Gemini sometimes returns a list)
                analysis_obj = parsed_review[0] if isinstance(parsed_review, list) and len(parsed_review) > 0 else parsed_review
                
                final_record = {
                    "strategy": session,
                    "timestamp": review_dt.isoformat().replace("+00:00", "Z"),
                    "observation": current_observation,
                    "actual_market_outcome": outcome, 
                    "analysis": analysis_obj
                }
                
                DataStorage.save_json(final_record, review_path)
                logger.info(f"Review archived: {review_path}")

            except Exception as e:
                logger.error(f"Error reviewing {filename}: {e}", exc_info=True)
    finally:
        bf.close()
        logger.info("=== Review Pipeline Complete ===")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run the Crypto Review Agent B.")
    parser.add_argument("--force", action="store_true", help="Bypass protective checks.")
    parser.add_argument("--base-dir", type=str, default=None, help="Base directory override")
    parser.add_argument("--file", type=str, default=None, help="Specific strategy file to review")
    args = parser.parse_args()
    
    target_files = [args.file] if args.file else None
    main_review(target_files=target_files, force=args.force, base_dir=args.base_dir)
