"""Unit tests for static direction helpers extracted from MarginOrderExecutor."""

import pytest
from src.agent.order_executor import MarginOrderExecutor
from src.infrastructure.exchange.models import MarginOrder


class TestExitSide:
    def test_long_returns_sell(self):
        assert MarginOrderExecutor._exit_side("LONG") == "SELL"

    def test_short_returns_buy(self):
        assert MarginOrderExecutor._exit_side("SHORT") == "BUY"


class TestEntrySide:
    def test_long_returns_buy(self):
        assert MarginOrderExecutor._entry_side("LONG") == "BUY"

    def test_short_returns_sell(self):
        assert MarginOrderExecutor._entry_side("SHORT") == "SELL"


class TestPriceDelta:
    def test_long_in_profit(self):
        """LONG: current > entry → positive."""
        assert MarginOrderExecutor._price_delta("LONG", 100, 90) == 10

    def test_long_in_loss(self):
        """LONG: current < entry → negative."""
        assert MarginOrderExecutor._price_delta("LONG", 90, 100) == -10

    def test_short_in_profit(self):
        """SHORT: entry > current → positive."""
        assert MarginOrderExecutor._price_delta("SHORT", 100, 110) == 10

    def test_short_in_loss(self):
        """SHORT: entry < current → negative."""
        assert MarginOrderExecutor._price_delta("SHORT", 110, 100) == -10


class TestBufferedSL:
    def test_long_sl_below_trigger(self):
        """LONG: -buffer → SL limit below trigger price."""
        assert MarginOrderExecutor._buffered_sl(68000, 10, "LONG") == 67990

    def test_short_sl_above_trigger(self):
        """SHORT: +buffer → SL limit above trigger price."""
        assert MarginOrderExecutor._buffered_sl(68000, 10, "SHORT") == 68010

    def test_zero_buffer_no_change(self):
        """buffer=0 → no offset."""
        assert MarginOrderExecutor._buffered_sl(100, 0, "LONG") == 100
        assert MarginOrderExecutor._buffered_sl(100, 0, "SHORT") == 100


class TestExtractOcoPrices:
    def test_both_legs_present(self):
        """TP (LIMIT) and SL (STOP_LOSS_LIMIT) both extracted."""
        orders = [
            MarginOrder("BTCUSDT", "1", "", 75000, 0.5, 0, "NEW", "GTC", "LIMIT", "SELL", 0),
            MarginOrder("BTCUSDT", "2", "", 0, 0.5, 0, "NEW", "GTC", "STOP_LOSS_LIMIT", "SELL", 0, stop_price=68000),
        ]
        tp, sl = MarginOrderExecutor._extract_oco_prices(orders, "SELL")
        assert tp == 75000
        assert sl == 68000

    def test_falls_back_to_defaults_when_empty(self):
        tp, sl = MarginOrderExecutor._extract_oco_prices([], "SELL", default_tp=72000, default_sl=67000)
        assert tp == 72000
        assert sl == 67000

    def test_ignores_wrong_side_orders(self):
        """Entry-side order (BUY) ignored when looking for exit-side (SELL)."""
        orders = [
            MarginOrder("BTCUSDT", "1", "", 70000, 0.5, 0, "NEW", "GTC", "LIMIT", "BUY", 0),
        ]
        tp, sl = MarginOrderExecutor._extract_oco_prices(orders, "SELL", default_tp=72000, default_sl=67000)
        assert tp == 72000  # unchanged — BUY order ignored
        assert sl == 67000

    def test_only_tp_present(self):
        orders = [
            MarginOrder("BTCUSDT", "1", "", 75000, 0.5, 0, "NEW", "GTC", "LIMIT", "SELL", 0),
        ]
        tp, sl = MarginOrderExecutor._extract_oco_prices(orders, "SELL", default_sl=68000)
        assert tp == 75000
        assert sl == 68000  # fallback
