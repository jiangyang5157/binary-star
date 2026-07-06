"""Tests for exception propagation and error handling in MarginOrderExecutor."""

import pytest
from unittest.mock import MagicMock

from tests.executor_fixtures import make_executor

# Reusable trade config used by multiple tests
_BTC_CONFIG = {
    "benchmark_symbol": "BTCUSDT",
    "risk_per_trade": 0.02,
    "net_qty_tolerance": 1e-8,
    "precision_qty": 4,
    "precision_price": 2,
    "min_order_qty": 0.001,
    "sl_slippage_buffer": 0.5,
}


class TestGuardianExceptionHandling:
    def test_guardian_config_error_returns_state(self):
        """Missing symbol config falls back gracefully."""
        executor, client = make_executor()
        client.get_symbol_position.return_value = MagicMock(net_qty=0.5)
        client.get_active_orders.return_value = []
        executor._get_trade_config = MagicMock(side_effect=KeyError("symbol not configured"))

        result, level = executor.guardian_check("UNKNOWN", {"direction": "LONG"})
        assert result is not None

    def test_guardian_oco_failure_triggers_emergency_close(self):
        """When OCO placement fails, emergency close is attempted."""
        executor, client = make_executor()
        client.get_symbol_position.return_value = MagicMock(net_qty=1.0)
        client.get_active_orders.return_value = []
        client.get_ticker_price.return_value = 60000
        client.place_oco_order.return_value = False
        client.execute_market_close.return_value = True
        executor._get_trade_config = MagicMock(return_value=_BTC_CONFIG)

        result, level = executor.guardian_check("BTCUSDT", {
            "direction": "LONG",
            "tp_price": 62000,
            "sl_price": 58000,
        })
        client.execute_market_close.assert_called_once()
        assert result == {}


class TestOptimizeExceptionHandling:
    def test_optimize_no_active_orders_returns_safe(self):
        """Optimize with empty orders list does not crash."""
        executor, client = make_executor()
        client.get_symbol_position.return_value = MagicMock(net_qty=1.0)
        client.get_active_orders.return_value = []
        executor._get_trade_config = MagicMock(return_value=_BTC_CONFIG)

        intact, update = executor._optimize_same_direction(
            "BTCUSDT", "LONG", 1.0, [], 62000, 58000,
        )
        assert intact is True
        assert update is not None

    def test_optimize_cancel_failure_returns_safe(self):
        """When cancel_all_symbol_orders fails, original protection is kept."""
        executor, client = make_executor()
        client.get_symbol_position.return_value = MagicMock(net_qty=1.0)
        client.get_active_orders.return_value = []
        client.cancel_all_symbol_orders.return_value = False
        executor._get_trade_config = MagicMock(return_value=_BTC_CONFIG)

        intact, update = executor._optimize_same_direction(
            "BTCUSDT", "LONG", 1.0, [], 62000, 58000,
        )
        assert intact is True
        assert update is None


class TestMigrationExceptionHandling:
    def test_dynamic_sl_zero_sl_lock_returns_noop(self):
        """sl_lock <= 0 returns no migration needed."""
        executor, _ = make_executor()
        intact, new_sl = executor._apply_sl_lock(
            "BTCUSDT", "LONG", 58000, 62000, 60000,
            _BTC_CONFIG, 0,
        )
        assert intact is True
        assert new_sl is None

    def test_dynamic_sl_no_change_returns_noop(self):
        """SL already at lock value — no migration needed."""
        executor, _ = make_executor()
        sl_lock = 0.24
        avg_entry = 70000.0
        current_tp = 75000.0
        current_sl = avg_entry + (current_tp - avg_entry) * 0.24  # 71200
        intact, new_sl = executor._apply_sl_lock(
            "BTCUSDT", "LONG", current_sl, current_tp, avg_entry,
            _BTC_CONFIG, sl_lock,
        )
        assert intact is True
        assert new_sl is None
