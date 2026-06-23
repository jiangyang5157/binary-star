"""Tests for liquidity slippage calculation."""
import pytest
from src.utils.math_utils import MathTools


def test_calculate_liquidity_slippage_high_volume():
    """High-volume bucket → minimum slippage, no vacuum."""
    profile = [{"price": 100, "volume": 1000}]
    res = MathTools.calculate_liquidity_slippage(100, profile, 10, 5.0, 50.0)
    assert res["slippage_bps"] == 5.0
    assert res["price_adjusted"] == 100.05
    assert res["is_vacuum_zone"] is False


def test_calculate_liquidity_slippage_vacuum_zone():
    """Low-volume bucket (relative to max in profile) → high slippage penalty."""
    # Two buckets: high-vol anchor + low-vol target → vacuum detected
    profile = [{"price": 120, "volume": 50}, {"price": 100, "volume": 1000}]
    res = MathTools.calculate_liquidity_slippage(120, profile, 10, 5.0, 50.0)
    # max_vol=1000, quality=50/1000=0.05, is_vacuum (quality < 0.1)
    # extra = (1 - 0.05) * (50 - 5) = 0.95 * 45 = 42.75, total = 5 + 42.75 = 47.75
    assert res["slippage_bps"] == pytest.approx(47.75)
    assert res["is_vacuum_zone"] is True


def test_calculate_liquidity_slippage_boundary():
    """Quality exactly at vacuum threshold (0.1) → NOT vacuum."""
    profile = [{"price": 100, "volume": 100}]  # vol/max_vol = 100/1000 = 0.1
    res = MathTools.calculate_liquidity_slippage(100, profile, 10, 5.0, 50.0)
    assert res["is_vacuum_zone"] is False


def test_calculate_liquidity_slippage_between_buckets():
    """Price between two buckets → nearest bucket used (base slippage)."""
    profile = [
        {"price": 100, "volume": 1000},
        {"price": 120, "volume": 100},
    ]
    res = MathTools.calculate_liquidity_slippage(105, profile, 10, 5.0, 50.0)
    assert res["slippage_bps"] == 5.0  # nearest high-volume bucket


def test_calculate_liquidity_slippage_empty_profile():
    """Empty volume profile → fall back to base slippage without crashing."""
    res = MathTools.calculate_liquidity_slippage(100, [], 10, 5.0, 50.0)
    assert res["slippage_bps"] >= 0


def test_calculate_liquidity_slippage_single_bucket():
    """Single bucket profile → use that bucket."""
    profile = [{"price": 100, "volume": 500}]
    res = MathTools.calculate_liquidity_slippage(100, profile, 10, 5.0, 50.0)
    assert res["slippage_bps"] == 5.0
    assert res["liquidity_quality"] >= 0


def test_calculate_liquidity_slippage_zero_volume():
    """Zero volume in all buckets → divide-by-zero guard."""
    profile = [{"price": 100, "volume": 0}]
    res = MathTools.calculate_liquidity_slippage(100, profile, 10, 5.0, 50.0)
    assert "slippage_bps" in res  # should not crash
