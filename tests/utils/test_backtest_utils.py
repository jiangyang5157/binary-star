import pandas as pd
import numpy as np
import pytest
from datetime import datetime, timezone, timedelta
from src.analyzer.historical_sampler import MarketRegimeAnalyzer, SpacedSampler, RegimeSampler

@pytest.fixture
def mock_klines():
    """Generates 50 days of synthetic kline data for regime testing."""
    base_time = datetime(2024, 1, 1, tzinfo=timezone.utc)
    klines = []
    
    # Generate a Bull High Vol sequence followed by a Bear Low Vol sequence
    for i in range(50):
        ts = int((base_time + timedelta(days=i)).timestamp() * 1000)
        # Bull High Vol: increasing price with high variance
        if i < 25:
            price = 100 + i * 2 + (5 if i % 2 == 0 else -5)
        else:
            # Bear Low Vol: decreasing price with low variance
            price = 150 - (i - 25) * 1 + (1 if i % 2 == 0 else -1)
            
        # [OpenTime, Open, High, Low, Close, Volume, CloseTime, ...]
        klines.append([ts, price, price+2, price-2, price, 1000, ts+86399999, 0, 0, 0, 0, 0])
        
    return klines

def test_market_regime_analyzer(mock_klines):
    analyzer = MarketRegimeAnalyzer(ema_period=5, vol_period=5) # Smaller periods for short test data
    df = analyzer.classify_regimes(mock_klines)
    
    assert not df.empty
    assert 'regime' in df.columns
    # Check that we have both Bull and Bear regimes
    regimes = df['regime'].unique()
    assert any("BULL" in r for r in regimes)
    assert any("BEAR" in r for r in regimes)

def test_spaced_sampler_exact_count():
    sampler = SpacedSampler()
    # Create 100 timestamps
    df = pd.DataFrame({
        'timestamp': [datetime(2024, 1, 1) + timedelta(days=i) for i in range(100)]
    })
    
    # Test different counts
    for count in [1, 5, 10, 50, 100]:
        samples = sampler.sample(df, count)
        assert len(samples) == count
    
    # Test more samples than available
    samples = sampler.sample(df, 150)
    assert len(samples) == 100

def test_regime_sampler_distribution():
    sampler = RegimeSampler()
    # Create 100 timestamps with 2 regimes (80% A, 20% B)
    df = pd.DataFrame({
        'timestamp': [datetime(2024, 1, 1) + timedelta(days=i) for i in range(100)],
        'regime': (["BULL_LOW"] * 80) + (["BEAR_HIGH"] * 20)
    })
    
    # Target 15 samples
    count = 15
    samples = sampler.sample(df, count)
    
    assert len(samples) == count
    
    # Check proportionality (80% of 15 is 12, 20% of 15 is 3)
    # We use a deterministic random_state=42 in our implementation
    bull_count = sum(1 for s in samples if s < datetime(2024, 1, 1) + timedelta(days=80))
    bear_count = sum(1 for s in samples if s >= datetime(2024, 1, 1) + timedelta(days=80))
    
    assert bull_count == 12
    assert bear_count == 3

def test_regime_sampler_rounding_safety():
    """Ensure exact count even with awkward splits (e.g., 3 regimes, 10 samples)."""
    sampler = RegimeSampler()
    df = pd.DataFrame({
        'timestamp': [datetime(2024, 1, 1) + timedelta(days=i) for i in range(30)],
        'regime': (["A"] * 10) + (["B"] * 10) + (["C"] * 10)
    })
    
    count = 10
    samples = sampler.sample(df, count)
    assert len(samples) == count # 10 / 3 = 3.33. Rounded to 3,3,4 or similar to hit 10.
