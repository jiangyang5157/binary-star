import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.data_fetcher.binance_client import BinanceDataFetcher
from src.analyzer.volume_profile import VolumeProfileAnalyzer
from src.analyzer.chart_generator import ChartGenerator
from predictor import load_config

def test_analysis_pipeline():
    print("--- Testing Crypto Analysis Layer ---")
    
    # 0. Load Config
    config = load_config()
    symbol = config['symbol']
    macro_config = config['prediction']['macro_timeframe']
    micro_config = config['prediction']['micro_timeframe']
    macro_tf = macro_config['interval']
    micro_tf = micro_config['interval']
    macro_limit = macro_config['limit']
    micro_limit = micro_config['limit']
    
    # 1. Fetch Klines (Macro and Micro)
    bf = BinanceDataFetcher()
    print(f"\n[1] Fetching Macro ({macro_tf}) and Micro ({micro_tf}) Klines...")
    klines_macro = bf.fetch_historical_klines(symbol=symbol, interval=macro_tf, limit=macro_limit)
    klines_micro = bf.fetch_historical_klines(symbol=symbol, interval=micro_tf, limit=micro_limit)
    
    if not klines_macro or not klines_micro:
        print("    Failed to fetch Klines. Exiting.")
        return
        
    # 2. Process & Analyze Volume Profile (Based on Macro)
    print("\n[2] Processing Volume Profile (Macro-based)...")
    vpa = VolumeProfileAnalyzer(
        value_area_pct=config['strategy']['value_area_pct'],
        vol_profile_bins=config['strategy']['vol_profile_bins'],
        atr_window=config['strategy']['atr_window']
    )
    
    df_macro = vpa.process_klines(klines_macro)
    df_micro = vpa.process_klines(klines_micro)
    print(f"    Created DataFrames: Macro({len(df_macro)}), Micro({len(df_micro)})")
    
    # Calculate POC, VAH, VAL from Macro
    profile_data = vpa.calculate_profile(df_macro)
    print(f"    POC: {profile_data.get('poc'):.2f}, VAH: {profile_data.get('vah'):.2f}, VAL: {profile_data.get('val'):.2f}")
    
    # 3. Generate Charts (Enhanced with Visual AR)
    print("\n[3] Generating Visual Charts (Enhanced with Visual AR)...")
    output_dir = os.path.join(os.path.dirname(__file__), "..", "data", "images", "test")
    cg = ChartGenerator(output_dir=output_dir)
    
    # Mock Liquidation Data for Visual AR testing
    mock_liquidations = [
        {"p": profile_data.get('vah'), "S": "SELL", "q": "1.0"}, # Resistance band
        {"p": profile_data.get('val'), "S": "BUY", "q": "2.5"}   # Support band
    ]
    
    p4 = cg.generate_chart(symbol=symbol, df=df_macro, profile_data=profile_data, liquidations=mock_liquidations, filename_suffix=f"{macro_tf}")
    p1 = cg.generate_chart(symbol=symbol, df=df_micro, profile_data=profile_data, liquidations=mock_liquidations, filename_suffix=f"{micro_tf}")
    
    if p4 and p1:
        print(f"    Successfully generated Macro chart: {p4}")
        print(f"    Successfully generated Micro chart: {p1}")
    else:
        print("    Failed to generate one or more charts.")

if __name__ == "__main__":
    test_analysis_pipeline()
