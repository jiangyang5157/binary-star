import os
import pytest
import pandas as pd
import numpy as np
from datetime import datetime, timezone
from src.analyzer.chart_generator import ChartVisualRenderer, ChartConfig
from src.infrastructure.binance.client import BinanceFuturesClient

# Configuration for test output
TEST_OUTPUT_DIR = "data/test/klines"

@pytest.fixture(scope="module")
def chart_renderer():
    return ChartVisualRenderer(output_dir=TEST_OUTPUT_DIR)

@pytest.fixture(scope="module")
def binance_client():
    return BinanceFuturesClient()

def test_filename_generation(chart_renderer):
    """Verifies the new naming convention: {symbol}_{interval}_klines_{ts}.png"""
    symbol = "BTCUSDT"
    interval = "15m"
    timestamp = "2026-03-25T14:00:00Z"
    
    filepath = chart_renderer.storage.generate_filepath(symbol, interval, timestamp)
    filename = os.path.basename(filepath)
    
    assert filename == "BTCUSDT_15m_klines_20260325_140000.png"

def test_trendline_logic(chart_renderer):
    """Verifies that trendlines are detected from fractal highs/lows."""
    # Synthetic upward trend with local peaks
    prices = [100, 102, 101, 105, 104, 110, 108, 115]
    df = pd.DataFrame({
        'open': prices,
        'high': [p + 0.5 for p in prices],
        'low': [p - 0.5 for p in prices],
        'close': prices,
        'volume': [100] * len(prices)
    })
    
    trendlines = chart_renderer.extractor.detect_trendlines(df)
    # With 8 points and window=5, we should detect at least some local structure
    assert isinstance(trendlines, list)

def test_render_synthetic(chart_renderer):
    """Verifies rendering with synthetic data doesn't crash."""
    dates = pd.date_range(start="2026-03-25", periods=50, freq="15min")
    df = pd.DataFrame({
        'open': np.linspace(100, 110, 50),
        'high': np.linspace(101, 111, 50),
        'low': np.linspace(99, 109, 50),
        'close': np.linspace(100, 110, 50),
        'volume': np.random.uniform(10, 100, 50)
    }, index=dates)
    
    profile_data = {
        "poc": 105.0,
        "vah": 108.0,
        "val": 102.0,
        "timestamp": "2026-03-25T14:00:00Z",
        "profile_data": [{"price": 105, "volume": 500}]
    }
    
    filepath = chart_renderer.generate_chart(
        symbol="SYNTH",
        df=df,
        profile_data=profile_data,
        time_interval="15m"
    )
    
    assert os.path.exists(filepath)
    assert "SYNTH_15m_klines_20260325_140000.png" in filepath

@pytest.mark.integration
def test_render_live_binance(chart_renderer, binance_client):
    """Integration test: Fetch real BTCUSDT klines and render."""
    symbol = "BTCUSDT"
    interval = "1h"
    
    # 1. Fetch real klines
    raw_klines = binance_client.fetch_historical_klines(symbol, interval, limit=100)
    assert isinstance(raw_klines, list) and len(raw_klines) > 0
    
    # Standard format for Binance klines
    df = pd.DataFrame(raw_klines, columns=[
        'open_time', 'open', 'high', 'low', 'close', 'volume', 
        'close_time', 'q_volume', 'trades', 'taker_base', 'taker_quote', 'ignore'
    ])
    df['open'] = df['open'].astype(float)
    df['high'] = df['high'].astype(float)
    df['low'] = df['low'].astype(float)
    df['close'] = df['close'].astype(float)
    df['volume'] = df['volume'].astype(float)
    df.index = pd.to_datetime(df['open_time'], unit='ms')
    
    # 2. Mock profile data (normally comes from VolumeProfileAnalyzer)
    profile_data = {
        "poc": df['close'].mean(),
        "vah": df['high'].max(),
        "val": df['low'].min(),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "profile_data": [{"price": df['close'].iloc[0], "volume": 1000}]
    }
    
    # 3. Render
    filepath = chart_renderer.generate_chart(
        symbol=symbol,
        df=df,
        profile_data=profile_data,
        time_interval=interval
    )
    
    assert os.path.exists(filepath)
    print(f"\nLive chart generated at: {filepath}")
