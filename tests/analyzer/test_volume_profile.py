import pytest
import pandas as pd
import numpy as np
from src.analyzer.volume_profile import VolumeProfileAnalyzer, VolumeProfileConfig

@pytest.fixture
def vp_config():
    return VolumeProfileConfig(
        value_area_ratio=0.7,
        resolution_bins=50,
        atr_period=14,
        max_high_volume_node_count=3,
        max_low_volume_node_count=3,
        high_volume_node_detection_threshold=0.1,
        low_volume_node_detection_threshold=0.1,
        min_node_distance=1,
        balanced_atr_multiplier=1.5
    )

@pytest.fixture
def analyzer(vp_config):
    return VolumeProfileAnalyzer(config=vp_config)

def generate_mock_klines(count=100, trend=0):
    """Generates mock kline data [Time, O, H, L, C, V, ...]"""
    base_time = 1700000000000
    klines = []
    for i in range(count):
        t = base_time + (i * 60000)
        p = 100 + (i * trend) + np.random.normal(0, 0.5)
        o = p - 0.1
        h = p + 0.2
        l = p - 0.2
        c = p
        v = 10 + np.random.uniform(0, 20)
        # Standard Binance kline format (12 elements)
        klines.append([t, str(o), str(h), str(l), str(c), str(v), t+59999, "100", 10, "5", "50", "0"])
    return klines

def test_preprocessing(analyzer):
    klines = generate_mock_klines(50)
    df = analyzer.process_klines(klines)
    assert isinstance(df, pd.DataFrame)
    assert len(df) == 50
    assert 'atr' in df.columns
    assert 'typical_price' in df.columns

def test_profile_calculation(analyzer):
    # Create a distribution centered around 100
    klines = []
    base_time = 1700000000000
    for i in range(100):
        t = base_time + (i * 60000)
        # Most prices near 100, some outliers
        p = 100 + np.random.normal(0, 5)
        klines.append([t, str(p-0.1), str(p+0.2), str(p-0.2), str(p), "10", t+59999, "100", 10, "5", "50", "0"])
    
    df = analyzer.process_klines(klines)
    profile = analyzer.calculate_profile(df)
    
    assert "poc" in profile
    assert "vah" in profile
    assert "val" in profile
    assert profile["vah"] > profile["val"]
    assert profile["val"] <= profile["poc"] <= profile["vah"]

def test_significant_nodes(analyzer):
    # Create a multi-modal distribution (two peaks)
    klines = []
    base_time = 1700000000000
    for i in range(100):
        t = base_time + (i * 60000)
        # Peaks at 100 and 150
        p = 100 + np.random.normal(0, 2) if i < 50 else 150 + np.random.normal(0, 2)
        klines.append([t, str(p-0.1), str(p+0.2), str(p-0.2), str(p), "10", t+59999, "100", 10, "5", "50", "0"])
    
    df = analyzer.process_klines(klines)
    profile = analyzer.calculate_profile(df)
    nodes = analyzer.find_significant_nodes(profile)
    
    assert "hvn" in nodes
    assert "lvn" in nodes
    assert len(nodes["hvn"]) > 0
    # Higher strength should be near the peaks
    prices = [n["price"] for n in nodes["hvn"]]
    # Relaxed assertions to account for binning/randomness
    assert len(prices) >= 2
    assert any(p > 130 for p in prices)
    assert any(p < 120 for p in prices)

def test_empty_data(analyzer):
    result = analyzer.analyze([])
    assert result["poc"] == 0.0
    assert result["market_regime"] == "UNKNOWN"
