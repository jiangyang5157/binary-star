import os
import sys
from unittest.mock import MagicMock, ANY, patch
from datetime import datetime, timezone, timedelta

# Ensure the project root is in the path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(project_root)

from src.infrastructure.exchange.models import MarginPosition, MarginOrder, MarginAccountSummary
from src.agent.order_executor import MarginOrderExecutor

def print_separator(title):
    print("\n" + "="*60)
    print(f" {title} ".center(60, "="))
    print("="*60)

def _make_executor():
    """Creates a MarginOrderExecutor with a fully mocked client."""
    client = MagicMock()
    client.get_cross_margin_account.return_value = MarginAccountSummary(0.1, 0.0, 0.1, 999.0, "NORMAL", [])
    client.get_ticker_price.return_value = 70000.0
    client.cancel_all_symbol_orders.return_value = True
    client.execute_market_close.return_value = True
    client.place_limit_order.return_value = 12345  # Mock order ID
    client.place_oco_order.return_value = True
    client.cancel_order.return_value = True
    return MarginOrderExecutor(client), client


# ================================================================
# ENTRY TESTS (sync_with_opinion)
# ================================================================

def test_flat_to_long():
    print_separator("SCENARIO: FLAT -> LONG OPINION (LIMIT ENTRY)")
    executor, client = _make_executor()
    client.get_symbol_position.return_value = MarginPosition("BTCUSDT", "BTC", "USDT", 0.0, 0.0, 0.0, 0.0)
    client.get_active_orders.return_value = []
    
    order_id = executor.sync_with_opinion("BTCUSDT", "LONG", entry_price=74000, tp_price=76000, sl_price=73000)
    
    # Assertions
    client.cancel_all_symbol_orders.assert_not_called()
    client.execute_market_close.assert_not_called()
    client.place_limit_order.assert_called_once_with(symbol="BTCUSDT", side="BUY", qty=ANY, price=74000)
    assert order_id == 12345
    print("✅ Result: Correctly placed LIMIT entry order and returned order_id.")

def test_flat_with_stale_orders_to_long():
    print_separator("SCENARIO: FLAT WITH STALE ORDERS -> CLEAR + LIMIT ENTRY")
    executor, client = _make_executor()
    client.get_symbol_position.return_value = MarginPosition("BTCUSDT", "BTC", "USDT", 0.0, 0.0, 0.0, 0.0)
    stale_order = MarginOrder("BTCUSDT", 1, "", 75000, 1.0, 0.0, "NEW", "GTC", "LIMIT_MAKER", "SELL", 0)
    client.get_active_orders.return_value = [stale_order]
    
    order_id = executor.sync_with_opinion("BTCUSDT", "LONG", entry_price=74000, tp_price=76000, sl_price=73000)
    
    client.cancel_all_symbol_orders.assert_called_once_with("BTCUSDT")
    client.place_limit_order.assert_called_once_with(symbol="BTCUSDT", side="BUY", qty=ANY, price=74000)
    assert order_id == 12345
    print("✅ Result: Cleared stale orders and placed LIMIT entry.")

def test_pivot_short_to_long():
    print_separator("SCENARIO: HOLDING SHORT -> LONG OPINION (PIVOT)")
    executor, client = _make_executor()
    client.get_symbol_position.return_value = MarginPosition("BTCUSDT", "BTC", "USDT", -0.5, 0.5, 0.0, 0.0)
    
    order_id = executor.sync_with_opinion("BTCUSDT", "LONG", entry_price=74000, tp_price=76000, sl_price=73000)
    
    client.cancel_all_symbol_orders.assert_called_once_with("BTCUSDT")
    client.execute_market_close.assert_called_once_with("BTCUSDT")
    client.place_limit_order.assert_called_once_with(symbol="BTCUSDT", side="BUY", qty=ANY, price=74000)
    assert order_id == 12345
    print("✅ Result: Cancelled orders, Market Closed Short, placed LIMIT entry Long.")

def test_same_direction_optimization():
    print_separator("SCENARIO: HOLDING LONG -> LONG OPINION (OPTIMIZATION)")
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
        price=76000, stop_price=73000, stop_limit_price=72999.0
    )
    assert order_id is None  # No new entry order for same-direction
    print("✅ Result: Protected Net Qty (2.0) with optimized TP (76000) and SL (73000).")

def test_non_whitelisted_symbol():
    print_separator("SCENARIO: NON-WHITELISTED SYMBOL (ETHUSDT)")
    executor, client = _make_executor()
    
    order_id = executor.sync_with_opinion("ETHUSDT", "LONG", entry_price=2000, tp_price=2200, sl_price=1900)
    
    client.get_symbol_position.assert_not_called()
    client.place_limit_order.assert_not_called()
    assert order_id is None
    print("✅ Result: Aborted execution for non-whitelisted symbol.")


# ================================================================
# GUARDIAN TESTS
# ================================================================

def test_guardian_no_trade_state():
    print_separator("GUARDIAN: Empty trade_state -> No-op")
    executor, client = _make_executor()
    
    result = executor.guardian_check("BTCUSDT", {})
    
    client.get_symbol_position.assert_not_called()
    assert result == {}
    print("✅ Result: Guardian correctly skipped with empty state.")

def test_guardian_entry_pending_not_expired():
    print_separator("GUARDIAN: Entry pending, not expired -> No-op")
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
    print("✅ Result: Entry order still pending, Guardian waiting.")

def test_guardian_entry_expired():
    print_separator("GUARDIAN: Entry expired -> Cancel order")
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
    print("✅ Result: Expired entry order cancelled, trade state cleared.")

def test_guardian_unprotected_position_place_oco():
    print_separator("GUARDIAN: Position exists, no OCO -> Place OCO")
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
        price=76000.0, stop_price=73000.0, stop_limit_price=72999.0
    )
    assert "entry_order_id" not in result  # Entry tracking removed after OCO placed
    print("✅ Result: Guardian placed OCO to protect unprotected LONG position.")

def test_guardian_sl_breached_emergency_close():
    print_separator("GUARDIAN: Position exists, SL breached -> Emergency close")
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
    print("✅ Result: Guardian detected SL breach, emergency market close executed.")

def test_guardian_position_already_protected():
    print_separator("GUARDIAN: Position protected with OCO -> No-op")
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
    print("✅ Result: Guardian confirmed position is protected. No action.")


if __name__ == "__main__":
    test_flat_to_long()
    test_flat_with_stale_orders_to_long()
    test_pivot_short_to_long()
    test_same_direction_optimization()
    test_non_whitelisted_symbol()
    test_guardian_no_trade_state()
    test_guardian_entry_pending_not_expired()
    test_guardian_entry_expired()
    test_guardian_unprotected_position_place_oco()
    test_guardian_sl_breached_emergency_close()
    test_guardian_position_already_protected()
    print("\n" + "*"*60)
    print("All Executor + Guardian Tests Passed Successfully.")
    print("*"*60)
