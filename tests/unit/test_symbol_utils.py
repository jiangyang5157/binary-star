"""Tests for src/utils/symbol_utils.py"""
import pytest
from src.utils.symbol_utils import resolve_symbol, resolve_symbols


class TestResolveSymbol:
    def test_basic_prefix(self):
        assert resolve_symbol("BTC") == "BTCUSDT"

    def test_lowercase_prefix(self):
        assert resolve_symbol("btc") == "BTCUSDT"

    def test_already_full_symbol(self):
        assert resolve_symbol("BTCUSDT") == "BTCUSDT"

    def test_strips_whitespace(self):
        assert resolve_symbol("  eth  ") == "ETHUSDT"

    def test_xaut(self):
        assert resolve_symbol("XAUT") == "XAUTUSDT"

    def test_rejects_empty(self):
        with pytest.raises(ValueError, match="Symbol must be at least 2 characters"):
            resolve_symbol("")

    def test_rejects_too_short(self):
        with pytest.raises(ValueError, match="Symbol must be at least 2 characters"):
            resolve_symbol("X")

    def test_rejects_non_alphanumeric(self):
        with pytest.raises(ValueError, match="Symbol must be alphanumeric"):
            resolve_symbol("BT-C")


class TestResolveSymbols:
    def test_single(self):
        assert resolve_symbols("BTC") == ["BTCUSDT"]

    def test_csv_list(self):
        assert resolve_symbols("BTC,ETH,XAUT") == ["BTCUSDT", "ETHUSDT", "XAUTUSDT"]

    def test_csv_with_spaces(self):
        assert resolve_symbols(" BTC , ETH , XAUT ") == ["BTCUSDT", "ETHUSDT", "XAUTUSDT"]

    def test_deduplicates(self):
        assert resolve_symbols("BTC,BTC,ETH") == ["BTCUSDT", "ETHUSDT"]

    def test_preserves_order(self):
        assert resolve_symbols("XAUT,BTC,ETH") == ["XAUTUSDT", "BTCUSDT", "ETHUSDT"]

    def test_mixed_formats(self):
        assert resolve_symbols("BTC,ETHUSDT") == ["BTCUSDT", "ETHUSDT"]

    def test_empty_string(self):
        with pytest.raises(ValueError, match="At least one symbol required"):
            resolve_symbols("")

    def test_empty_csv_parts(self):
        with pytest.raises(ValueError, match="At least one symbol required"):
            resolve_symbols(",,")

    def test_rejects_invalid_in_csv(self):
        with pytest.raises(ValueError, match="Symbol must be at least 2 characters"):
            resolve_symbols("BTC,X,")
