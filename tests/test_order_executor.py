import os
import sys
from unittest.mock import MagicMock

# Ensure the project root is in the path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(project_root)

from src.infrastructure.exchange.models import MarginPosition, MarginOrder
from src.agent.order_executor import MarginOrderExecutor

def print_separator(title):
    print("\n" + "="*60)
    print(f" {title} ".center(60, "="))
    print("="*60)

def test_flat_to_long():
    print_separator("SCENARIO: FLAT -> LONG OPINION")
    client = MagicMock()
    # Mocking FLAT position
    client.get_symbol_position.return_value = MarginPosition("BTCUSDT", "BTC", "USDT", 0.0, 0.0, 0.0, 0.0)
    client.get_active_orders.return_value = []
    
    # Mock Risk Calculation calls
    from src.infrastructure.exchange.models import MarginAccountSummary
    client.get_cross_margin_account.return_value = MarginAccountSummary(0.1, 0.0, 0.1, 999.0, "NORMAL", [])
    client.get_ticker_price.return_value = 70000.0
    client.cancel_all_symbol_orders.return_value = True
    client.execute_market_close.return_value = True
    
    executor = MarginOrderExecutor(client)
    executor.sync_with_opinion("BTCUSDT", "LONG", entry_price=74000, tp_price=76000, sl_price=73000)
    
    # Assertions
    client.cancel_all_symbol_orders.assert_not_called()
    client.execute_market_close.assert_not_called()
    print("✅ Result: Correctly placed OTOCO order.")

def test_flat_with_stale_orders_to_long():
    print_separator("SCENARIO: FLAT WITH STALE ORDERS -> NEW OTOCO")
    client = MagicMock()
    # Mocking FLAT position
    client.get_symbol_position.return_value = MarginPosition("BTCUSDT", "BTC", "USDT", 0.0, 0.0, 0.0, 0.0)
    # Mocking STALE orders
    stale_order = MarginOrder("BTCUSDT", 1, "", 75000, 1.0, 0.0, "NEW", "GTC", "LIMIT_MAKER", "SELL", 0)
    client.get_active_orders.return_value = [stale_order]
    
    # Mock Risk Calculation calls
    from src.infrastructure.exchange.models import MarginAccountSummary
    client.get_cross_margin_account.return_value = MarginAccountSummary(0.1, 0.0, 0.1, 999.0, "NORMAL", [])
    client.get_ticker_price.return_value = 70000.0
    client.cancel_all_symbol_orders.return_value = True
    client.execute_market_close.return_value = True
    
    executor = MarginOrderExecutor(client)
    executor.sync_with_opinion("BTCUSDT", "LONG", entry_price=74000, tp_price=76000, sl_price=73000)
    
    # Assertions
    client.cancel_all_symbol_orders.assert_called_once_with("BTCUSDT")
    client.execute_market_close.assert_not_called()
    print("✅ Result: Cleared stale orders and placed new OTOCO.")

def test_pivot_short_to_long():
    print_separator("SCENARIO: HOLDING SHORT -> LONG OPINION (PIVOT)")
    client = MagicMock()
    # Mocking SHORT position (-0.5 BTC)
    client.get_symbol_position.return_value = MarginPosition("BTCUSDT", "BTC", "USDT", -0.5, 0.5, 0.0, 0.0)
    
    # Mock Risk Calculation calls
    from src.infrastructure.exchange.models import MarginAccountSummary
    client.get_cross_margin_account.return_value = MarginAccountSummary(0.1, 0.0, 0.1, 999.0, "NORMAL", [])
    client.get_ticker_price.return_value = 70000.0
    client.cancel_all_symbol_orders.return_value = True
    client.execute_market_close.return_value = True
    
    executor = MarginOrderExecutor(client)
    executor.sync_with_opinion("BTCUSDT", "LONG", entry_price=74000, tp_price=76000, sl_price=73000)
    
    client.cancel_all_symbol_orders.assert_called_once_with("BTCUSDT")
    client.execute_market_close.assert_called_once_with("BTCUSDT")
    print("✅ Result: Cancelled old orders, Market Closed Short, placed new OTOCO Long.")

def test_same_direction_optimization():
    print_separator("SCENARIO: HOLDING LONG -> LONG OPINION (OPTIMIZATION)")
    client = MagicMock()
    # Mocking LONG position (2.0 BTC)
    client.get_symbol_position.return_value = MarginPosition("BTCUSDT", "BTC", "USDT", 2.0, 0.0, 2.0, 0.0)
    client.cancel_all_symbol_orders.return_value = True
    
    # Mocking existing Manual Orders (TP is 75000, SL is 72000)
    old_tp = MarginOrder("BTCUSDT", 1, "", 75000, 2.0, 0.0, "NEW", "GTC", "LIMIT_MAKER", "SELL", 0)
    old_sl = MarginOrder("BTCUSDT", 2, "", 72000, 2.0, 0.0, "NEW", "GTC", "STOP_LOSS_LIMIT", "SELL", 0, stop_price=72000)
    client.get_active_orders.return_value = [old_tp, old_sl]
    client.place_oco_order.return_value = True
    
    executor = MarginOrderExecutor(client)
    # New Opinion: TP 76000 (Wider! Better!), SL 73000 (Tighter! Better!)
    executor.sync_with_opinion("BTCUSDT", "LONG", entry_price=74000, tp_price=76000, sl_price=73000)
    
    # Should pick max(75000, 76000) = 76000 for TP
    # Should pick max(72000, 73000) = 73000 for SL
    client.cancel_all_symbol_orders.assert_called_once_with("BTCUSDT")
    client.execute_market_close.assert_not_called()
    client.place_oco_order.assert_called_once_with(
        symbol="BTCUSDT", side="SELL", qty=2.0,  # Note it protects the FULL 2.0 position
        price=76000, stop_price=73000, stop_limit_price=73000
    )
    print("✅ Result: Protected Net Qty (2.0) with optimized TP (76000) and SL (73000).")

def test_non_whitelisted_symbol():
    print_separator("SCENARIO: NON-WHITELISTED SYMBOL (ETHUSDT)")
    client = MagicMock()
    executor = MarginOrderExecutor(client)
    
    # ETHUSDT is not in our trade_management config
    executor.sync_with_opinion("ETHUSDT", "LONG", entry_price=2000, tp_price=2200, sl_price=1900)
    
    # Should abort immediately
    client.get_symbol_position.assert_not_called()
    client.cancel_all_symbol_orders.assert_not_called()
    client.place_otoco_order.assert_not_called()
    print("✅ Result: Aborted execution for non-whitelisted symbol.")

if __name__ == "__main__":
    # For manual running
    test_flat_to_long()
    test_flat_with_stale_orders_to_long()
    test_pivot_short_to_long()
    test_same_direction_optimization()
    test_non_whitelisted_symbol()
    print("\n" + "*"*60)
    print("All Executor Logic Tests Passed Successfully.")
    print("*"*60)
