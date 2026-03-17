import os
import sys
import yaml
import json
import logging
from datetime import datetime, timezone
from dotenv import load_dotenv

# Load environment variables from .env if it exists
load_dotenv()

# Setup paths
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJECT_ROOT)

from src.data_fetcher.binance_client import BinanceDataFetcher
from src.data_fetcher.sentiment import SentimentFetcher
from src.data_fetcher.storage import DataStorage
from src.analyzer.volume_profile import VolumeProfileAnalyzer
from src.analyzer.chart_generator import ChartGenerator
from src.agent.trader_agent import TraderAgent

# Setup logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("MainPipeline")

def load_config(config_path: str = "config/config.yaml") -> dict:
    try:
        with open(os.path.join(PROJECT_ROOT, config_path), 'r') as f:
            return yaml.safe_load(f)
    except Exception as e:
        logger.error(f"Failed to load config: {e}")
        return {}

def run_agent_a(override_timestamp: datetime = None):
    """
    Executes the full pipeline for Agent A:
    1. Read Config
    2. Fetch Market Data & Sentiment
    3. Calculate Volume Profile & Generate Chart
    4. Pass to Gemini API
    5. Save output
    """
    if override_timestamp:
        logger.info(f"=== Starting BACKTEST Pipeline at {override_timestamp} ===")
    else:
        logger.info("=== Starting Crypto Dual-Agent Pipeline (Agent A) ===")
    config = load_config()
    if not config:
        return

    symbol = config['trading']['symbol']
    macro_config = config['data']['macro_timeframe']
    micro_config = config['data']['micro_timeframe']
    
    # 1. Fetching Data
    bf = BinanceDataFetcher()
    sf = SentimentFetcher()

    logger.info(f"Step 1: Fetching Market Data for {symbol}")
    fetch_kwargs = {}
    if override_timestamp:
        fetch_kwargs['endTime'] = int(override_timestamp.timestamp() * 1000)

    # Macro data for Volume Profile structure
    klines_macro = bf.fetch_historical_klines(
        symbol=symbol, 
        interval=macro_config['interval'], 
        limit=macro_config['limit'],
        **fetch_kwargs
    )
    # Micro data for entry precision
    klines_micro = bf.fetch_historical_klines(
        symbol=symbol, 
        interval=micro_config['interval'], 
        limit=micro_config['limit'],
        **fetch_kwargs
    )
    
    logger.info("Step 2: Fetching Sentiment Data")
    oi = sf.fetch_open_interest(symbol=symbol)
    ls_ratio = sf.fetch_long_short_ratio(symbol=symbol, period=macro_config['interval'], limit=1)
    
    # Bundle Context for Gemini
    context_data = {
        "symbol": symbol,
        "macro_interval": macro_config['interval'],
        "micro_interval": micro_config['interval'],
        "current_open_interest": oi.get('openInterest', 'N/A'),
        "long_short_ratio_latest": ls_ratio[0].get('longShortRatio', 'N/A') if ls_ratio else 'N/A',
        "current_time": override_timestamp.isoformat() if override_timestamp else datetime.now(timezone.utc).isoformat()
    }
    
    # 2. Analysis & Visualization
    logger.info("Step 3: Calculating Volume Profile & Charting")
    va_pct = config['data'].get('value_area_pct', 0.70)
    vpa = VolumeProfileAnalyzer(value_area_pct=va_pct)
    
    # Process both kline sets
    df_macro = vpa.process_klines(klines_macro)
    df_micro = vpa.process_klines(klines_micro)
    
    # Calculate Profile based on MACRO data (the big picture structure)
    profile_data = vpa.calculate_profile(df_macro)
    
    # Calculate current timestamp for filenames
    dt_now = override_timestamp if override_timestamp else datetime.now(timezone.utc)
    timestamp_str = dt_now.strftime("%Y%m%d_%H%M%S")
    prediction_timestamp = dt_now.isoformat() + ("Z" if not override_timestamp else "")
    
    # Attach to profile_data so ChartGenerator can pick it up
    profile_data["timestamp"] = prediction_timestamp
    
    # Add POC data to the text context as well
    context_data["poc_price"] = profile_data.get('poc', 0)
    context_data["vah"] = profile_data.get('vah', 0)
    context_data["val"] = profile_data.get('val', 0)
    context_data["last_close_price"] = df_macro['close'].iloc[-1] if not df_macro.empty else 0
    context_data["macro_interval"] = macro_config['interval']
    context_data["micro_interval"] = micro_config['interval']
    context_data["review_window_days"] = config.get('trading', {}).get('review_window_days', 14)
    
    cg = ChartGenerator(output_dir=os.path.join(PROJECT_ROOT, config['paths']['images_dir']))
    
    # Generate TWO charts: Macro and Micro, overlaid with the SAME Volume Profile levels
    macro_chart_path = cg.generate_chart(symbol=symbol, df=df_macro, profile_data=profile_data, filename_suffix=macro_config['interval'])
    micro_chart_path = cg.generate_chart(symbol=symbol, df=df_micro, profile_data=profile_data, filename_suffix=micro_config['interval'])
    
    chart_paths = [p for p in [macro_chart_path, micro_chart_path] if p]
    
    if not chart_paths:
        logger.error("Failed to generate any charts. Cannot proceed with multimodal agent.")
        return
        
    # Step 4: Invoking Agent A (Gemini)
    logger.info("Step 4: Invoking Agent A (Gemini)")
    logger.info("Note: Ensure GEMINI_API_KEY environment variable is set.")
    
    # Calculate Prompt Version (Hash) to track data drift
    prompt_path = os.path.join(PROJECT_ROOT, config['paths']['prompts_dir'], "prompt_trader.txt")
    prompt_version = "unknown"
    try:
        with open(prompt_path, 'r', encoding='utf-8') as f:
            import hashlib
            prompt_content = f.read()
            prompt_version = hashlib.md5(prompt_content.encode('utf-8')).hexdigest()[:8]
            logger.info(f"Using Trader Prompt Version: {prompt_version}")
    except Exception as e:
        logger.warning(f"Could not calculate prompt version: {e}")

    # Set up Agent A
    trader = TraderAgent(
        model_name=config['agent']['model_name'],
        prompts_dir=os.path.join(PROJECT_ROOT, config['paths']['prompts_dir'])
    )
    
    # Execute Model
    if not os.environ.get("GEMINI_API_KEY"):
        logger.warning("GEMINI_API_KEY not found in environment. Mocking Agent A output.")
        agent_output_raw = json.dumps({
            "timestamp": prediction_timestamp,
            "action": "mock_HOLD",
            "confidence": 0,
            "reasoning": "API Key missing. This is a mocked output."
        }, indent=2)
    else:
        agent_output_raw = trader.analyze(symbol=symbol, chart_image_paths=chart_paths, context_data=context_data)
        
    logger.info(f"Agent A Raw Output Received.")

    # 4. Parse output and add metadata
    try:
        agent_output = json.loads(agent_output_raw)
    except Exception:
        logger.warning("Agent output was not valid JSON. Saving as raw string.")
        agent_output = agent_output_raw

    # Enrich with metadata if it's a dictionary
    if isinstance(agent_output, dict):
        # Force system timestamp to avoid AI hallucinations
        agent_output['timestamp'] = prediction_timestamp
        agent_output['metadata'] = {
            "prompt_version": prompt_version,
            "config_snapshot": config['trading']
        }
    
    # 5. Send Notification if confidence is high
    notif_config = config.get('notifications', {})
    if notif_config.get('email_enabled') and isinstance(agent_output, dict):
        threshold = notif_config.get('min_confidence_threshold', 85)
        if agent_output.get('confidence', 0) >= threshold:
            try:
                from src.utils.notifier import EmailNotifier
                notifier = EmailNotifier(config)
                notifier.send_prediction_alert(symbol, agent_output)
            except Exception as e:
                logger.error(f"Failed to send notification: {e}")

    # 6. Save the result
    logger.info("Step 5: Saving results")
    output_dir = os.path.join(PROJECT_ROOT, config['paths']['raw_data_dir'], "predictions")
    os.makedirs(output_dir, exist_ok=True)
    output_file = os.path.join(output_dir, f"{symbol}_prediction_{timestamp_str}.json")
    
    try:
        if isinstance(agent_output, dict):
            DataStorage.save_json(agent_output, output_file)
        else:
            with open(output_file, 'w', encoding='utf-8') as f:
                f.write(agent_output)
        logger.info(f"Prediction saved to {output_file}")
    except Exception as e:
        logger.error(f"Could not save prediction: {e}")
        
    logger.info("=== Pipeline Complete ===")

if __name__ == "__main__":
    run_agent_a()
