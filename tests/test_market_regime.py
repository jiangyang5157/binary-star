import pandas as pd
import numpy as np
import pytest
from src.analyzer.market_regime import MarketRegimeAnalyzer

def test_market_regime_squeeze():
    # Create dummy data with absolute zero volatility (Squeeze)
    data = {
        'open': [100] * 50,
        'high': [101] * 50,
        'low': [99] * 50,
        'close': [100] * 50,
        'volume': [1000] * 50
    }
    df = pd.DataFrame(data)
    # TR: 101-99 = 2.
    # SMA: 100. Std: 0.
    # BB: 100 +/- 0. Width: 0.
    # KC: 100 +/- 1.5*2 = 100 +/- 3. Width: 6.
    # 0 < 6. Squeeze should be ON.
    
    mra = MarketRegimeAnalyzer(21, 2.0, 21, 1.5, 21, 0.4)
    metrics = mra.analyze(df)
    
    assert metrics['volatility_regime'] == 'SQUEEZE'
    assert metrics['squeeze_factor'] < 1.0

def test_market_regime_expansion():
    # Create dummy data followed by a breakout
    data = {
        'open': [100] * 30 + [110],
        'high': [101] * 30 + [120],
        'low': [99] * 30 + [110],
        'close': [100] * 30 + [115],
        'volume': [1000] * 31
    }
    df = pd.DataFrame(data)
    
    mra = MarketRegimeAnalyzer(21, 2.0, 21, 1.5, 21, 0.4)
    metrics = mra.analyze(df)
    
    # After a long period of flat (Squeeze), a big move should exit it
    assert metrics['volatility_regime'] in ['NORMAL', 'EXPANSION']

def test_market_regime_trend():
    # Create trending data
    prices = [100 + i for i in range(50)]
    data = {
        'open': [p - 0.5 for p in prices],
        'high': [p + 1 for p in prices],
        'low': [p - 1 for p in prices],
        'close': prices,
        'volume': [1000] * 50
    }
    df = pd.DataFrame(data)
    
    mra = MarketRegimeAnalyzer(21, 2.0, 21, 1.5, 21, 0.4)
    metrics = mra.analyze(df)
    
    assert metrics['market_regime'] == 'TRENDING'
    assert metrics['trend_intensity'] > 0.5
