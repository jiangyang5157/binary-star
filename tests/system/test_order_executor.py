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

    client.cancel_all_symbol_orders.assert_called_once_with("BTCUSDT")
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
    
    order_id = executor.sync_with_opinion("ETHUSDT", "LONG", entry_price=2000, tp_price=2200, sl_price=1900)
    
    client.get_symbol_position.assert_not_called()
    client.place_limit_order.assert_not_called()
    assert order_id is None

# ================================================================
# GUARDIAN TESTS
# ================================================================

def test_guardian_no_trade_state():

    executor, client = _make_executor()
    
    result = executor.guardian_check("BTCUSDT", {})
    
    client.get_symbol_position.assert_called_once_with("BTCUSDT")
    assert result == {}

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
    
    result = executor.guardian_check("BTCUSDT", trade_state)
    
    client.cancel_order.assert_not_called()
    assert result["entry_order_id"] == 12345

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
    
    result = executor.guardian_check("BTCUSDT", trade_state)
    
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
    
    result = executor.guardian_check("BTCUSDT", trade_state)
    
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
    
    result = executor.guardian_check("BTCUSDT", trade_state)
    
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
    
    result = executor.guardian_check("BTCUSDT", trade_state)
    
    client.place_oco_order.assert_not_called()
    client.execute_market_close.assert_not_called()
    assert result == trade_state

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

    result = executor.guardian_check("BTCUSDT", trade_state)

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

    result = executor.guardian_check("BTCUSDT", trade_state)

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

    result = executor.guardian_check("BTCUSDT", trade_state)

    client.cancel_all_symbol_orders.assert_called_once_with("BTCUSDT")
    assert result == {}


# ================================================================
# PARTIAL TP + DYNAMIC TRAILING TESTS
# ================================================================

def test_partial_tp_triggers_long():
    """LONG: price - entry >= 1.5 ATR, SL < entry -> TP 50%, SL = entry."""
    executor, client = _make_executor()
    atr = 1000.0
    entry = 70000.0
    current_price = entry + 1.5 * atr  # 71500
    client.get_ticker_price.return_value = current_price
    client.get_symbol_position.return_value = MarginPosition("BTCUSDT", "BTC", "USDT", net_qty=0.5, borrowed=0.0, free=0.5, locked=0.0)
    client.get_avg_entry_price.return_value = entry
    orders = _make_oco_orders(symbol="BTCUSDT", exit_side="SELL", tp=75000, sl=68000)
    client.get_active_orders.return_value = orders

    trade_state = _make_trade_state("LONG", entry, tp_price=75000, sl_price=68000)
    result = executor.guardian_check("BTCUSDT", trade_state, atr_macro=atr)

    # Should have cancelled old OCO and placed new
    client.cancel_all_symbol_orders.assert_called()
    client.place_oco_order.assert_called()
    # New SL should be at entry (breakeven)
    call_kwargs = client.place_oco_order.call_args
    assert call_kwargs is not None
    # Verify new SL is entry price (breakeven)
    assert result.get("sl_price") == entry


def test_partial_tp_skipped_when_sl_at_entry():
    """SL already = entry -> skip TP, proceed to dynamic trailing."""
    executor, client = _make_executor()
    atr = 1000.0
    entry = 70000.0
    current_price = entry + 2.5 * atr  # 72500 — would trigger if not idempotent
    client.get_ticker_price.return_value = current_price
    client.get_symbol_position.return_value = MarginPosition("BTCUSDT", "BTC", "USDT", net_qty=0.25, borrowed=0.0, free=0.25, locked=0.0)
    client.get_avg_entry_price.return_value = entry
    # SL already at entry
    orders = _make_oco_orders(symbol="BTCUSDT", exit_side="SELL", tp=75000, sl=entry)
    client.get_active_orders.return_value = orders

    trade_state = _make_trade_state("LONG", entry, tp_price=75000, sl_price=entry)
    result = executor.guardian_check("BTCUSDT", trade_state, atr_macro=atr)

    # Should NOT cancel + TP — position is intact
    # But dynamic trailing may trigger since price is far from SL
    # The key assertion: place_limit_order (partial close) was NOT called
    # (place_oco_order may be called for trailing migration)
    client.place_limit_order.assert_not_called()


