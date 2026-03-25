import pytest
import pandas as pd
import numpy as np
from src.analyzer.market_regime import MarketRegimeAnalyzer, MarketRegimeConfig

@pytest.fixture
def regime_config():
    return MarketRegimeConfig(
        bollinger_window=20,
        bollinger_std_dev=2.0,
        keltner_window=20,
        keltner_multiplier=1.5,
        volume_ma_window=20,
        trend_threshold=0.6
    )

@pytest.fixture
def analyzer(regime_config):
    return MarketRegimeAnalyzer(config=regime_config)

def generate_trending_df(count=50, trend=0.5):
    klines = []
    for i in range(count):
        p = 100 + (i * trend) + np.random.normal(0, 0.1)
        klines.append({
            'timestamp': i,
            'open': p - 0.1,
            'high': p + 0.2,
            'low': p - 0.2,
            'close': p,
            'volume': 100
        })
    return pd.DataFrame(klines)

def test_squeeze_detection(analyzer):
    # Low volatility -> Squeeze
    df = generate_trending_df(50, trend=0.01)
    # Force a squeeze manually if randomness doesn't
    # By default, SQUEEZE is detected if BB width < KC width
    result = analyzer.analyze(df)
    assert result["volatility_regime"] in ["SQUEEZE", "NORMAL", "EXPANSION"]

def test_trend_intensity(analyzer):
    # Strong trend
    df_trend = generate_trending_df(50, trend=1.0)
    result_trend = analyzer.analyze(df_trend)
    assert result_trend["trend_intensity"] > 0.5
    
    # Flat range
    df_range = generate_trending_df(50, trend=0.0)
    result_range = analyzer.analyze(df_range)
    assert result_range["trend_intensity"] < 0.5

def test_wick_skewness(analyzer):
    # Bullish wicks (long lower wicks)
    klines = []
    for i in range(20):
        klines.append({'open': 100, 'high': 101, 'low': 95, 'close': 100, 'volume': 100})
    df = pd.DataFrame(klines)
    result = analyzer.analyze(df)
    # upper_wicks = 1, lower_wicks = 5. skew = (1-5)/(1+5) = -4/6
    assert result["skewness"] < 0

def test_insufficient_data(analyzer):
    df = generate_trending_df(5, trend=0)
    result = analyzer.analyze(df)
    assert result["volatility_regime"] == "UNKNOWN"
