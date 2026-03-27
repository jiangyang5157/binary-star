import os
import sys
from datetime import datetime, timezone, timedelta
sys.path.append(os.getcwd())

from src.infrastructure.binance.client import BinanceFuturesClient

def verify_sync():
    client = BinanceFuturesClient()
    symbol = "BTCUSDT"
    
    # 1 hour ago
    past_time = datetime.now(timezone.utc) - timedelta(hours=1)
    ts_ms = int(past_time.timestamp() * 1000)
    
    print(f"Testing for timestamp: {past_time} ({ts_ms} ms)")
    
    # 1. Fetch historical funding rate
    print("\n--- Funding Rate ---")
    hist_fr = client.fetch_funding_rate(symbol, limit=1, endTime=ts_ms)
    live_fr = client.fetch_funding_rate(symbol, limit=1)
    
    if hist_fr:
        print(f"Historical Funding Rate: {hist_fr[0].get('fundingRate')}")
    if live_fr:
        print(f"Live Funding Rate: {live_fr[0].get('fundingRate')}")
        
    # 2. Fetch historical liquidations
    print("\n--- Liquidations ---")
    liq_start = ts_ms - (24 * 60 * 60 * 1000)
    hist_liqs = client.fetch_liquidations(symbol, limit=10, startTime=liq_start, endTime=ts_ms)
    live_liqs = client.fetch_liquidations(symbol, limit=10)
    
    print(f"Historical Liquidations Found: {len(hist_liqs)}")
    print(f"Live Liquidations Found: {len(live_liqs)}")
    
    if len(hist_liqs) > 0 and len(live_liqs) > 0:
        first_hist = hist_liqs[0].get('time') or hist_liqs[0].get('T')
        first_live = live_liqs[0].get('time') or live_liqs[0].get('T')
        print(f"First Hist Liq Time: {first_hist}")
        print(f"First Live Liq Time: {first_live}")
        
    print("\nVerification process concluded.")

if __name__ == "__main__":
    verify_sync()
