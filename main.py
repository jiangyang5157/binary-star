import os
import sys
import yaml
import json
import logging
from datetime import datetime

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

def run_agent_a():
    """
    Executes the full pipeline for Agent A:
    1. Read Config
    2. Fetch Market Data & Sentiment
    3. Calculate Volume Profile & Generate Chart
    4. Pass to Gemini API
    5. Save output
    """
    logger.info("=== Starting Crypto Dual-Agent Pipeline (Agent A) ===")
    config = load_config()
    if not config:
        return

    symbol = config['trading']['symbol']
    interval = config['data']['macro_timeframe']['interval']
    limit = config['data']['macro_timeframe']['limit']
    
    # 1. Fetching Data
    bf = BinanceDataFetcher()
    sf = SentimentFetcher()

    logger.info(f"Step 1: Fetching Market Data for {symbol}")
    klines = bf.fetch_historical_klines(symbol=symbol, interval=interval, limit=limit)
    
    logger.info("Step 2: Fetching Sentiment Data")
    oi = sf.fetch_open_interest(symbol=symbol)
    ls_ratio = sf.fetch_long_short_ratio(symbol=symbol, period=interval, limit=1)
    
    # Bundle Context for Gemini
    context_data = {
        "symbol": symbol,
        "interval": interval,
        "current_open_interest": oi.get('openInterest', 'N/A'),
        "long_short_ratio_latest": ls_ratio[0].get('longShortRatio', 'N/A') if ls_ratio else 'N/A'
    }
    
    # 2. Analysis & Visualization
    logger.info("Step 3: Calculating Volume Profile & Charting")
    vpa = VolumeProfileAnalyzer()
    df = vpa.process_klines(klines)
    profile_data = vpa.calculate_profile(df)
    
    # Add POC data to the text context as well
    context_data["poc_price"] = profile_data.get('poc', 0)
    context_data["vah"] = profile_data.get('vah', 0)
    context_data["val"] = profile_data.get('val', 0)
    context_data["last_close_price"] = df['close'].iloc[-1] if not df.empty else 0
    
    cg = ChartGenerator(output_dir=os.path.join(PROJECT_ROOT, config['paths']['images_dir']))
    chart_path = cg.generate_chart(symbol=symbol, df=df, profile_data=profile_data, filename_suffix=interval)
    
    if not chart_path:
        logger.error("Failed to generate chart. Cannot proceed with multimodal agent.")
        return
        
    # 3. Agent A execution
    logger.info("Step 4: Invoking Agent A (Gemini)")
    logger.info("Note: Ensure GEMINI_API_KEY environment variable is set.")
    
    prompts_dir = os.path.join(PROJECT_ROOT, config['paths']['prompts_dir'])
    trader = TraderAgent(model_name=config['agent']['model_name'], prompts_dir=prompts_dir)
    
    # Try calling the API
    if not os.environ.get("GEMINI_API_KEY"):
        logger.warning("GEMINI_API_KEY not found in environment. Mocking Agent A output for testing...")
        agent_output = json.dumps({
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "action": "mock_HOLD",
            "confidence": 0,
            "reasoning": "API Key missing. This is a mocked output."
        }, indent=2)
    else:
        agent_output = trader.analyze(symbol=symbol, chart_image_path=chart_path, context_data=context_data)
        
    logger.info(f"Agent A Output:\n{agent_output}")
    
    # 4. Save the result
    logger.info("Step 5: Saving results")
    output_dir = os.path.join(PROJECT_ROOT, config['paths']['raw_data_dir'], "predictions")
    os.makedirs(output_dir, exist_ok=True)
    
    timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_file = os.path.join(output_dir, f"{symbol}_prediction_{timestamp_str}.json")
    
    try:
        # We try to parse the JSON string returned by Gemini to ensure formatting,
        # but if it fails, we save the raw string.
        try:
            parsed_json = json.loads(agent_output)
            DataStorage.save_json(parsed_json, output_file)
        except json.JSONDecodeError:
            with open(output_file, 'w') as f:
                f.write(agent_output)
        logger.info(f"Prediction saved to {output_file}")
    except Exception as e:
        logger.error(f"Could not save prediction: {e}")
        
    logger.info("=== Pipeline Complete ===")

if __name__ == "__main__":
    run_agent_a()
