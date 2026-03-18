import sys
import os

# Add the 'src' directory to the Python path so we can import our modules
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.data_fetcher.binance_client import BinanceDataFetcher
from src.data_fetcher.sentiment import SentimentFetcher
from src.data_fetcher.storage import DataStorage
from main import load_config

def test_data_fetcher_components():
    print("--- Testing Crypto Dual-Agent Data Layer ---")
    
    symbol = "BTCUSDT"
    
    # test fetchers
    bf = BinanceDataFetcher()
    sf = SentimentFetcher()
    
    # 0. Load Config for dynamic testing
    config = load_config()
    macro_tf = config['trading']['macro_timeframe']['interval']
    micro_tf = config['trading']['micro_timeframe']['interval']
    
    # 1. Test Klines
    print(f"\n[1] Fetching Dual-Timeframe Klines for {symbol}...")
    klines_macro = bf.fetch_historical_klines(symbol=symbol, interval=macro_tf, limit=5)
    print(f"    Macro ({macro_tf}): Received {len(klines_macro)} K-lines.")
    
    klines_micro = bf.fetch_historical_klines(symbol=symbol, interval=micro_tf, limit=5)
    print(f"    Micro ({micro_tf}): Received {len(klines_micro)} K-lines.")
    
    # 2. Test Order Book
    print(f"\n[2] Fetching Order Book for {symbol}...")
    order_book = bf.fetch_order_book(symbol=symbol, limit=10)
    print(f"    Received bids: {len(order_book.get('bids', []))}, asks: {len(order_book.get('asks', []))}")
    
    # 3. Test Sentiment & Liquidations
    print(f"\n[3] Fetching Sentiment & Liquidity Data for {symbol}...")
    open_interest = sf.fetch_open_interest(symbol=symbol)
    print(f"    Current Open Interest: {open_interest.get('openInterest')}")
    
    # Test Liquidations (Phase 2 feature)
    liquidations = bf.fetch_liquidations(symbol=symbol, limit=5)
    print(f"    Received Liquidations: {len(liquidations)}")
    if liquidations:
        print(f"    Latest Liq Price: {liquidations[0].get('p')}")

    ls_ratio = sf.fetch_long_short_ratio(symbol=symbol, period=macro_tf, limit=1)
    if ls_ratio:
        print(f"    Long/Short Ratio: {ls_ratio[0].get('longShortRatio')}")
    else:
        print("    No L/S Ratio received.")
        
    # NEW: Test API Key presence in Binance Fetcher
    print(f"\n[4] Verifying API Key Initialization...")
    if bf.api_key:
        print(f"    Binance Fetcher initialized with API KEY (ending in ...{bf.api_key[-4:]})")
    else:
        print("    Binance Fetcher initialized in PUBLIC mode (No API Key).")
        
    # 4. Storage utility test
    test_filepath = os.path.join(os.path.dirname(__file__), "..", "data", "raw", f"{symbol}_test.json")
    print(f"\n[4] Testing JSON Storage utility ({test_filepath})...")
    DataStorage.save_json(order_book, test_filepath)
    loaded_data = DataStorage.load_json(test_filepath)
    print(f"    Save/Load verified? {type(loaded_data) is dict}")
    
    # NEW: Cleanup test file
    if os.path.exists(test_filepath):
        os.remove(test_filepath)
        print(f"    Cleaned up test file: {test_filepath}")

if __name__ == "__main__":
    test_data_fetcher_components()
