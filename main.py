import os
import sys
import yaml
import json
import logging
import hashlib
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

    # Pre-flight check for ALL required keys to enforce Strict Config
    try:
        # Global
        _ = config['timezone']
        
        # Paths
        _ = config['paths']['raw_data_dir']
        _ = config['paths']['images_dir']
        _ = config['paths']['prompts_dir']
        
        # Trading & Prediction
        _ = config['trading']['symbol']
        _ = config['trading']['value_area_pct']
        _ = config['trading']['order_flow_lookback_bars']
        _ = config['prediction']['trade_horizon_days']
        _ = config['prediction']['macro_timeframe']['interval']
        _ = config['prediction']['macro_timeframe']['limit']
        _ = config['prediction']['micro_timeframe']['interval']
        _ = config['prediction']['micro_timeframe']['limit']
        
        # Agent
        _ = config['agent']['trader_model']
        _ = config['agent']['trader_pass1_temperature']
        _ = config['agent']['trader_pass2_temperature']
        _ = config['agent']['trader_pass3_temperature']
        
        # Notifications
        _ = config['notifications']['min_confidence_threshold']
        _ = config['notifications']['smtp_server']
        _ = config['notifications']['smtp_port']
        
        # Automation & Intervals
        _ = config['automation']['prediction_interval_hours']
        _ = config['automation']['review_interval_hours']

    except KeyError as e:
        logger.error(f"Config is missing required key: {e}. Please check your config.yaml.")
        return

    symbol = config['trading']['symbol']
    macro_config = config['prediction']['macro_timeframe']
    micro_config = config['prediction']['micro_timeframe']
    
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
    
    logger.info("Step 2: Fetching Sentiment & Liquidity Data")
    oi = sf.fetch_open_interest(symbol=symbol, period=micro_config['interval'], **fetch_kwargs)
    ls_ratio = sf.fetch_long_short_ratio(symbol=symbol, period=macro_config['interval'], limit=1, **fetch_kwargs)
    
    # Some endpoints might not support endTime correctly in the library
    sentiment_kwargs = {}
    if not override_timestamp:
        sentiment_kwargs = fetch_kwargs
    
    top_ls_ratio = bf.fetch_top_long_short_accounts(symbol=symbol, period=macro_config['interval'], limit=1, **sentiment_kwargs)
    liquidations = bf.fetch_liquidations(symbol=symbol, limit=20) # Get recent 20 liquidations
    
    # Calculate Order Flow Delta from MICRO klines
    # Delta = (Taker Buy Base Volume) - (Total Volume - Taker Buy Base Volume)
    # This shows aggressive buying vs aggressive selling.
    total_delta = 0
    lookback_bars = config['trading']['order_flow_lookback_bars']
    if klines_micro:
        try:
            # Last few bars from config
            recent_micro = klines_micro[-lookback_bars:] 
            for k in recent_micro:
                vol = float(k[5])
                taker_buy = float(k[9])
                total_delta += (taker_buy - (vol - taker_buy))
        except (IndexError, ValueError):
            pass

    # Bundle Context for Gemini
    context_data = {
        "symbol": symbol,
        "macro_interval": macro_config['interval'],
        "micro_interval": micro_config['interval'],
        "current_open_interest": oi.get('openInterest', 'N/A'),
        "long_short_ratio_latest": ls_ratio[0].get('longShortRatio', 'N/A') if (isinstance(ls_ratio, list) and ls_ratio) else 'N/A',
        "top_traders_ls_ratio": top_ls_ratio[0].get('longShortRatio', 'N/A') if (isinstance(top_ls_ratio, list) and top_ls_ratio) else 'N/A',
        "recent_liquidations": [
            {"price": l.get('p'), "side": l.get('S'), "amount": l.get('q')} 
            for l in liquidations[:5] # Just top 5 for context density
        ],
        "order_flow_delta_recent": f"{total_delta:.4f} {symbol[:-4]}",
        "current_time": override_timestamp.isoformat() if override_timestamp else datetime.now(timezone.utc).isoformat()
    }
    
    # 2. Analysis & Visualization
    logger.info("Step 3: Calculating Volume Profile & Charting")
    va_pct = config['trading']['value_area_pct']
    vpa = VolumeProfileAnalyzer(value_area_pct=va_pct)
    
    # Process both kline sets
    df_macro = vpa.process_klines(klines_macro)
    df_micro = vpa.process_klines(klines_micro)
    
    # Calculate Profile based on MACRO data (the big picture structure)
    profile_data = vpa.calculate_profile(df_macro)
    
    # Calculate current timestamp for filenames
    dt_now = override_timestamp if override_timestamp else datetime.now(timezone.utc)
    timestamp_str = dt_now.strftime("%Y%m%d_%H%M%S")
    # Unified ISO format (using Z instead of +00:00)
    prediction_timestamp = dt_now.isoformat().replace("+00:00", "Z")
    
    # Attach to profile_data so ChartGenerator can pick it up
    profile_data["timestamp"] = prediction_timestamp
    
    # Add POC data to the text context as well
    context_data["poc_price"] = profile_data.get('poc', 0)
    context_data["vah"] = profile_data.get('vah', 0)
    context_data["val"] = profile_data.get('val', 0)
    context_data["last_close_price"] = df_macro['close'].iloc[-1] if not df_macro.empty else 0
    context_data["macro_interval"] = macro_config['interval']
    context_data["micro_interval"] = micro_config['interval']
    context_data["trade_horizon_days"] = config['prediction']['trade_horizon_days']
    context_data["lookback_bars"] = lookback_bars
    
    cg = ChartGenerator(output_dir=os.path.join(PROJECT_ROOT, config['paths']['images_dir']))
    
    # Generate TWO charts: Macro and Micro, overlaid with the SAME Volume Profile levels
    macro_chart_path = cg.generate_chart(symbol=symbol, df=df_macro, profile_data=profile_data, liquidations=liquidations, filename_suffix=macro_config['interval'])
    micro_chart_path = cg.generate_chart(symbol=symbol, df=df_micro, profile_data=profile_data, liquidations=liquidations, filename_suffix=micro_config['interval'])
    
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
            prompt_content = f.read()
            prompt_version = hashlib.md5(prompt_content.encode('utf-8')).hexdigest()[:8]
            logger.info(f"Using Trader Prompt Version: {prompt_version}")
    except Exception as e:
        logger.warning(f"Could not calculate prompt version: {e}")

    # Set up Agent A
    trader = TraderAgent(
        model_name=config['agent']['trader_model'],
        prompts_dir=os.path.join(PROJECT_ROOT, config['paths']['prompts_dir']),
        temp_pass1=config['agent']['trader_pass1_temperature'],
        temp_pass2=config['agent']['trader_pass2_temperature'],
        temp_pass3=config['agent']['trader_pass3_temperature']
    )
    
    # Execute Model
    if not os.environ.get("GEMINI_API_KEY"):
        logger.warning("GEMINI_API_KEY not found in environment. Mocking Agent A output.")
        agent_output_raw = json.dumps({
            "timestamp": prediction_timestamp,
            "action": "mock_HOLD",
            "confidence": 0,
            "reasoning": "API Key missing. This is a mocked output."
        }, indent=2, ensure_ascii=False)
    else:
        coach_dir = os.path.join(PROJECT_ROOT, config['paths']['raw_data_dir'], "coach")
        agent_output_raw = trader.analyze(
            symbol=symbol, 
            chart_image_paths=chart_paths, 
            context_data=context_data,
            coach_dir=coach_dir
        )
        
    logger.info(f"Agent A Raw Output Received.")

    # 4. Parse output and add metadata
    try:
        agent_output = json.loads(agent_output_raw)
        
        # New: Handle list format from Agent A (unwrapping if single item)
        if isinstance(agent_output, list) and len(agent_output) > 0:
            logger.info("Agent output is a list, unwrapping first prediction.")
            agent_output = agent_output[0]
            
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
    try:
        from src.utils.notifier import EmailNotifier
        notifier = EmailNotifier(config)
        
        if notifier.enabled and isinstance(agent_output, dict):
            # Strict access to required notification keys
            notif_config = config['notifications']
            min_confidence = notif_config['min_confidence_threshold']
            
            if agent_output.get('confidence', 0) >= min_confidence:
                notifier.send_prediction_alert(symbol, agent_output, chart_paths=chart_paths)
    except Exception as e:
        logger.error(f"Failed to handle notification: {e}")

    # 6. Save the result
    logger.info("Step 5: Saving results")
    output_dir = os.path.join(PROJECT_ROOT, config['paths']['raw_data_dir'], "predictions")
    os.makedirs(output_dir, exist_ok=True)
    output_file = os.path.join(output_dir, f"{symbol}_prediction_{timestamp_str}.json")
    
    try:
        if isinstance(agent_output, (dict, list)):
            DataStorage.save_json(agent_output, output_file)
        else:
            with open(output_file, 'w', encoding='utf-8') as f:
                f.write(agent_output)
        logger.info(f"Prediction saved to {output_file}")
    except Exception as e:
        logger.error(f"Failed to save prediction: {e}")
    finally:
        # Cleanup resources
        bf.close()
        sf.close()
        logger.info("=== Pipeline Complete ===")

if __name__ == "__main__":
    run_agent_a()
