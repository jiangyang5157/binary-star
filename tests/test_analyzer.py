import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.data_fetcher.binance_client import BinanceDataFetcher
from src.analyzer.volume_profile import VolumeProfileAnalyzer
from src.analyzer.chart_generator import ChartGenerator

def test_analysis_pipeline():
    print("--- Testing Crypto Dual-Agent Analysis Layer ---")
    
    symbol = "BTCUSDT"
    # 1. Fetch Klines (Macro and Micro)
    bf = BinanceDataFetcher()
    print(f"\n[1] Fetching Macro (180 @ 4h) and Micro (120 @ 1h) Klines...")
    klines_macro = bf.fetch_historical_klines(symbol=symbol, interval="4h", limit=180)
    klines_micro = bf.fetch_historical_klines(symbol=symbol, interval="1h", limit=120)
    
    if not klines_macro or not klines_micro:
        print("    Failed to fetch Klines. Exiting.")
        return
        
    # 2. Process & Analyze Volume Profile (Based on Macro)
    print("\n[2] Processing Volume Profile (Macro-based)...")
    vpa = VolumeProfileAnalyzer()
    
    df_macro = vpa.process_klines(klines_macro)
    df_micro = vpa.process_klines(klines_micro)
    print(f"    Created DataFrames: Macro({len(df_macro)}), Micro({len(df_micro)})")
    
    # Calculate POC, VAH, VAL from Macro
    profile_data = vpa.calculate_profile(df_macro)
    print(f"    POC: {profile_data.get('poc'):.2f}, VAH: {profile_data.get('vah'):.2f}, VAL: {profile_data.get('val'):.2f}")
    
    # 3. Generate Charts
    print("\n[3] Generating Visual Charts (Dual)...")
    output_dir = os.path.join(os.path.dirname(__file__), "..", "data", "images")
    cg = ChartGenerator(output_dir=output_dir)
    
    p4 = cg.generate_chart(symbol=symbol, df=df_macro, profile_data=profile_data, filename_suffix="4h")
    p1 = cg.generate_chart(symbol=symbol, df=df_micro, profile_data=profile_data, filename_suffix="1h")
    
    if p4 and p1:
        print(f"    Successfully generated Macro chart: {p4}")
        print(f"    Successfully generated Micro chart: {p1}")
    else:
        print("    Failed to generate one or more charts.")

if __name__ == "__main__":
    test_analysis_pipeline()
