"""Tests for exception propagation and error handling in MarginOrderExecutor."""

import pytest
from unittest.mock import MagicMock, patch


def _make_executor():
    """Build a MarginOrderExecutor with mocked client for exception testing."""
    from src.agent.order_executor import MarginOrderExecutor

    executor = MarginOrderExecutor.__new__(MarginOrderExecutor)
    executor.client = MagicMock()
    executor.global_cfg = {
        "trade_management": {"risk_per_trade": 0.02, "net_qty_tolerance": 1e-8},
        "guardian": {"exit_ladder": {"levels": []}},
    }
    executor.manual_balance_usdt = 10000.0
    executor._last_conflict_key = {}
    executor._global_config_raw = {}
    executor._trade_config_cache = {"BTCUSDT": {
        "benchmark_symbol": "BTCUSDT",
        "risk_per_trade": 0.02,
        "net_qty_tolerance": 1e-8,
        "precision_qty": 4,
        "precision_price": 2,
        "min_order_qty": 0.001,
        "sl_slippage_buffer": 0.5,
    }}
    return executor


class TestGuardianExceptionHandling:
    def test_guardian_config_error_returns_state(self):
        """Missing symbol config falls back gracefully."""
        executor = _make_executor()
        executor.client.get_symbol_position.return_value = MagicMock(net_qty=0.5)
        executor.client.get_active_orders.return_value = []
        executor._get_trade_config = MagicMock(side_effect=KeyError("symbol not configured"))

        result, level = executor.guardian_check("UNKNOWN", {"direction": "LONG"})
        assert result is not None

    def test_guardian_oco_failure_triggers_emergency_close(self):
        """When OCO placement fails, emergency close is attempted."""
        executor = _make_executor()
        executor.client.get_symbol_position.return_value = MagicMock(net_qty=1.0)
        executor.client.get_active_orders.return_value = []
        executor.client.get_ticker_price.return_value = 60000
        executor.client.place_oco_order.return_value = False
        executor.client.execute_market_close.return_value = True
        executor._get_trade_config = MagicMock(return_value=executor._trade_config_cache["BTCUSDT"])

        result, level = executor.guardian_check("BTCUSDT", {
            "direction": "LONG",
            "tp_price": 62000,
            "sl_price": 58000,
        })
        executor.client.execute_market_close.assert_called_once()
        assert result == {}  # trade state cleared after emergency close

class TestOptimizeExceptionHandling:
    def test_optimize_no_active_orders_returns_safe(self):
        """Optimize with empty orders list does not crash."""
        executor = _make_executor()
        executor.client.get_symbol_position.return_value = MagicMock(net_qty=1.0)
        executor.client.get_active_orders.return_value = []
        executor._get_trade_config = MagicMock(return_value=executor._trade_config_cache["BTCUSDT"])

        intact, update = executor._optimize_same_direction(
            "BTCUSDT", "LONG", 1.0, [], 62000, 58000,
        )
        assert intact is True
        # Should still return state update even without existing orders
        assert update is not None

    def test_optimize_cancel_failure_returns_safe(self):
        """When cancel_all_symbol_orders fails, original protection is kept."""
        executor = _make_executor()
        executor.client.get_symbol_position.return_value = MagicMock(net_qty=1.0)
        executor.client.get_active_orders.return_value = []
        executor.client.cancel_all_symbol_orders.return_value = False
        executor._get_trade_config = MagicMock(return_value=executor._trade_config_cache["BTCUSDT"])

        intact, update = executor._optimize_same_direction(
            "BTCUSDT", "LONG", 1.0, [], 62000, 58000,
        )
        assert intact is True
        # State update preserves old TP/SL
        assert "tp_price" in update
        assert "sl_price" in update


class TestMigrationExceptionHandling:
    def test_dynamic_sl_zero_sl_lock_returns_noop(self):
        """sl_lock <= 0 returns no migration needed."""
        executor = _make_executor()
        intact, new_sl = executor._migrate_dynamic_sl(
            "BTCUSDT", "LONG", 58000, 62000, 60000,
            executor._trade_config_cache["BTCUSDT"], 0,
        )
        assert intact is True
        assert new_sl is None

    def test_dynamic_sl_no_change_returns_noop(self):
        """SL already at price — zero gap means no migration needed."""
        executor = _make_executor()
        sl_lock = 0.65
        sl = 60000  # SL at current_price — gap is 0
        intact, new_sl = executor._migrate_dynamic_sl(
            "BTCUSDT", "LONG", sl, 62000, 60000,
            executor._trade_config_cache["BTCUSDT"], sl_lock,
        )
        assert intact is True
        assert new_sl is None
