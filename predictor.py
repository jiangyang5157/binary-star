import os
import sys
import yaml
import json
import logging
import argparse
from datetime import datetime, timezone
from dotenv import load_dotenv

# Load environment variables from .env if it exists
load_dotenv()

# Setup logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s", stream=sys.stdout)
logger = logging.getLogger("PredictionPipeline")

# Setup paths
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJECT_ROOT)

from src.data_fetcher.binance_client import BinanceDataFetcher
from src.data_fetcher.sentiment import SentimentFetcher
from src.data_fetcher.storage import DataStorage
from src.analyzer.volume_profile import VolumeProfileAnalyzer
from src.analyzer.market_regime import MarketRegimeAnalyzer
from src.analyzer.chart_generator import ChartGenerator
from src.agent.predictor_agent import PredictorAgent

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

def run_predictor(override_timestamp: datetime = None, current_position: dict = None, base_dir: str = None):
    """
    Executes the full pipeline for Predictor:
    1. Read Config
    2. Fetch Market Data & Sentiment
    3. Calculate Volume Profile & Generate Chart
    4. Pass to Gemini API
    5. Save output with Dispatcher logic
    """
    if override_timestamp:
        logger.info(f"=== Starting BACKTEST Pipeline at {override_timestamp} ===")
    else:
        logger.info("=== Starting Crypto Predictor ===")
    
    config = load_config()
    
    if base_dir:
        config['paths']['base_dir'] = base_dir

    # Pre-flight check for ALL required keys to enforce Strict Config
    try:
        # Paths
        _ = config['paths']['base_dir']
        _ = config['paths']['predictions_dir']
        _ = config['paths']['images_dir']
        _ = config['paths']['prompts_dir']
        _ = config['paths']['prompt_predictor_filename']
        
        # Symbol & Prediction
        _ = config['symbol']
        _ = config['prediction']['prediction_horizon_days']
        _ = config['prediction']['macro_timeframe']['interval']
        _ = config['prediction']['macro_timeframe']['limit']
        _ = config['prediction']['micro_timeframe']['interval']
        _ = config['prediction']['micro_timeframe']['limit']
        
        # Strategy Parameters
        _ = config['strategy']['vp_value_area_pct']
        _ = config['strategy']['vp_bins']
        _ = config['strategy']['order_flow_lookback_bars']
        _ = config['strategy']['trend_intensity_threshold']
        _ = config['strategy']['atr_window']
        _ = config['strategy']['bb_window']
        _ = config['strategy']['bb_std']
        _ = config['strategy']['kc_window']
        _ = config['strategy']['kc_mult']
        _ = config['strategy']['vol_ma_window']
        _ = config['strategy']['liquidation_fetch_limit']
        _ = config['strategy']['liquidation_context_limit']
        
        # Agent
        _ = config['agent']['predictor_model']
        _ = config['agent']['predictor_temp_initial']
        _ = config['agent']['predictor_temp_critique']
        _ = config['agent']['predictor_temp_final']
        
        # Notifications
        _ = config['notifications']['min_confidence_threshold']
        _ = config['notifications']['smtp_server']
        _ = config['notifications']['smtp_port']
        
        # Automation & Intervals
        _ = config['automation']['prediction_interval_hours']
        _ = config['automation']['review_interval_hours']

    except KeyError as e:
        error_msg = f"Config is missing required key: {e}. Please check your config.yaml."
        logger.error(error_msg)
        raise RuntimeError(error_msg) from e

    symbol = config['symbol']
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
    liq_fetch_limit = config['strategy']['liquidation_fetch_limit']
    liquidations = bf.fetch_liquidations(symbol=symbol, limit=liq_fetch_limit)
    
    # Calculate Order Flow Delta from MICRO klines
    # Delta = (Taker Buy Base Volume) - (Total Volume - Taker Buy Base Volume)
    # This shows aggressive buying vs aggressive selling.
    total_delta = 0
    lookback_bars = config['strategy']['order_flow_lookback_bars']
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
            for l in liquidations[:config['strategy']['liquidation_context_limit']]
        ],
        "order_flow_delta_recent": f"{total_delta:.4f} {symbol[:-4]}",
        "current_time": override_timestamp.isoformat() if override_timestamp else datetime.now(timezone.utc).isoformat()
    }
    
    # 1.5 Position Context
    if not current_position:
        current_position = {"position_type": "NONE", "entry_price": None}
    
    current_position_str = json.dumps(current_position, indent=2)
    
    # 2. Analysis & Visualization
    logger.info("Step 3: Calculating Volume Profile & Charting")
    # Fetch K-line data for Volume Profile (Macro)
    # We use a larger window to identify the high-level VAH/VAL/POC
    vpa = VolumeProfileAnalyzer(
        value_area_pct=config['strategy']['vp_value_area_pct'],
        vol_profile_bins=config['strategy']['vp_bins'],
        atr_window=config['strategy']['atr_window']
    )
    
    # Process both kline sets
    df_macro = vpa.process_klines(klines_macro)
    df_micro = vpa.process_klines(klines_micro)
    
    # 2.5 Market Regime Analysis (using MACRO data for high-level regime)
    mra = MarketRegimeAnalyzer(
        bb_window=config['strategy']['bb_window'],
        bb_std=config['strategy']['bb_std'],
        kc_window=config['strategy']['kc_window'],
        kc_mult=config['strategy']['kc_mult'],
        vol_ma_window=config['strategy']['vol_ma_window'],
        trend_intensity_threshold=config['strategy']['trend_intensity_threshold']
    )
    regime_metrics = mra.analyze(df_macro)
    
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
    context_data["atr_macro"] = df_macro['atr'].iloc[-1] if not df_macro.empty else 0
    context_data["atr_micro"] = df_micro['atr'].iloc[-1] if not df_micro.empty else 0
    context_data["prediction_horizon_days"] = config['prediction']['prediction_horizon_days']
    context_data["lookback_bars"] = lookback_bars
    
    # Inject Regime Metrics
    context_data.update(regime_metrics)
    
    # Inject strategy parameters for prompt template rendering
    context_data.update(config['strategy'])
    
    cg = ChartGenerator(output_dir=os.path.join(PROJECT_ROOT, config['paths']['base_dir'], config['paths']['images_dir']))
    
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

    # Set up PredictorAgent
    predictor_agent = PredictorAgent(
        model_name=config['agent']['predictor_model'],
        prompts_dir=os.path.join(PROJECT_ROOT, config['paths']['prompts_dir']),
        prompt_filename=config['paths']['prompt_predictor_filename'],
        temp_initial=config['agent']['predictor_temp_initial'],
        temp_critique=config['agent']['predictor_temp_critique'],
        temp_final=config['agent']['predictor_temp_final']
    )
    
    # Execute Model
    if not os.environ.get("GEMINI_API_KEY"):
        logger.warning("GEMINI_API_KEY not found in environment. Mocking AI output.")
        agent_output_raw = json.dumps({
            "timestamp": prediction_timestamp,
            "opinion": "mock_NEUTRAL",
            "confidence": 0,
            "reasoning": "API Key missing. This is a mocked output."
        }, indent=2, ensure_ascii=False)
    else:
        agent_output_raw = predictor_agent.analyze(
            symbol=symbol, 
            chart_image_paths=chart_paths, 
            context_data=context_data,
            current_position=current_position_str
        )
        
    logger.info(f"Agent A Raw Output Received.")

    # 4. Parse output and add metadata
    try:
        agent_output = json.loads(agent_output_raw)
        
        # New: Handle list format from Agent A (unwrapping if single item)
        if isinstance(agent_output, list) and len(agent_output) > 0:
            logger.info("Agent output is a list, unwrapping first prediction.")
            agent_output = agent_output[0]
            
    except json.JSONDecodeError as e:
        logger.warning(f"Agent output was not valid JSON ({e}). Saving as raw string.")
        agent_output = agent_output_raw

    # 4.5 The Dispatcher (Local Action Resolution)
    if isinstance(agent_output, dict):
        # Force system timestamp
        agent_output['timestamp'] = prediction_timestamp
        
        # Resolve Opinion vs Action
        opinion = str(agent_output.get("opinion", "NEUTRAL")).upper()
        pos_type = str(current_position.get("position_type", "NONE")).upper()
        
        final_action = "WAIT"
        
        if "BULLISH" in opinion:
            if pos_type == "NONE": final_action = "LONG"
            elif pos_type == "SHORT": final_action = "LONG" # Flip
            elif pos_type == "LONG": final_action = "HOLD"  # Already in
        elif "BEARISH" in opinion:
            if pos_type == "NONE": final_action = "SHORT"
            elif pos_type == "LONG": final_action = "SHORT" # Flip
            elif pos_type == "SHORT": final_action = "HOLD" # Already in
        else: # NEUTRAL
            if pos_type == "NONE": final_action = "WAIT"
            else: final_action = "CLOSE" # Exit
            
        logger.info(f"Dispatcher: Opinion({opinion}) + Position({pos_type}) -> Final Action({final_action})")
        
        # Final Result
        final_report = {}
        final_report["timestamp"] = prediction_timestamp
        final_report["confidence"] = agent_output.get("confidence", 0)
        final_report["opinion"] = opinion
        final_report["action"] = final_action
        final_report["current_price"] = agent_output.get("current_price", 0.0)
        final_report["take_profit"] = agent_output.get("take_profit", 0.0)
        final_report["stop_loss"] = agent_output.get("stop_loss", 0.0)
        final_report["reasoning"] = agent_output.get("reasoning", "")
        final_report["reasoning_zh"] = agent_output.get("reasoning_zh", "")
        
        final_report['position_context'] = {
            "position_type": pos_type,
            "entry_price": current_position.get("entry_price", 0.0)
        }
        
        final_report['config_context'] = {
            "symbol": config['symbol'],
            "prediction_horizon_days": config['prediction']['prediction_horizon_days'],
            "model": config['agent']['predictor_model']
        }
        agent_output = final_report
        # Cleanup old field if AI returned 'action' instead of 'opinion'
        if "action" in agent_output and agent_output["action"] == opinion:
             agent_output["opinion"] = opinion
    
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
    output_dir = os.path.join(PROJECT_ROOT, config['paths']['base_dir'], config['paths']['predictions_dir'])
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
    parser = argparse.ArgumentParser(description="Crypto Predictor CLI")
    parser.add_argument("--position", type=str, choices=["LONG", "SHORT", "NONE"], default="NONE", help="Current position type (LONG, SHORT, NONE)")
    parser.add_argument("--entry", type=float, default=0.0, help="Entry price of the current position")
    parser.add_argument("--base-dir", type=str, default=None, help="Base directory override")
    
    args = parser.parse_args()
    
    current_position = None
    if args.position.upper() != "NONE":
        current_position = {
            "position_type": args.position.upper(),
            "entry_price": args.entry if args.entry != 0.0 else None
        }
    
    run_predictor(current_position=current_position, base_dir=args.base_dir)
