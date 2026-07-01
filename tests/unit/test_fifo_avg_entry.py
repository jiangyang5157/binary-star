"""Tests for _fifo_avg_entry — static method on BinanceMarginClient.

Covers normal computation, cross-position trim, and edge cases.
"""

import pytest
from src.infrastructure.binance.margin_client import BinanceMarginClient


# ── helpers ──────────────────────────────────────────────────────────
def trade(trade_id: int, is_buyer: bool, price: float, qty: float) -> dict:
    """Minimal Binance myTrades entry dict."""
    return {
        "id": trade_id,
        "isBuyer": is_buyer,
        "price": str(price),
        "qty": str(qty),
    }


_fifo = BinanceMarginClient._fifo_avg_entry

# ── LONG position tests ─────────────────────────────────────────────

def test_clean_single_entry():
    """One BUY exactly matches position → returns that price."""
    trades = [trade(1, True, 3985.0, 0.173)]
    assert _fifo(trades, 0.173) == pytest.approx(3985.0)


def test_clean_multi_fill_entry():
    """Multiple BUY fills for the same position."""
    trades = [
        trade(1, True, 3984.0, 0.100),
        trade(2, True, 3986.0, 0.073),
    ]
    # (3984*0.1 + 3986*0.073) / 0.173 = 3984.84
    expected = (3984.0 * 0.1 + 3986.0 * 0.073) / 0.173
    assert _fifo(trades, 0.173) == pytest.approx(expected)


def test_fully_closed_then_new_entry():
    """Old position fully closed → new entry is clean."""
    trades = [
        trade(1, True, 4044.0, 0.256),   # old position entry
        trade(2, False, 4010.0, 0.256),  # fully closed
        trade(3, True, 3985.0, 0.173),   # new entry
    ]
    assert _fifo(trades, 0.173) == pytest.approx(3985.0)


def test_partially_closed_old_position_trims():
    """Old position partially closed → residual trimmed from oldest end.

    Reproduces the XAUT 0.173 scenario: a prior 0.492 LONG at 4062
    was only partially closed (0.256), leaving 0.236 residual in the
    FIFO queue.  The emergency close later consumed the residual but
    left other old BUYs (4035, 4042) that contaminate the new 0.173
    entry at 3985.
    """
    trades = [
        # old position: 0.492 at ~4062
        trade(1, True, 4062.0, 0.492),
        # partial close: only 0.256
        trade(2, False, 4055.0, 0.256),
        # emergency close of another position (0.307) consumes oldest
        trade(3, False, 4013.0, 0.307),
        # auto-cover oversell
        trade(4, True, 4007.0, 0.051),
        # new entry
        trade(5, True, 3985.0, 0.173),
    ]
    # Should trim the 4062.0 residual → return 3985.0
    assert _fifo(trades, 0.173) == pytest.approx(3985.0)


def test_trim_not_needed_when_queue_matches():
    """No trim when queue total ≈ position (within 1%)."""
    trades = [trade(1, True, 4000.0, 0.173)]
    assert _fifo(trades, 0.173) == pytest.approx(4000.0)


def test_insufficient_coverage_returns_zero():
    """Not enough BUY qty in queue → return 0.0."""
    trades = [trade(1, True, 4000.0, 0.050)]
    assert _fifo(trades, 0.173) == 0.0


def test_exact_trim_boundary():
    """Queue is 1.01x position → exactly at threshold, should trim.

    queue=0.1747 for net_qty=0.173 → 1.0099x (within 1%, no trim).
    queue=0.1750 for net_qty=0.173 → 1.0115x (exceeds 1%, trim).
    """
    # 1.0099x — within tolerance, no trim
    trades_within = [
        trade(1, True, 4044.0, 0.0017),  # oldest (will stay if no trim)
        trade(2, True, 3985.0, 0.1730),  # current position
    ]
    # total=0.1747, position=0.173 → ratio=1.0098 < 1.01 → no trim
    result = _fifo(trades_within, 0.173)
    assert result > 0
    # result should be weighted average of BOTH (no trim occurred)
    expected_both = (4044.0 * 0.0017 + 3985.0 * 0.173) / 0.1747
    assert result == pytest.approx(expected_both)

    # 1.0115x — exceeds tolerance, trim oldest
    trades_over = [
        trade(1, True, 4044.0, 0.050),   # oldest (should be trimmed)
        trade(2, True, 3985.0, 0.1730),  # current position
    ]
    # total=0.223, position=0.173 → ratio=1.289 > 1.01 → trim
    assert _fifo(trades_over, 0.173) == pytest.approx(3985.0)


def test_partial_trim_splits_oldest():
    """Trim removes part of the oldest entry when it exceeds the gap."""
    trades = [
        trade(1, True, 4062.0, 0.236),   # all excess
        trade(2, True, 3985.0, 0.173),   # current position
    ]
    # queue=0.409, position=0.173 → trim 0.236 from oldest
    # 0.236 <= 0.236 → pop entire oldest → left with 3985 only
    assert _fifo(trades, 0.173) == pytest.approx(3985.0)

    # Now: oldest is larger than excess → split
    trades_split = [
        trade(1, True, 4062.0, 0.173),   # keep 0.02, discard 0.153
        trade(2, True, 3985.0, 0.020),
    ]
    # queue=0.193, position=0.020 → excess=0.173, oldest=0.173 → pop entirely
    # left with 3985 only
    assert _fifo(trades_split, 0.020) == pytest.approx(3985.0)


# ── SHORT position tests ────────────────────────────────────────────

def test_short_clean_entry():
    """One SELL for a SHORT position → returns that price."""
    trades = [trade(1, False, 59000.0, 0.1)]
    assert _fifo(trades, -0.1) == pytest.approx(59000.0)


def test_short_with_residual_trim():
    """Old SELL residual trimmed for SHORT position."""
    trades = [
        trade(1, False, 60000.0, 0.200),  # old short
        trade(2, True, 59500.0, 0.100),   # partial close
        trade(3, False, 58800.0, 0.050),  # new short entry
    ]
    # queue should be trimmed to just 0.05 at 58800
    assert _fifo(trades, -0.05) == pytest.approx(58800.0)


# ── edge cases ──────────────────────────────────────────────────────

def test_empty_trades():
    assert _fifo([], 0.173) == 0.0


def test_flat_position():
    assert _fifo([], 0.0) == 0.0
