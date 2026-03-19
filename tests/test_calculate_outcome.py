"""
Tests for the calculate_outcome function, especially the new TP/SL hit hint logic.
"""
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from review import calculate_outcome


def test_basic_outcome():
    """Basic outcome calculation without prediction data."""
    klines = [
        [0, "100", "110", "90", "105", "1000", 0],
        [0, "105", "115", "95", "108", "1000", 0],
    ]
    result = calculate_outcome(klines, 100.0)
    assert result["start_price"] == 100.0
    assert result["max_price_reached"] == 115.0
    assert result["min_price_reached"] == 90.0
    assert result["final_close_price"] == 108.0
    assert result["outcome_period_bars"] == 2
    assert "tp_reached" not in result  # No prediction, no hints


def test_buy_tp_hit():
    """BUY trade where TP is reached."""
    klines = [
        [0, "100", "110", "95", "108", "1000", 0],
    ]
    prediction = {"action": "BUY", "take_profit": 108.0, "stop_loss": 92.0}
    result = calculate_outcome(klines, 100.0, prediction=prediction)
    assert result["tp_reached"] is True
    assert result["sl_reached"] is False


def test_buy_sl_hit():
    """BUY trade where SL is reached."""
    klines = [
        [0, "100", "105", "88", "90", "1000", 0],
    ]
    prediction = {"action": "BUY", "take_profit": 115.0, "stop_loss": 92.0}
    result = calculate_outcome(klines, 100.0, prediction=prediction)
    assert result["tp_reached"] is False
    assert result["sl_reached"] is True


def test_sell_tp_hit():
    """SELL trade where TP (lower target) is reached."""
    klines = [
        [0, "100", "102", "88", "90", "1000", 0],
    ]
    prediction = {"action": "SELL", "take_profit": 90.0, "stop_loss": 105.0}
    result = calculate_outcome(klines, 100.0, prediction=prediction)
    assert result["tp_reached"] is True
    assert result["sl_reached"] is False


def test_hold_no_tp_sl():
    """HOLD trade should have tp_reached=False and sl_reached=False."""
    klines = [
        [0, "100", "110", "90", "105", "1000", 0],
    ]
    prediction = {"action": "HOLD", "take_profit": None, "stop_loss": None}
    result = calculate_outcome(klines, 100.0, prediction=prediction)
    assert result["tp_reached"] is False
    assert result["sl_reached"] is False


def test_empty_klines():
    """Empty klines should return empty dict."""
    result = calculate_outcome([], 100.0)
    assert result == {}
