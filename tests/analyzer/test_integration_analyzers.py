import pytest
import os
from dotenv import load_dotenv
from src.infrastructure.binance.client import BinanceFuturesClient
from src.analyzer.volume_profile import VolumeProfileAnalyzer, VolumeProfileConfig
from src.analyzer.market_regime import MarketRegimeAnalyzer, MarketRegimeConfig

load_dotenv()

@pytest.fixture
def binance_client():
    api_key = os.getenv("BINANCE_API_KEY")
    api_secret = os.getenv("BINANCE_API_SECRET")
    if not api_key or not api_secret:
        pytest.skip("API keys not found in .env")
    return BinanceFuturesClient(api_key, api_secret)

def test_real_data_analysis(binance_client):
    symbol = "BTCUSDT"
    interval = "1h"
    
    # 1. Fetch real data
    klines = binance_client.fetch_historical_klines(symbol, interval, limit=100)
    assert len(klines) >= 100
    
    # 2. Test Volume Profile with real data
    vp_cfg = VolumeProfileConfig(
        value_area_ratio=0.7,
        resolution_bins=24,
        atr_period=14,
        max_hvn_nodes=5,
        max_lvn_nodes=5,
        hvn_sensitivity=0.1,
        lvn_sensitivity=0.05,
        min_node_distance=3
    )
    vp_analyzer = VolumeProfileAnalyzer(config=vp_cfg)
    vp_result = vp_analyzer.analyze(klines)
    
    assert vp_result["poc"] > 0
    assert vp_result["vah"] > vp_result["val"]
    assert "hvn" in vp_result
    
    # 3. Test Market Regime with real data
    mr_cfg = MarketRegimeConfig(
        bollinger_window=20,
        bollinger_std_dev=2.0,
        keltner_window=20,
        keltner_multiplier=1.5,
        volume_ma_window=20,
        trend_intensity_threshold=0.6,
        trend_lookback=14,
        wick_skewness_period=24
    )
    mr_analyzer = MarketRegimeAnalyzer(config=mr_cfg)
    
    # MarketRegimeAnalyzer expects a DataFrame
    import pandas as pd
    df = pd.DataFrame(klines, columns=[
        'timestamp', 'open', 'high', 'low', 'close', 'volume',
        'close_time', 'quote_av', 'trades', 'tb_base_av', 'tb_quote_av', 'ignore'
    ])
    for col in ['open', 'high', 'low', 'close', 'volume']:
        df[col] = df[col].astype(float)
        
    mr_result = mr_analyzer.analyze(df)
    
    assert mr_result["volatility_regime"] in ["NORMAL", "SQUEEZE", "EXPANSION"]
    assert mr_result["market_regime"] in ["TRENDING", "RANGING"]
    assert mr_result["trend_intensity"] >= 0
