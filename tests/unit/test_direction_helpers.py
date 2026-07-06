"""Unit tests for static direction helpers extracted from MarginOrderExecutor."""

import pytest
from src.agent.order_executor import MarginOrderExecutor


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
