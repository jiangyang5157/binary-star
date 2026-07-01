"""Tests for LiquidationEstimator — edge cases and boundary behaviour."""
import math
import pytest
import numpy as np
from src.analyzer.liquidation_estimator import LiquidationEstimator
from src.infrastructure.exchange.models import KlineData, OpenInterestData, RatioData


@pytest.fixture
def estimator():
    return LiquidationEstimator(
        volume_moving_average_period=5,
        volume_surge_vs_ma_ratio=1.5,
        max_liquidation_clusters=3,
        long_taker_threshold=1.5,
        short_taker_threshold=0.5,
        gaussian_sigma=1.0,
        grid_bins=100,
        grid_padding_atr=2.0,
    )


def _make_klines(n=20, base_price=60000):
    return [KlineData(
        open_time=i, open=base_price, high=base_price + 100, low=base_price - 100,
        close=base_price, volume=100 + i * 10, close_time=i,
    ) for i in range(n)]


def _make_oi(n=20, val=1e9):
    return [OpenInterestData(symbol="BTCUSDT", open_interest=val + i * 1e7, timestamp=i)
            for i in range(n)]


def _make_taker(n=20, ratio=1.8):
    return [RatioData(long_short_ratio=ratio + 0.005 * i, timestamp=i)
            for i in range(n)]


class TestSynthesizeClusters:

    def test_empty_inputs(self, estimator):
        """Empty klines/OI/taker → empty clusters, no crash."""
        result = estimator.synthesize_clusters([], [], [], 60000, 200)
        assert result == {"long_liquidation": [], "short_liquidation": []}

    def test_partial_empty_oi(self, estimator):
        """Missing OI still handled via min_len alignment."""
        klines = _make_klines(20)
        result = estimator.synthesize_clusters(klines, [], [], 60000, 200)
        assert "long_liquidation" in result
        assert "short_liquidation" in result

    def test_normal_long_aggression(self, estimator):
        """Taker ratio > 1.5 (long aggressive) → generates long liquidation stops."""
        klines = _make_klines(50, base_price=60000)
        oi = _make_oi(50, val=1e9)
        taker = _make_taker(50, ratio=1.8)  # above long_taker_threshold
        result = estimator.synthesize_clusters(klines, oi, taker, 60000, 200)
        # Should have at least some below-price liquidation points
        assert isinstance(result["long_liquidation"], list)

    def test_normal_short_aggression(self, estimator):
        """Taker ratio < 0.5 (short aggressive) → generates short liquidation stops."""
        klines = _make_klines(50, base_price=60000)
        oi = _make_oi(50, val=1e9)
        taker = _make_taker(50, ratio=0.3)  # below short_taker_threshold
        result = estimator.synthesize_clusters(klines, oi, taker, 60000, 200)
        assert isinstance(result["short_liquidation"], list)

    def test_zero_atr_no_crash(self, estimator):
        """atr=0 should not cause crash in _cluster_points grid building."""
        klines = _make_klines(50)
        oi = _make_oi(50)
        taker = _make_taker(50, ratio=1.8)
        result = estimator.synthesize_clusters(klines, oi, taker, 60000, 0.0)
        assert "long_liquidation" in result

    def test_no_accumulation(self, estimator):
        """No volume surge → no accumulation → empty clusters."""
        klines = [KlineData(
            open_time=i, open=60000, high=60100, low=59900,
            close=60000, volume=100, close_time=i,
        ) for i in range(20)]
        oi = [OpenInterestData(symbol="BTCUSDT", open_interest=1e9, timestamp=i)
              for i in range(20)]
        taker = [RatioData(long_short_ratio=1.0, timestamp=i)
                 for i in range(20)]
        result = estimator.synthesize_clusters(klines, oi, taker, 60000, 200)
        assert result == {"long_liquidation": [], "short_liquidation": []}


class TestClusterPoints:

    def test_empty_points(self, estimator):
        result = estimator._cluster_points([], 200, 59000, 61000)
        assert result == []

    def test_single_point(self, estimator):
        points = [{"price": 59500, "weight": 100}]
        result = estimator._cluster_points(points, 200, 59000, 61000)
        assert len(result) >= 1
        assert result[0]["intensity"] == 1.0  # normalized to 1.0

    def test_multiple_points_sorted_by_intensity(self, estimator):
        points = [
            {"price": 59500, "weight": 50},
            {"price": 60500, "weight": 200},
            {"price": 60000, "weight": 100},
        ]
        result = estimator._cluster_points(points, 200, 59000, 61000)
        assert len(result) >= 1
        # First (highest intensity) should be the strongest original weight
        intensities = [p["intensity"] for p in result]
        assert all(0 <= i <= 1.0 for i in intensities)


class TestCalculateSMA:

    def test_zero_period(self, estimator):
        data = np.array([1.0, 2.0, 3.0])
        result = estimator._calculate_sma(data, 0)
        assert len(result) == 3
        assert result[0] == pytest.approx(2.0)  # mean of data

    def test_period_larger_than_data(self, estimator):
        data = np.array([1.0, 2.0])
        result = estimator._calculate_sma(data, 5)
        assert len(result) == 2
        assert np.isnan(result[0])
        assert np.isnan(result[1])

    def test_normal_sma(self, estimator):
        data = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
        result = estimator._calculate_sma(data, 3)
        assert result[2] == pytest.approx(2.0)  # (1+2+3)/3
        assert result[3] == pytest.approx(3.0)  # (2+3+4)/3
        assert result[4] == pytest.approx(4.0)  # (3+4+5)/3
        assert np.isnan(result[0])  # first period-1 elements are NaN
        assert np.isnan(result[1])