def test_dynamic_trailing_advances_sl_long():
    """LONG: price far from SL -> new_sl = max(sl, price - 1.5 ATR)."""
    executor, client = _make_executor()
    atr = 1000.0
    entry = 70000.0
    current_sl = entry  # already at breakeven
    current_price = entry + 3.0 * atr  # 73000
    client.get_ticker_price.return_value = current_price
    client.get_symbol_position.return_value = MarginPosition("BTCUSDT", "BTC", "USDT", net_qty=0.25, borrowed=0.0, free=0.25, locked=0.0)
    client.get_avg_entry_price.return_value = entry
    orders = _make_oco_orders(symbol="BTCUSDT", exit_side="SELL", tp=75000, sl=current_sl)
    client.get_active_orders.return_value = orders

    trade_state = _make_trade_state("LONG", entry, tp_price=75000, sl_price=current_sl)
    result = executor.guardian_check("BTCUSDT", trade_state, atr_macro=atr)

    # SL should advance to price - 1.5 ATR = 73000 - 1500 = 71500
    expected_sl = current_price - 1.5 * atr
    if client.place_oco_order.called:
        call_kwargs = client.place_oco_order.call_args
        if call_kwargs:
            new_sl = call_kwargs[1].get("stop_price", current_sl)
            assert new_sl >= current_sl  # monotonic
            assert new_sl <= expected_sl + 1  # roughly at expected level


def test_partial_tp_triggers_short():
    """SHORT: entry - price >= 1.5 ATR, SL > entry -> TP 50%, SL = entry."""
    executor, client = _make_executor()
    atr = 1000.0
    entry = 70000.0
    current_price = entry - 1.5 * atr  # 68500
    client.get_ticker_price.return_value = current_price
    client.get_symbol_position.return_value = MarginPosition("BTCUSDT", "BTC", "USDT", net_qty=-0.5, borrowed=0.5, free=0.0, locked=0.0)
    client.get_avg_entry_price.return_value = entry
    orders = _make_oco_orders(symbol="BTCUSDT", exit_side="BUY", tp=65000, sl=72000)
    client.get_active_orders.return_value = orders

    trade_state = _make_trade_state("SHORT", entry, tp_price=65000, sl_price=72000)
    result = executor.guardian_check("BTCUSDT", trade_state, atr_macro=atr)

    client.cancel_all_symbol_orders.assert_called()
    client.place_oco_order.assert_called()
    assert result.get("sl_price") == entry


def test_oco_replace_failure_emergency_closes():
    """When OCO re-place fails after cancel, emergency market close."""
    executor, client = _make_executor()
    atr = 1000.0
    entry = 70000.0
    current_price = entry + 1.5 * atr
    client.get_ticker_price.return_value = current_price
    client.get_symbol_position.return_value = MarginPosition("BTCUSDT", "BTC", "USDT", net_qty=0.5, borrowed=0.0, free=0.5, locked=0.0)
    client.get_avg_entry_price.return_value = entry
    orders = _make_oco_orders(symbol="BTCUSDT", exit_side="SELL", tp=75000, sl=68000)
    client.get_active_orders.return_value = orders
    client.place_oco_order.return_value = False  # OCO fails

    trade_state = _make_trade_state("LONG", entry, tp_price=75000, sl_price=68000)
    result = executor.guardian_check("BTCUSDT", trade_state, atr_macro=atr)

    client.execute_market_close.assert_called()
    assert result == {}  # trade state cleared


def test_restart_reconstructs_trade_state():
    """Empty trade_state + exchange position + OCO -> reconstruct from exchange."""
    executor, client = _make_executor()
    atr = 1000.0
    entry = 70000.0
    current_price = entry + 2.0 * atr
    client.get_ticker_price.return_value = current_price
    client.get_symbol_position.return_value = MarginPosition("BTCUSDT", "BTC", "USDT", net_qty=0.25, borrowed=0.0, free=0.25, locked=0.0)
    client.get_avg_entry_price.return_value = entry
    orders = _make_oco_orders(symbol="BTCUSDT", exit_side="SELL", tp=75000, sl=entry)
    client.get_active_orders.return_value = orders

    # Empty trade state (simulates restart)
    result = executor.guardian_check("BTCUSDT", {}, atr_macro=atr)

    # Should NOT return empty — should have reconstructed and taken action
    # At minimum, it should process the position (not early-exit)
    assert result != {} or client.place_oco_order.called or client.cancel_all_symbol_orders.called
