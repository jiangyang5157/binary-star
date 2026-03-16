import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.data_fetcher.binance_client import BinanceDataFetcher
from src.analyzer.volume_profile import VolumeProfileAnalyzer
from src.analyzer.chart_generator import ChartGenerator

def run_tests():
    print("--- Testing Crypto Dual-Agent Analysis Layer ---")
    
    symbol = "BTCUSDT"
    interval = "4h"
    limit = 180  # ~30 days
    
    # 1. Fetch Klines
    print(f"\n[1] Fetching {limit} Klines for {symbol} at {interval}...")
    bf = BinanceDataFetcher()
    klines_data = bf.fetch_historical_klines(symbol=symbol, interval=interval, limit=limit)
    if not klines_data:
        print("    Failed to fetch Klines. Exiting.")
        return
        
    # 2. Process & Analyze Volume Profile
    print("\n[2] Processing Volume Profile...")
    vpa = VolumeProfileAnalyzer()
    
    # Pandas DF
    df = vpa.process_klines(klines_data)
    print(f"    Created DataFrame with {len(df)} rows.")
    
    # Calculate POC, VAH, VAL
    profile_data = vpa.calculate_profile(df)
    print(f"    POC (Point of Control): {profile_data.get('poc'):.2f}")
    print(f"    VAH (Value Area High):  {profile_data.get('vah'):.2f}")
    print(f"    VAL (Value Area Low):   {profile_data.get('val'):.2f}")
    
    # 3. Generate Chart
    print("\n[3] Generating Visual Chart...")
    output_dir = os.path.join(os.path.dirname(__file__), "..", "data", "images")
    cg = ChartGenerator(output_dir=output_dir)
    
    chart_path = cg.generate_chart(symbol=symbol, df=df, profile_data=profile_data, filename_suffix=interval)
    if chart_path:
        print(f"    Successfully generated chart at: {chart_path}")
    else:
        print("    Failed to generate chart.")

if __name__ == "__main__":
    run_tests()
