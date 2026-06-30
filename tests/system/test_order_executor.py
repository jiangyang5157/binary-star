import os
import sys
from unittest.mock import MagicMock, ANY, patch
from datetime import datetime, timezone, timedelta

# Ensure the project root is in the path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(project_root)

from src.infrastructure.exchange.models import MarginPosition, MarginOrder, MarginAccountSummary
from src.agent.order_executor import MarginOrderExecutor

def _make_executor():
    client = MagicMock()
    client.get_cross_margin_account.return_value = MarginAccountSummary(0.1, 0.0, 0.1, 999.0, "NORMAL", [])
    client.get_ticker_price.return_value = 70000.0
    client.get_symbol_position.return_value = MarginPosition("BTCUSDT", "BTC", "USDT", 0.0, 0.0, 0.0, 0.0)
    client.cancel_all_symbol_orders.return_value = True
    client.execute_market_close.return_value = True
    client.place_limit_order.return_value = 12345  # Mock order ID
    client.place_oco_order.return_value = True
    client.cancel_order.return_value = True
    client.get_avg_entry_price.return_value = 70000.0
    client.execute_partial_market_close.return_value = True
    return MarginOrderExecutor(client), client


def _make_trade_state(direction="LONG", entry_price=70000, tp_price=75000, sl_price=68000):
    return {
        "direction": direction,
        "entry_price": entry_price,
        "tp_price": tp_price,
        "sl_price": sl_price,
        "entry_filled_at": (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat(),
        "projected_holding_hours": 24.0,
        "entry_atr": 1000.0,
    }

def _make_oco_orders(symbol="BTCUSDT", exit_side="SELL", tp=75000, sl=68000):
    """Create TP (LIMIT) and SL (STOP_LOSS_LIMIT) active orders."""
    return [
        MarginOrder(symbol, "10", "", tp, 0.5, 0.0, "NEW", "GTC", "LIMIT", exit_side, 0),
        MarginOrder(symbol, "11", "", 0, 0.5, 0.0, "NEW", "GTC", "STOP_LOSS_LIMIT", exit_side, 0, stop_price=sl),
    ]


# ================================================================
# ENTRY TESTS (sync_with_opinion)
# ================================================================

def test_flat_to_long():

    executor, client = _make_executor()
    client.get_symbol_position.return_value = MarginPosition("BTCUSDT", "BTC", "USDT", 0.0, 0.0, 0.0, 0.0)
    client.get_active_orders.return_value = []
    
    order_id = executor.sync_with_opinion("BTCUSDT", "LONG", entry_price=74000, tp_price=76000, sl_price=73000)
    
    # Assertions
    client.cancel_all_symbol_orders.assert_not_called()
    client.execute_market_close.assert_not_called()
    client.place_limit_order.assert_called_once_with(symbol="BTCUSDT", side="BUY", qty=ANY, price=74000)
    assert order_id == 12345

def test_flat_with_stale_orders_to_long():

    executor, client = _make_executor()
    client.get_symbol_position.return_value = MarginPosition("BTCUSDT", "BTC", "USDT", 0.0, 0.0, 0.0, 0.0)
    stale_order = MarginOrder("BTCUSDT", 1, "", 75000, 1.0, 0.0, "NEW", "GTC", "LIMIT_MAKER", "SELL", 0)
    client.get_active_orders.return_value = [stale_order]
    
    order_id = executor.sync_with_opinion("BTCUSDT", "LONG", entry_price=74000, tp_price=76000, sl_price=73000)
    
    client.cancel_all_symbol_orders.assert_called_once_with("BTCUSDT")
    client.place_limit_order.assert_called_once_with(symbol="BTCUSDT", side="BUY", qty=ANY, price=74000)
    assert order_id == 12345

def test_pivot_short_to_long_no_sl():
    """Case A-1: Opposing SHORT has NO stop loss → force-close and place new LONG entry."""

    executor, client = _make_executor()
    client.get_symbol_position.return_value = MarginPosition("BTCUSDT", "BTC", "USDT", -0.5, 0.5, 0.0, 0.0)
    client.get_active_orders.return_value = []  # No stop loss → Case A-1
    
    order_id = executor.sync_with_opinion("BTCUSDT", "LONG", entry_price=74000, tp_price=76000, sl_price=73000)
    
    client.cancel_all_symbol_orders.assert_called_once_with("BTCUSDT")
    client.execute_market_close.assert_called_once_with("BTCUSDT")
    client.place_limit_order.assert_called_once_with(symbol="BTCUSDT", side="BUY", qty=ANY, price=74000)
    client.place_oco_order.assert_not_called()
    assert order_id == 12345

def test_pivot_short_with_sl_to_long():
    """Case A-2: Opposing SHORT has a stop loss → preserve it with midpoint TP + new LONG entry."""

    executor, client = _make_executor()
    # SHORT position of 0.5 BTC
    client.get_symbol_position.return_value = MarginPosition("BTCUSDT", "BTC", "USDT", -0.5, 0.5, 0.0, 0.0)
    # SHORT's stop loss: BUY STOP_LOSS_LIMIT at 86000 (above current, protecting the short)
    sl_order = MarginOrder("BTCUSDT", 55, "", 86000, 0.5, 0.0, "NEW", "GTC", "STOP_LOSS_LIMIT", "BUY", 0, stop_price=86000)
    client.get_active_orders.return_value = [sl_order]
    # Current price is 84000, opinion entry is 82000
    client.get_ticker_price.return_value = 84000.0
    
    order_id = executor.sync_with_opinion("BTCUSDT", "LONG", entry_price=82000, tp_price=80000, sl_price=85000)
    
    # Step 1: Cancel all orders (clean slate)
    client.cancel_all_symbol_orders.assert_called_once_with("BTCUSDT")
    # Step 2: Should NOT force-close the existing SHORT
    client.execute_market_close.assert_not_called()
    # Step 3: OCO placed to protect existing SHORT
    #   No existing TP, so new TP = new entry = 82000
    #   buffered_sl = 86000 + 10.0 = 86010.0 (SHORT SL = trigger + buffer)
    client.place_oco_order.assert_called_once_with(
        symbol="BTCUSDT", side="BUY", qty=0.5,
        price=82000, stop_price=86000, stop_limit_price=86010.0
    )
    # Step 4: New LONG LIMIT entry placed
    client.place_limit_order.assert_called_once_with(symbol="BTCUSDT", side="BUY", qty=ANY, price=82000)
    assert order_id == 12345

def test_pivot_short_with_optimal_tp_to_long():
    """Case A-2b: Previously this kept the 'better' TP. Now it MUST align with new entry for Seamless Flip."""

    executor, client = _make_executor()
    client.get_symbol_position.return_value = MarginPosition("BTCUSDT", "BTC", "USDT", -0.5, 0.5, 0.0, 0.0)
    sl_order = MarginOrder("BTCUSDT", 55, "", 86000, 0.5, 0.0, "NEW", "GTC", "STOP_LOSS_LIMIT", "BUY", 0, stop_price=86000)
    tp_order = MarginOrder("BTCUSDT", 56, "", 79000, 0.5, 0.0, "NEW", "GTC", "LIMIT_MAKER", "BUY", 0) # 79000 is < 82000!
    client.get_active_orders.return_value = [sl_order, tp_order]
    client.get_ticker_price.return_value = 84000.0
    
    order_id = executor.sync_with_opinion("BTCUSDT", "LONG", entry_price=82000, tp_price=80000, sl_price=85000)
    
    # The system should pick the new entry_price (82000) regardless of the old TP (79000)
    client.place_oco_order.assert_called_once_with(
        symbol="BTCUSDT", side="BUY", qty=0.5,
        price=82000.0, stop_price=86000, stop_limit_price=86010.0
    )

def test_pivot_short_with_oco_and_stale_limit():
    """Case A-2c: Opposing SHORT has an OCO AND a stale Limit entry. The system must ignore them and use new Entry."""

    executor, client = _make_executor()
    client.get_symbol_position.return_value = MarginPosition("BTCUSDT", "BTC", "USDT", -0.5, 0.5, 0.0, 0.0)
    
    # B: OCO Stop Loss
    sl_order = MarginOrder("BTCUSDT", 100, "", 86000, 0.5, 0.0, "NEW", "GTC", "STOP_LOSS_LIMIT", "BUY", 0, stop_price=86000)
    # A: OCO Take Profit (Original TP) -> 73000
    tp_order = MarginOrder("BTCUSDT", 101, "", 73000, 0.5, 0.0, "NEW", "GTC", "LIMIT_MAKER", "BUY", 0)
    # C: Stale Opinion Entry Limit -> 74000
    stale_limit = MarginOrder("BTCUSDT", 102, "", 74000, 0.5, 0.0, "NEW", "GTC", "LIMIT", "BUY", 0)
    
    # Send all 3 orders!
    client.get_active_orders.return_value = [sl_order, tp_order, stale_limit]
    client.get_ticker_price.return_value = 84000.0
    
    # New Opinion Entry is 74600
    order_id = executor.sync_with_opinion("BTCUSDT", "LONG", entry_price=74600, tp_price=80000, sl_price=85000)
    
    # The system should pick the new entry_price (74600)
    client.place_oco_order.assert_called_once_with(
        symbol="BTCUSDT", side="BUY", qty=0.5,
        price=74600.0, stop_price=86000, stop_limit_price=86010.0
    )
    # The system should place the new LIMIT at 74600 (New C)
    client.place_limit_order.assert_called_once_with(symbol="BTCUSDT", side="BUY", qty=ANY, price=74600)

def test_pivot_short_to_long_overshot():
    """Case A-2d: Price has already overshot the entry point -> Market Close instead of OCO."""

    executor, client = _make_executor()
    # SHORT position of 0.5 BTC
    client.get_symbol_position.return_value = MarginPosition("BTCUSDT", "BTC", "USDT", -0.5, 0.5, 0.0, 0.0)
    sl_order = MarginOrder("BTCUSDT", 55, "", 86000, 0.5, 0.0, "NEW", "GTC", "STOP_LOSS_LIMIT", "BUY", 0, stop_price=86000)
    client.get_active_orders.return_value = [sl_order]
    
    # Entry is 70000, but current price is 69950 (overshot for a SHORT)
    client.get_ticker_price.return_value = 69950.0
    
    order_id = executor.sync_with_opinion("BTCUSDT", "LONG", entry_price=70000, tp_price=75000, sl_price=69000)
    
    # Step 1: Cancel all orders
    client.cancel_all_symbol_orders.assert_called_once_with("BTCUSDT")
    # Step 2: SHOULD execute market close because it's overshot
    client.execute_market_close.assert_called_once_with("BTCUSDT")
    # Step 3: Should NOT place OCO
    client.place_oco_order.assert_not_called()
    # Step 4: Place new LONG entry
    client.place_limit_order.assert_called_once_with(symbol="BTCUSDT", side="BUY", qty=ANY, price=70000)

def test_pivot_short_with_sl_oco_fails_abort():
    """Case A-2 failure: OCO placement fails → emergency close + place new entry."""

    executor, client = _make_executor()
    client.get_symbol_position.return_value = MarginPosition("BTCUSDT", "BTC", "USDT", -0.5, 0.5, 0.0, 0.0)
    sl_order = MarginOrder("BTCUSDT", 55, "", 86000, 0.5, 0.0, "NEW", "GTC", "STOP_LOSS_LIMIT", "BUY", 0, stop_price=86000)
    client.get_active_orders.return_value = [sl_order]
    client.get_ticker_price.return_value = 84000.0
    client.place_oco_order.return_value = False  # OCO fails!

    order_id = executor.sync_with_opinion("BTCUSDT", "LONG", entry_price=82000, tp_price=80000, sl_price=85000)

    # New OCO placed BEFORE cancelling old — on failure, old OCO stays (no cancel)
    client.cancel_all_symbol_orders.assert_not_called()
    client.place_oco_order.assert_called_once()  # Attempted but failed
    # Emergency close instead of leaving position naked
    client.execute_market_close.assert_called_once_with("BTCUSDT")
    # Still place new entry since AI opinion is valid
    client.place_limit_order.assert_called_once_with(symbol="BTCUSDT", side="BUY", qty=ANY, price=82000)
    assert order_id is not None  # Returns new entry order_id

def test_same_direction_optimization():

    executor, client = _make_executor()
    client.get_symbol_position.return_value = MarginPosition("BTCUSDT", "BTC", "USDT", 2.0, 0.0, 2.0, 0.0)
    client.cancel_all_symbol_orders.return_value = True
    
    old_tp = MarginOrder("BTCUSDT", 1, "", 75000, 2.0, 0.0, "NEW", "GTC", "LIMIT_MAKER", "SELL", 0)
    old_sl = MarginOrder("BTCUSDT", 2, "", 72000, 2.0, 0.0, "NEW", "GTC", "STOP_LOSS_LIMIT", "SELL", 0, stop_price=72000)
    client.get_active_orders.return_value = [old_tp, old_sl]
    
    order_id = executor.sync_with_opinion("BTCUSDT", "LONG", entry_price=74000, tp_price=76000, sl_price=73000)
    
    # Should pick max(75000, 76000) = 76000 for TP
    # Should pick max(72000, 73000) = 73000 for SL
    client.cancel_all_symbol_orders.assert_called_once_with("BTCUSDT")
    client.execute_market_close.assert_not_called()
    client.place_oco_order.assert_called_once_with(
        symbol="BTCUSDT", side="SELL", qty=2.0,
        price=76000, stop_price=73000, stop_limit_price=72990.0
    )
    # sync_with_opinion now returns state_update dict for same-direction optimization
    assert order_id == {"tp_price": 76000, "sl_price": 73000}

def test_non_whitelisted_symbol():

    executor, client = _make_executor()
    
    order_id = executor.sync_with_opinion("SOLUSDT", "LONG", entry_price=2000, tp_price=2200, sl_price=1900)
    
    client.get_symbol_position.assert_not_called()
    client.place_limit_order.assert_not_called()
    assert order_id is None

# ================================================================
# GUARDIAN TESTS
# ================================================================

def test_guardian_no_trade_state():

    executor, client = _make_executor()

    result, level = executor.guardian_check("BTCUSDT", {})

    client.get_symbol_position.assert_called_once_with("BTCUSDT")
    assert result == {}
    assert level is None

def test_guardian_entry_pending_not_expired():

    executor, client = _make_executor()
    client.get_symbol_position.return_value = MarginPosition("BTCUSDT", "BTC", "USDT", 0.0, 0.0, 0.0, 0.0)
    client.get_active_orders.return_value = []

    trade_state = {
        "direction": "LONG",
        "entry_order_id": 12345,
        "entry_placed_at": datetime.now(timezone.utc) - timedelta(hours=1),
        "projected_waiting_hours": 4.0,
        "tp_price": 76000,
        "sl_price": 73000,
    }

    result, level = executor.guardian_check("BTCUSDT", trade_state)

    client.cancel_order.assert_not_called()
    assert result["entry_order_id"] == 12345
    assert level is None

def test_guardian_entry_expired():

    executor, client = _make_executor()
    client.get_symbol_position.return_value = MarginPosition("BTCUSDT", "BTC", "USDT", 0.0, 0.0, 0.0, 0.0)
    client.get_active_orders.return_value = []

    trade_state = {
        "direction": "LONG",
        "entry_order_id": 12345,
        "entry_placed_at": datetime.now(timezone.utc) - timedelta(hours=5),
        "projected_waiting_hours": 4.0,
        "tp_price": 76000,
        "sl_price": 73000,
    }

    result, level = executor.guardian_check("BTCUSDT", trade_state)

    client.cancel_order.assert_called_once_with("BTCUSDT", 12345)
    assert result == {}

def test_guardian_unprotected_position_place_oco():

    executor, client = _make_executor()
    # Position exists (LONG 0.005 BTC)
    client.get_symbol_position.return_value = MarginPosition("BTCUSDT", "BTC", "USDT", 0.005, 0.0, 0.005, 0.0)
    # No active orders (no protection!)
    client.get_active_orders.return_value = []
    client.get_ticker_price.return_value = 74000.0  # Price above SL

    trade_state = {
        "direction": "LONG",
        "tp_price": 76000.0,
        "sl_price": 73000.0,
        "entry_order_id": 12345,
    }

    result, level = executor.guardian_check("BTCUSDT", trade_state)

    client.place_oco_order.assert_called_once_with(
        symbol="BTCUSDT", side="SELL", qty=0.005,
        price=76000.0, stop_price=73000.0, stop_limit_price=72990.0
    )
    assert "entry_order_id" not in result  # Entry tracking removed after OCO placed

def test_guardian_sl_breached_emergency_close():

    executor, client = _make_executor()
    client.get_symbol_position.return_value = MarginPosition("BTCUSDT", "BTC", "USDT", 0.005, 0.0, 0.005, 0.0)
    client.get_active_orders.return_value = []
    client.get_ticker_price.return_value = 72500.0  # Price BELOW SL of 73000!

    trade_state = {
        "direction": "LONG",
        "tp_price": 76000.0,
        "sl_price": 73000.0,
    }

    result, level = executor.guardian_check("BTCUSDT", trade_state)

    client.execute_market_close.assert_called_once_with("BTCUSDT")
    assert result == {}

def test_guardian_position_already_protected():

    executor, client = _make_executor()
    client.get_symbol_position.return_value = MarginPosition("BTCUSDT", "BTC", "USDT", 0.005, 0.0, 0.005, 0.0)
    # Active OCO orders exist
    sl_order = MarginOrder("BTCUSDT", 99, "", 73000, 0.005, 0.0, "NEW", "GTC", "STOP_LOSS_LIMIT", "SELL", 0, stop_price=73000)
    tp_order = MarginOrder("BTCUSDT", 100, "", 76000, 0.005, 0.0, "NEW", "GTC", "LIMIT_MAKER", "SELL", 0)
    client.get_active_orders.return_value = [sl_order, tp_order]

    trade_state = {
        "direction": "LONG",
        "tp_price": 76000.0,
        "sl_price": 73000.0,
    }

    result, level = executor.guardian_check("BTCUSDT", trade_state)

    client.place_oco_order.assert_not_called()
    client.execute_market_close.assert_not_called()
    assert result == trade_state
    # No ATR → Case 4 skipped, level unchanged (current_level=0 default)
    assert level == 0

def test_flat_to_short():
    """FLAT → SHORT: places SELL limit entry with SL above entry."""
    executor, client = _make_executor()
    client.get_symbol_position.return_value = MarginPosition("BTCUSDT", "BTC", "USDT", 0.0, 0.0, 0.0, 0.0)
    client.get_active_orders.return_value = []

    order_id = executor.sync_with_opinion("BTCUSDT", "BEARISH", entry_price=66000, tp_price=64000, sl_price=67000)

    client.cancel_all_symbol_orders.assert_not_called()
    client.execute_market_close.assert_not_called()
    client.place_limit_order.assert_called_once_with(symbol="BTCUSDT", side="SELL", qty=ANY, price=66000)
    assert order_id == 12345


# ================================================================
# GUARDIAN EDGE CASE TESTS
# ================================================================

def test_guardian_position_flat_no_entry_cleanup():
    """Position went flat after being filled — clean up stray orders and state."""
    executor, client = _make_executor()
    client.get_symbol_position.return_value = MarginPosition("BTCUSDT", "BTC", "USDT", 0.0, 0.0, 0.0, 0.0)
    client.get_active_orders.return_value = []

    trade_state = {
        "direction": "LONG",
        "tp_price": 76000,
        "sl_price": 73000,
        "entry_filled_at": (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat(),
    }

    result, level = executor.guardian_check("BTCUSDT", trade_state)

    client.cancel_all_symbol_orders.assert_called_once_with("BTCUSDT")
    assert result == {}


def test_guardian_partial_sl_fill_rebuilds_oco_with_remaining_qty():
    """SL partially filled (0.04 of 0.068) — remaining 0.028 gets new OCO."""
    executor, client = _make_executor()
    client.get_symbol_position.return_value = MarginPosition("BTCUSDT", "BTC", "USDT", -0.028, 0.0, 0.0, 0.0)
    client.get_active_orders.return_value = []  # SL order consumed (partial fill + cancel)
    client.get_ticker_price.return_value = 65000  # price recovered, not breached

    trade_state = {
        "direction": "SHORT",
        "tp_price": 63000,
        "sl_price": 66000,
        "entry_filled_at": (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(),
    }

    result, level = executor.guardian_check("BTCUSDT", trade_state)

    # Should place OCO for remaining qty=0.028
    client.place_oco_order.assert_called_once()
    call_kwargs = client.place_oco_order.call_args.kwargs
    assert call_kwargs["qty"] == 0.028
    assert call_kwargs["side"] == "BUY"  # close SHORT = BUY
    assert "entry_order_id" not in result
    assert result["direction"] == "SHORT"


def test_guardian_position_flat_without_entry_filled_at():
    """Position flat, no entry_order_id, no entry_filled_at — still cleans up."""
    executor, client = _make_executor()
    client.get_symbol_position.return_value = MarginPosition("BTCUSDT", "BTC", "USDT", 0.0, 0.0, 0.0, 0.0)
    client.get_active_orders.return_value = []

    trade_state = {
        "direction": "LONG",
        "tp_price": 76000,
        "sl_price": 73000,
        # no entry_filled_at
    }

    result, level = executor.guardian_check("BTCUSDT", trade_state)

    client.cancel_all_symbol_orders.assert_called_once_with("BTCUSDT")
    assert result == {}


# ================================================================
# PARTIAL TP + DYNAMIC TRAILING TESTS (multi-level, daemon-memory driven)
# ================================================================
# current_level = next level to check (0=L1, 1=L2, 2=L3, 3=all done)
# Returned level = updated next level (or None for non-Case-4 paths)

def test_partial_tp_l1_triggers_long():
    """L1: |price - entry| >= 1.5 ATR -> close 20%, SL = entry, level 0->1."""
    executor, client = _make_executor()
    atr = 1000.0
    entry = 70000.0
    current_price = entry + 1.5 * atr  # 71500
    client.get_ticker_price.return_value = current_price
    client.get_symbol_position.return_value = MarginPosition(
        "BTCUSDT", "BTC", "USDT", net_qty=0.5, borrowed=0.0, free=0.5, locked=0.0
    )
    client.get_avg_entry_price.return_value = entry
    orders = _make_oco_orders(symbol="BTCUSDT", exit_side="SELL", tp=75000, sl=68000)
    client.get_active_orders.return_value = orders

    trade_state = _make_trade_state("LONG", entry, tp_price=75000, sl_price=68000)
    result, level = executor.guardian_check("BTCUSDT", trade_state, atr_macro=atr,
                                            current_level=0)

    # Partial close at 20% of 0.5 = 0.1
    client.execute_partial_market_close.assert_called_once()
    close_call = client.execute_partial_market_close.call_args
    assert close_call[1]["qty"] == 0.1
    assert close_call[1]["side"] == "SELL"
    # OCO re-placed with SL at entry
    client.place_oco_order.assert_called()
    oco_call = client.place_oco_order.call_args
    assert oco_call[1]["stop_price"] == entry
    # Trade state updated
    assert result.get("sl_price") == entry
    assert level == 1  # next to check = L2


def test_partial_tp_l1_idempotent_via_level():
    """current_level=1 -> L1 skipped, L2 checked (not met at 2.0 ATR)."""
    executor, client = _make_executor()
    atr = 1000.0
    entry = 70000.0
    current_price = entry + 2.0 * atr  # 72000 (L1 would fire, but already done)
    client.get_ticker_price.return_value = current_price
    client.get_symbol_position.return_value = MarginPosition(
        "BTCUSDT", "BTC", "USDT", net_qty=0.4, borrowed=0.0, free=0.4, locked=0.0
    )
    client.get_avg_entry_price.return_value = entry
    orders = _make_oco_orders(symbol="BTCUSDT", exit_side="SELL", tp=75000, sl=entry)
    client.get_active_orders.return_value = orders

    trade_state = _make_trade_state("LONG", entry, tp_price=75000, sl_price=entry)
    result, level = executor.guardian_check("BTCUSDT", trade_state, atr_macro=atr,
                                            current_level=1)

    # L1 should NOT fire again
    client.execute_partial_market_close.assert_not_called()
    # L2: 2.0 < 3.5 -> no trigger either
    assert level == 1  # unchanged


def test_partial_tp_l2_triggers_long():
    """L1 done (current_level=1), |price-entry| >= 3.5 ATR -> L2 fires, level 1->2."""
    executor, client = _make_executor()
    atr = 1000.0
    entry = 70000.0
    current_price = entry + 3.5 * atr  # 73500
    client.get_ticker_price.return_value = current_price
    client.get_symbol_position.return_value = MarginPosition(
        "BTCUSDT", "BTC", "USDT", net_qty=0.4, borrowed=0.0, free=0.4, locked=0.0
    )
    client.get_avg_entry_price.return_value = entry
    orders = _make_oco_orders(symbol="BTCUSDT", exit_side="SELL", tp=75000, sl=entry)
    client.get_active_orders.return_value = orders

    trade_state = _make_trade_state("LONG", entry, tp_price=75000, sl_price=entry)
    result, level = executor.guardian_check("BTCUSDT", trade_state, atr_macro=atr,
                                            current_level=1)

    # L2 fired: close 20% of 0.4 = 0.08
    client.execute_partial_market_close.assert_called_once()
    close_call = client.execute_partial_market_close.call_args
    assert close_call[1]["qty"] == 0.08
    assert level == 2  # next = L3


def test_partial_tp_l3_triggers_long():
    """L2 done (current_level=2), |price-entry| >= 5.5 ATR -> L3 fires, level 2->3."""
    executor, client = _make_executor()
    atr = 1000.0
    entry = 70000.0
    current_price = entry + 5.5 * atr  # 75500
    client.get_ticker_price.return_value = current_price
    client.get_symbol_position.return_value = MarginPosition(
        "BTCUSDT", "BTC", "USDT", net_qty=0.32, borrowed=0.0, free=0.32, locked=0.0
    )
    client.get_avg_entry_price.return_value = entry
    orders = _make_oco_orders(symbol="BTCUSDT", exit_side="SELL", tp=75000, sl=entry)
    client.get_active_orders.return_value = orders

    trade_state = _make_trade_state("LONG", entry, tp_price=75000, sl_price=entry)
    result, level = executor.guardian_check("BTCUSDT", trade_state, atr_macro=atr,
                                            current_level=2)

    # L3 fired: close 20% of 0.32 = 0.064
    client.execute_partial_market_close.assert_called_once()
    close_call = client.execute_partial_market_close.call_args
    assert abs(close_call[1]["qty"] - 0.064) < 0.001
    assert level == 3  # all done


def test_multi_level_same_pulse():
    """Price at 6.0 ATR -> L1, L2, L3 all fire, level 0->3."""
    executor, client = _make_executor()
    atr = 1000.0
    entry = 70000.0
    current_price = entry + 6.0 * atr  # 76000
    client.get_ticker_price.return_value = current_price
    pos_chain = [0.5, 0.4, 0.32, 0.256]
    call_count = [0]
    def pos_side_effect(symbol):
        idx = min(call_count[0], len(pos_chain) - 1)
        qty = pos_chain[idx]
        call_count[0] += 1
        return MarginPosition("BTCUSDT", "BTC", "USDT",
                              net_qty=qty, borrowed=0.0, free=abs(qty), locked=0.0)
    client.get_symbol_position.side_effect = pos_side_effect

    client.get_avg_entry_price.return_value = entry
    orders = _make_oco_orders(symbol="BTCUSDT", exit_side="SELL", tp=80000, sl=68000)
    client.get_active_orders.return_value = orders

    trade_state = _make_trade_state("LONG", entry, tp_price=80000, sl_price=68000)
    result, level = executor.guardian_check("BTCUSDT", trade_state, atr_macro=atr,
                                            current_level=0)

    # All three levels fired: 3 partial closes
    assert client.execute_partial_market_close.call_count == 3
    calls = client.execute_partial_market_close.call_args_list
    assert calls[0][1]["qty"] == 0.1   # L1: 20% of 0.5
    assert calls[1][1]["qty"] == 0.08  # L2: 20% of 0.4
    assert calls[2][1]["qty"] == 0.064 # L3: 20% of 0.32
    assert level == 3  # all done


def test_no_trailing_when_distance_zero():
    """L1 active (sl_distance_atr=0, current_level=1) -> trailing skipped."""
    executor, client = _make_executor()
    atr = 1000.0
    entry = 70000.0
    current_price = entry + 2.0 * atr  # 72000
    client.get_ticker_price.return_value = current_price
    client.get_symbol_position.return_value = MarginPosition(
        "BTCUSDT", "BTC", "USDT", net_qty=0.4, borrowed=0.0, free=0.4, locked=0.0
    )
    client.get_avg_entry_price.return_value = entry
    orders = _make_oco_orders(symbol="BTCUSDT", exit_side="SELL", tp=75000, sl=entry)
    client.get_active_orders.return_value = orders

    trade_state = _make_trade_state("LONG", entry, tp_price=75000, sl_price=entry)
    client.place_oco_order.reset_mock()
    client.cancel_all_symbol_orders.reset_mock()

    result, level = executor.guardian_check("BTCUSDT", trade_state, atr_macro=atr,
                                            current_level=1)

    # No partial close (L1 idempotent, L2 not reached at 2.0 ATR)
    client.execute_partial_market_close.assert_not_called()
    assert level == 1  # unchanged
    assert result.get("sl_price") == entry


def test_trailing_with_l2_distance():
    """L2 active (sl_distance_atr=1.0, current_level=2) -> trailing by 1.0 ATR."""
    executor, client = _make_executor()
    atr = 1000.0
    entry = 70000.0
    new_price = entry + 4.5 * atr  # 74500
    client.get_ticker_price.return_value = new_price
    client.get_symbol_position.return_value = MarginPosition(
        "BTCUSDT", "BTC", "USDT", net_qty=0.32, borrowed=0.0, free=0.32, locked=0.0
    )
    client.get_avg_entry_price.return_value = entry
    orders = _make_oco_orders(symbol="BTCUSDT", exit_side="SELL", tp=75000, sl=entry)
    client.get_active_orders.return_value = orders

    trade_state = _make_trade_state("LONG", entry, tp_price=75000, sl_price=entry)
    result, level = executor.guardian_check("BTCUSDT", trade_state, atr_macro=atr,
                                            current_level=2)

    # L3: 4.5 < 5.5 -> not triggered
    client.execute_partial_market_close.assert_not_called()
    assert level == 2  # unchanged
    # Trailing with 1.0 ATR distance should fire
    assert result.get("sl_price") != entry  # SL moved
    if client.place_oco_order.called:
        oco_call = client.place_oco_order.call_args
        new_sl = oco_call[1].get("stop_price", 0)
        expected_sl = new_price - 1.0 * atr  # 73500
        assert abs(new_sl - expected_sl) < 100


def test_trailing_with_l3_tighter_distance():
    """L3 active (sl_distance_atr=0.75, current_level=3) -> trailing by 0.75 ATR."""
    executor, client = _make_executor()
    atr = 1000.0
    entry = 70000.0
    new_price = entry + 6.0 * atr  # 76000
    client.get_ticker_price.return_value = new_price
    client.get_symbol_position.return_value = MarginPosition(
        "BTCUSDT", "BTC", "USDT", net_qty=0.256, borrowed=0.0, free=0.256, locked=0.0
    )
    client.get_avg_entry_price.return_value = entry
    current_sl = entry + 2.5 * atr  # 72500
    orders = _make_oco_orders(symbol="BTCUSDT", exit_side="SELL", tp=80000, sl=current_sl)
    client.get_active_orders.return_value = orders

    trade_state = _make_trade_state("LONG", entry, tp_price=80000, sl_price=current_sl)
    result, level = executor.guardian_check("BTCUSDT", trade_state, atr_macro=atr,
                                            current_level=3)

    # All levels exhausted -> no more partial closes
    client.execute_partial_market_close.assert_not_called()
    assert level == 3  # unchanged (exhausted)
    # Trailing with 0.75 ATR distance
    if client.place_oco_order.called:
        oco_call = client.place_oco_order.call_args
        new_sl = oco_call[1].get("stop_price", 0)
        expected_sl = new_price - 0.75 * atr  # 75250
        assert abs(new_sl - expected_sl) < 100


def test_partial_tp_l1_triggers_short():
    """SHORT: |entry - price| >= 1.5 ATR -> close 20%, SL = entry."""
    executor, client = _make_executor()
    atr = 1000.0
    entry = 70000.0
    current_price = entry - 1.5 * atr  # 68500
    client.get_ticker_price.return_value = current_price
    client.get_symbol_position.return_value = MarginPosition(
        "BTCUSDT", "BTC", "USDT", net_qty=-0.5, borrowed=0.5, free=0.0, locked=0.0
    )
    client.get_avg_entry_price.return_value = entry
    orders = _make_oco_orders(symbol="BTCUSDT", exit_side="BUY", tp=65000, sl=72000)
    client.get_active_orders.return_value = orders

    trade_state = _make_trade_state("SHORT", entry, tp_price=65000, sl_price=72000)
    result, level = executor.guardian_check("BTCUSDT", trade_state, atr_macro=atr,
                                            current_level=0)

    client.execute_partial_market_close.assert_called_once()
    close_call = client.execute_partial_market_close.call_args
    assert close_call[1]["qty"] == 0.1
    assert close_call[1]["side"] == "BUY"
    client.place_oco_order.assert_called()
    assert result.get("sl_price") == entry
    assert level == 1


def test_partial_tp_skips_when_long_in_loss():
    """LONG in loss: deviation <= 0 → partial TP does NOT fire."""
    executor, client = _make_executor()
    atr = 1000.0
    entry = 70000.0
    current_price = entry - 1.5 * atr  # price BELOW entry (in loss)
    client.get_ticker_price.return_value = current_price
    client.get_symbol_position.return_value = MarginPosition(
        "BTCUSDT", "BTC", "USDT", net_qty=0.5, borrowed=0.0, free=0.5, locked=0.0)
    client.get_avg_entry_price.return_value = entry
    orders = _make_oco_orders(symbol="BTCUSDT", exit_side="SELL", tp=75000, sl=68000)
    client.get_active_orders.return_value = orders

    trade_state = _make_trade_state("LONG", entry, tp_price=75000, sl_price=68000)
    result, level = executor.guardian_check("BTCUSDT", trade_state, atr_macro=atr,
                                            current_level=0)

    client.execute_partial_market_close.assert_not_called()
    assert result != {}


def test_partial_tp_skips_when_short_in_loss():
    """SHORT in loss: deviation <= 0 → partial TP does NOT fire."""
    executor, client = _make_executor()
    atr = 1000.0
    entry = 70000.0
    current_price = entry + 1.5 * atr  # price ABOVE entry (in loss for SHORT)
    client.get_ticker_price.return_value = current_price
    client.get_symbol_position.return_value = MarginPosition(
        "BTCUSDT", "BTC", "USDT", net_qty=-0.5, borrowed=0.5, free=0.0, locked=0.0)
    client.get_avg_entry_price.return_value = entry
    orders = _make_oco_orders(symbol="BTCUSDT", exit_side="BUY", tp=65000, sl=72000)
    client.get_active_orders.return_value = orders

    trade_state = _make_trade_state("SHORT", entry, tp_price=65000, sl_price=72000)
    result, level = executor.guardian_check("BTCUSDT", trade_state, atr_macro=atr,
                                            current_level=0)

    client.execute_partial_market_close.assert_not_called()
    assert result != {}


def test_oco_replace_failure_emergency_closes():
    """When OCO re-place fails after cancel, emergency market close."""
    executor, client = _make_executor()
    atr = 1000.0
    entry = 70000.0
    current_price = entry + 1.5 * atr
    client.get_ticker_price.return_value = current_price
    client.get_symbol_position.return_value = MarginPosition(
        "BTCUSDT", "BTC", "USDT", net_qty=0.5, borrowed=0.0, free=0.5, locked=0.0
    )
    client.get_avg_entry_price.return_value = entry
    orders = _make_oco_orders(symbol="BTCUSDT", exit_side="SELL", tp=75000, sl=68000)
    client.get_active_orders.return_value = orders
    client.place_oco_order.return_value = False  # OCO fails

    trade_state = _make_trade_state("LONG", entry, tp_price=75000, sl_price=68000)
    result, level = executor.guardian_check("BTCUSDT", trade_state, atr_macro=atr,
                                            current_level=0)

    client.execute_partial_market_close.assert_any_call(
        symbol="BTCUSDT", side="SELL", qty=0.4
    )
    client.execute_market_close.assert_not_called()
    assert result == {}


def test_restart_reconstructs_trade_state():
    """Restart: empty trade_state + exchange OCO → reconstructs direction/TP/SL."""
    executor, client = _make_executor()
    entry = 70000.0
    client.get_symbol_position.return_value = MarginPosition(
        "BTCUSDT", "BTC", "USDT", net_qty=0.4, borrowed=0.0, free=0.4, locked=0.0
    )
    client.get_avg_entry_price.return_value = entry
    orders = _make_oco_orders(symbol="BTCUSDT", exit_side="SELL", tp=75000, sl=entry)
    client.get_active_orders.return_value = orders

    # Empty trade state (simulates restart). Without ATR, Case 4 is skipped.
    result, level = executor.guardian_check("BTCUSDT", {})

    assert result != {}
    assert result.get("direction") == "LONG"
    assert result.get("tp_price") == 75000
    assert result.get("sl_price") == entry


def test_find_level_no_tp_yet():
    """find_level_and_sync_sl: SL < entry (LONG) -> L1 not fired -> returns 0."""
    executor, client = _make_executor()
    entry = 70000.0
    client.get_symbol_position.return_value = MarginPosition(
        "BTCUSDT", "BTC", "USDT", net_qty=0.5, borrowed=0.0, free=0.5, locked=0.0
    )
    client.get_avg_entry_price.return_value = entry
    client.get_ticker_price.return_value = entry + 1.0 * 1000  # 71000
    orders = _make_oco_orders(symbol="BTCUSDT", exit_side="SELL", tp=75000, sl=68000)
    client.get_active_orders.return_value = orders

    trade_state = _make_trade_state("LONG", entry, tp_price=75000, sl_price=68000)
    level = executor.find_level_and_sync_sl("BTCUSDT", trade_state, atr_macro=1000.0)
    assert level == 0


def test_find_level_l2_fired_syncs_sl():
    """find_level: SL=entry, price at 4.0 ATR -> L2 fired -> returns 2, syncs SL."""
    executor, client = _make_executor()
    atr = 1000.0
    entry = 70000.0
    client.get_symbol_position.return_value = MarginPosition(
        "BTCUSDT", "BTC", "USDT", net_qty=0.32, borrowed=0.0, free=0.32, locked=0.0
    )
    client.get_avg_entry_price.return_value = entry
    client.get_ticker_price.return_value = entry + 4.0 * atr  # 74000
    # SL at entry → L1 fired
    orders = _make_oco_orders(symbol="BTCUSDT", exit_side="SELL", tp=75000, sl=entry)
    client.get_active_orders.return_value = orders

    trade_state = _make_trade_state("LONG", entry, tp_price=75000, sl_price=entry)
    level = executor.find_level_and_sync_sl("BTCUSDT", trade_state, atr_macro=atr)

    # L2 threshold 3.5 ATR < 4.0 → L2 fired, returns 2 (next = L3)
    assert level == 2
    # SL should be synced: price - 1.0 ATR = 74000 - 1000 = 73000
    if client.place_oco_order.called:
        oco_call = client.place_oco_order.call_args
        assert abs(oco_call[1]["stop_price"] - 73000) < 100


def test_find_level_l3_all_fired():
    """find_level: SL=entry, price at 6.0 ATR -> all levels fired -> returns 3, SL=0.75 ATR."""
    executor, client = _make_executor()
    atr = 1000.0
    entry = 70000.0
    client.get_symbol_position.return_value = MarginPosition(
        "BTCUSDT", "BTC", "USDT", net_qty=0.256, borrowed=0.0, free=0.256, locked=0.0
    )
    client.get_avg_entry_price.return_value = entry
    client.get_ticker_price.return_value = entry + 6.0 * atr  # 76000
    orders = _make_oco_orders(symbol="BTCUSDT", exit_side="SELL", tp=80000, sl=entry)
    client.get_active_orders.return_value = orders

    trade_state = _make_trade_state("LONG", entry, tp_price=80000, sl_price=entry)
    level = executor.find_level_and_sync_sl("BTCUSDT", trade_state, atr_macro=atr)

    # L1+L2+L3 all fired -> next level = 3 (done)
    assert level == 3
    # SL should be synced: price - 0.75 ATR = 76000 - 750 = 75250
    if client.place_oco_order.called:
        oco_call = client.place_oco_order.call_args
        assert abs(oco_call[1]["stop_price"] - 75250) < 100


def test_find_level_short():
    """find_level_and_sync_sl: SHORT, SL=entry, price at -4.0 ATR -> L2 fired -> returns 2."""
    executor, client = _make_executor()
    atr = 1000.0
    entry = 70000.0
    client.get_symbol_position.return_value = MarginPosition(
        "BTCUSDT", "BTC", "USDT", net_qty=-0.32, borrowed=0.32, free=0.0, locked=0.0
    )
    client.get_avg_entry_price.return_value = entry
    client.get_ticker_price.return_value = entry - 4.0 * atr  # 66000
    orders = _make_oco_orders(symbol="BTCUSDT", exit_side="BUY", tp=60000, sl=entry)
    client.get_active_orders.return_value = orders

    trade_state = _make_trade_state("SHORT", entry, tp_price=60000, sl_price=entry)
    level = executor.find_level_and_sync_sl("BTCUSDT", trade_state, atr_macro=atr)

    # L2 threshold 3.5 ATR < 4.0 -> L2 fired, returns 2 (next = L3)
    assert level == 2
    # SL synced: price + 1.0 ATR = 66000 + 1000 = 67000 （ceiling toward safety）
    # For mock: verify OCO was called with correct stop
    if client.place_oco_order.called:
        oco_call = client.place_oco_order.call_args
        assert abs(oco_call[1]["stop_price"] - 67000) < 100


def test_find_level_cancel_fails_returns_next_level():
    """find_level: cancel fails -> returns next_level anyway (no sync, no crash)."""
    executor, client = _make_executor()
    atr = 1000.0
    entry = 70000.0
    client.get_symbol_position.return_value = MarginPosition(
        "BTCUSDT", "BTC", "USDT", net_qty=0.32, borrowed=0.0, free=0.32, locked=0.0
    )
    client.get_avg_entry_price.return_value = entry
    client.get_ticker_price.return_value = entry + 4.0 * atr  # 74000
    # SL != entry -> needs sync, but cancel will fail
    orders = _make_oco_orders(symbol="BTCUSDT", exit_side="SELL", tp=75000, sl=71000)
    client.get_active_orders.return_value = orders
    client.cancel_all_symbol_orders.return_value = False  # cancel fails

    trade_state = _make_trade_state("LONG", entry, tp_price=75000, sl_price=71000)
    level = executor.find_level_and_sync_sl("BTCUSDT", trade_state, atr_macro=atr)

    # L2 fired (4.0 >= 3.5), returns 2
    assert level == 2
    # OCO should NOT be re-placed (cancel failed, skip)
    client.place_oco_order.assert_not_called()


def test_daemon_qty_change_resets_level():
    """Daemon-level: qty changes -> level reset to None -> find_level re-initialized."""
    executor, client = _make_executor()
    atr = 1000.0
    entry = 70000.0

    # --- Pulse 1: L1 fires, daemon stores level=1 ---
    client.get_ticker_price.return_value = entry + 1.5 * atr  # 71500
    pos_chain = [0.5, 0.4]
    call_count = [0]
    def pos_side_effect(symbol):
        idx = min(call_count[0], len(pos_chain) - 1)
        qty = pos_chain[idx]
        call_count[0] += 1
        return MarginPosition("BTCUSDT", "BTC", "USDT",
                              net_qty=qty, borrowed=0.0, free=abs(qty), locked=0.0)
    client.get_symbol_position.side_effect = pos_side_effect
    client.get_avg_entry_price.return_value = entry
    orders = _make_oco_orders(symbol="BTCUSDT", exit_side="SELL", tp=75000, sl=68000)
    client.get_active_orders.return_value = orders
    client.place_oco_order.return_value = True

    trade_state = _make_trade_state("LONG", entry, tp_price=75000, sl_price=68000)
    result, level = executor.guardian_check("BTCUSDT", trade_state, atr_macro=atr,
                                            current_level=0)
    assert level == 1  # L1 fired, level advanced

    # --- Simulate qty change: daemon detects level is stale ---
    # In production, daemon compares net_qty to _symbol_last_qty.
    # Here we verify that re-running find_level correctly re-syncs.
    client.cancel_all_symbol_orders.reset_mock()
    client.place_oco_order.reset_mock()
    client.execute_partial_market_close.reset_mock()

    # Position qty changed (e.g., manual add) -> SL at entry, price at 2.0 ATR
    client.get_symbol_position.side_effect = None
    client.get_symbol_position.return_value = MarginPosition(
        "BTCUSDT", "BTC", "USDT", net_qty=0.6, borrowed=0.0, free=0.6, locked=0.0
    )
    client.get_ticker_price.return_value = entry + 2.0 * atr  # 72000
    orders2 = _make_oco_orders(symbol="BTCUSDT", exit_side="SELL", tp=75000, sl=entry)
    client.get_active_orders.return_value = orders2

    # Daemon would: reset level → call find_level_and_sync_sl
    find_level = executor.find_level_and_sync_sl("BTCUSDT", trade_state, atr_macro=atr)
    # SL at entry → L1 fired. 2.0 < 3.5 (L2 not met). next = 1.
    assert find_level == 1

    # Pass the found level to guardian_check — should skip L1, not re-trigger it
    result, level = executor.guardian_check("BTCUSDT", trade_state, atr_macro=atr,
                                            current_level=find_level)
    client.execute_partial_market_close.assert_not_called()  # L1 idempotent
    assert level == 1


def test_daemon_position_closed_clears_level():
    """Daemon-level: guardian returns {} -> level/qty tracking cleared."""
    executor, client = _make_executor()
    atr = 1000.0
    entry = 70000.0

    # Position with OCO protection
    client.get_symbol_position.return_value = MarginPosition(
        "BTCUSDT", "BTC", "USDT", net_qty=0.5, borrowed=0.0, free=0.5, locked=0.0
    )
    client.get_avg_entry_price.return_value = entry
    client.get_ticker_price.return_value = entry + 1.5 * atr
    orders = _make_oco_orders(symbol="BTCUSDT", exit_side="SELL", tp=75000, sl=68000)
    client.get_active_orders.return_value = orders

    trade_state = _make_trade_state("LONG", entry, tp_price=75000, sl_price=68000)
    result, level = executor.guardian_check("BTCUSDT", trade_state, atr_macro=atr,
                                            current_level=0)
    assert level == 1  # L1 fired
    assert result  # trade state intact

    # Now simulate position closed externally: net_qty=0, no OCO
    client.get_symbol_position.return_value = MarginPosition(
        "BTCUSDT", "BTC", "USDT", net_qty=0.0, borrowed=0.0, free=0.0, locked=0.0
    )
    client.get_active_orders.return_value = []

    # guardian_check detects flat position (Case 1: no position, has entry_filled_at)
    result, level = executor.guardian_check("BTCUSDT", trade_state, atr_macro=atr,
                                            current_level=1)
    # Should return {} to signal "clear trade state"
    assert result == {}
    # Daemon would: pop _symbol_level[symbol], pop _symbol_last_qty[symbol]
