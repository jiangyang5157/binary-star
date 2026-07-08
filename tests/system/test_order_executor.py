import os
import sys
import yaml
from unittest.mock import MagicMock, ANY, patch
from datetime import datetime, timezone, timedelta

# Ensure the project root is in the path
_tests_dir = os.path.dirname(os.path.abspath(__file__))          # .../tests/system
project_root = os.path.dirname(os.path.dirname(_tests_dir))      # .../
sys.path.append(project_root)

from src.infrastructure.exchange.models import MarginPosition, MarginOrder
from src.agent.order_executor import MarginOrderExecutor
from tests.executor_fixtures import make_executor as _make_executor

# Load production config for ratio-based test expectations.
# Tests compute expected values from config — changing exit_ladder
# in global_config.yaml does NOT break these tests.
_config_path = os.path.join(project_root, "config", "global_config.yaml")
with open(_config_path) as f:
    _cfg = yaml.safe_load(f)
_LV = _cfg["guardian"]["exit_ladder"]["levels"]
L1_TP, L1_SL = _LV[0]["tp_ratio"], _LV[0]["sl_lock"]
L2_TP, L2_SL = _LV[1]["tp_ratio"], _LV[1]["sl_lock"]
L3_TP, L3_SL = _LV[2]["tp_ratio"], _LV[2]["sl_lock"]


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
    client.place_otoco_order.assert_called_once_with(symbol="BTCUSDT", side="BUY", qty=ANY, entry_price=74000, tp_price=76000, sl_trigger_price=73000, sl_limit_price=ANY)
    assert order_id == 12345

def test_flat_with_stale_orders_to_long():

    executor, client = _make_executor()
    client.get_symbol_position.return_value = MarginPosition("BTCUSDT", "BTC", "USDT", 0.0, 0.0, 0.0, 0.0)
    stale_order = MarginOrder("BTCUSDT", 1, "", 75000, 1.0, 0.0, "NEW", "GTC", "LIMIT_MAKER", "SELL", 0)
    client.get_active_orders.return_value = [stale_order]
    
    order_id = executor.sync_with_opinion("BTCUSDT", "LONG", entry_price=74000, tp_price=76000, sl_price=73000)
    
    client.cancel_all_symbol_orders.assert_called_once_with("BTCUSDT")
    client.place_otoco_order.assert_called_once_with(symbol="BTCUSDT", side="BUY", qty=ANY, entry_price=74000, tp_price=76000, sl_trigger_price=73000, sl_limit_price=ANY)
    assert order_id == 12345

def test_pivot_short_to_long_no_sl():
    """Pivot: position exists without protection → skip, let Guardian manage."""

    executor, client = _make_executor()
    client.get_symbol_position.return_value = MarginPosition("BTCUSDT", "BTC", "USDT", -0.5, 0.5, 0.0, 0.0)
    client.get_active_orders.return_value = []  # No stop loss

    order_id = executor.sync_with_opinion("BTCUSDT", "LONG", entry_price=74000, tp_price=76000, sl_price=73000)

    # Bot does not intervene with existing positions — Guardian handles protection
    client.cancel_all_symbol_orders.assert_not_called()
    client.execute_market_close.assert_not_called()
    client.place_limit_order.assert_not_called()
    client.place_oco_order.assert_not_called()
    assert order_id is None

def test_pivot_short_with_sl_to_long():
    """Pivot: position exists with OCO protection → skip, let Guardian manage."""

    executor, client = _make_executor()
    client.get_symbol_position.return_value = MarginPosition("BTCUSDT", "BTC", "USDT", -0.5, 0.5, 0.0, 0.0)
    sl_order = MarginOrder("BTCUSDT", 55, "", 86000, 0.5, 0.0, "NEW", "GTC", "STOP_LOSS_LIMIT", "BUY", 0, stop_price=86000)
    client.get_active_orders.return_value = [sl_order]
    client.get_ticker_price.return_value = 84000.0

    order_id = executor.sync_with_opinion("BTCUSDT", "LONG", entry_price=82000, tp_price=80000, sl_price=85000)

    # Bot does not intervene with existing positions — Guardian handles protection
    client.cancel_all_symbol_orders.assert_not_called()
    client.execute_market_close.assert_not_called()
    client.place_oco_order.assert_not_called()
    client.place_limit_order.assert_not_called()
    assert order_id is None

def test_pivot_short_with_optimal_tp_to_long():
    """Pivot: position exists with OCO (SL+TP) → skip, let Guardian manage."""

    executor, client = _make_executor()
    client.get_symbol_position.return_value = MarginPosition("BTCUSDT", "BTC", "USDT", -0.5, 0.5, 0.0, 0.0)
    sl_order = MarginOrder("BTCUSDT", 55, "", 86000, 0.5, 0.0, "NEW", "GTC", "STOP_LOSS_LIMIT", "BUY", 0, stop_price=86000)
    tp_order = MarginOrder("BTCUSDT", 56, "", 79000, 0.5, 0.0, "NEW", "GTC", "LIMIT_MAKER", "BUY", 0)
    client.get_active_orders.return_value = [sl_order, tp_order]
    client.get_ticker_price.return_value = 84000.0

    order_id = executor.sync_with_opinion("BTCUSDT", "LONG", entry_price=82000, tp_price=80000, sl_price=85000)

    # Bot does not intervene with existing positions
    client.cancel_all_symbol_orders.assert_not_called()
    client.place_oco_order.assert_not_called()
    client.place_limit_order.assert_not_called()
    assert order_id is None

def test_pivot_short_with_oco_and_stale_limit():
    """Pivot: position with OCO + stale limit orders → skip, let Guardian manage."""

    executor, client = _make_executor()
    client.get_symbol_position.return_value = MarginPosition("BTCUSDT", "BTC", "USDT", -0.5, 0.5, 0.0, 0.0)

    sl_order = MarginOrder("BTCUSDT", 100, "", 86000, 0.5, 0.0, "NEW", "GTC", "STOP_LOSS_LIMIT", "BUY", 0, stop_price=86000)
    tp_order = MarginOrder("BTCUSDT", 101, "", 73000, 0.5, 0.0, "NEW", "GTC", "LIMIT_MAKER", "BUY", 0)
    stale_limit = MarginOrder("BTCUSDT", 102, "", 74000, 0.5, 0.0, "NEW", "GTC", "LIMIT", "BUY", 0)
    client.get_active_orders.return_value = [sl_order, tp_order, stale_limit]
    client.get_ticker_price.return_value = 84000.0

    order_id = executor.sync_with_opinion("BTCUSDT", "LONG", entry_price=74600, tp_price=80000, sl_price=85000)

    # Bot does not intervene with existing positions
    client.cancel_all_symbol_orders.assert_not_called()
    client.place_oco_order.assert_not_called()
    client.place_limit_order.assert_not_called()
    assert order_id is None

def test_pivot_short_to_long_overshot():
    """Pivot: overshot position → skip, Guardian handles (no force-close)."""

    executor, client = _make_executor()
    client.get_symbol_position.return_value = MarginPosition("BTCUSDT", "BTC", "USDT", -0.5, 0.5, 0.0, 0.0)
    sl_order = MarginOrder("BTCUSDT", 55, "", 86000, 0.5, 0.0, "NEW", "GTC", "STOP_LOSS_LIMIT", "BUY", 0, stop_price=86000)
    client.get_active_orders.return_value = [sl_order]
    client.get_ticker_price.return_value = 69950.0

    order_id = executor.sync_with_opinion("BTCUSDT", "LONG", entry_price=70000, tp_price=75000, sl_price=69000)

    # Bot does not intervene — Guardian/restart gap will handle
    client.cancel_all_symbol_orders.assert_not_called()
    client.execute_market_close.assert_not_called()
    client.place_oco_order.assert_not_called()
    client.place_limit_order.assert_not_called()
    assert order_id is None

def test_pivot_short_with_sl_oco_fails_abort():
    """Pivot: position exists → skip regardless of OCO state. No emergency close needed."""

    executor, client = _make_executor()
    client.get_symbol_position.return_value = MarginPosition("BTCUSDT", "BTC", "USDT", -0.5, 0.5, 0.0, 0.0)
    sl_order = MarginOrder("BTCUSDT", 55, "", 86000, 0.5, 0.0, "NEW", "GTC", "STOP_LOSS_LIMIT", "BUY", 0, stop_price=86000)
    client.get_active_orders.return_value = [sl_order]
    client.get_ticker_price.return_value = 84000.0
    client.place_oco_order.return_value = False  # irrelevant — we never call it

    order_id = executor.sync_with_opinion("BTCUSDT", "LONG", entry_price=82000, tp_price=80000, sl_price=85000)

    # Bot does not intervene — no emergency close, no new entry, no OCO manipulation
    client.cancel_all_symbol_orders.assert_not_called()
    client.place_oco_order.assert_not_called()
    client.execute_market_close.assert_not_called()
    client.place_limit_order.assert_not_called()
    assert order_id is None

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
        "otoco_placed_at": datetime.now(timezone.utc) - timedelta(hours=1),
        "projected_waiting_hours": 4.0,
        "tp_price": 76000,
        "sl_price": 73000,
    }

    result, level = executor.guardian_check("BTCUSDT", trade_state)

    client.cancel_all_symbol_orders.assert_not_called()
    assert result["direction"] == "LONG"
    assert level is None

def test_guardian_entry_expired():

    executor, client = _make_executor()
    client.get_symbol_position.return_value = MarginPosition("BTCUSDT", "BTC", "USDT", 0.0, 0.0, 0.0, 0.0)
    client.get_active_orders.return_value = []

    trade_state = {
        "direction": "LONG",
        "otoco_placed_at": datetime.now(timezone.utc) - timedelta(hours=5),
        "projected_waiting_hours": 4.0,
        "tp_price": 76000,
        "sl_price": 73000,
    }

    result, level = executor.guardian_check("BTCUSDT", trade_state)

    client.cancel_all_symbol_orders.assert_called_once_with("BTCUSDT")
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
    client.place_otoco_order.assert_called_once_with(symbol="BTCUSDT", side="SELL", qty=ANY, entry_price=66000, tp_price=64000, sl_trigger_price=67000, sl_limit_price=ANY)
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
# EXIT LADDER + DYNAMIC TRAILING TESTS (multi-level, daemon-memory driven)
# ================================================================
# current_level = next level to check (0=L1, 1=L2, 2=L3, 3=all done)
# Returned level = updated next level (or None for non-Case-4 paths)

def test_exit_ladder_l1_triggers_long():
    """L1 fires when progress >= configured target, closes tp_ratio fraction."""
    executor, client = _make_executor()
    entry = 70000.0
    tp = 75000.0
    current_price = entry + 0.50 * (tp - entry)
    client.get_ticker_price.return_value = current_price
    client.get_symbol_position.return_value = MarginPosition(
        "BTCUSDT", "BTC", "USDT", net_qty=0.5, borrowed=0.0, free=0.5, locked=0.0
    )
    client.get_avg_entry_price.return_value = entry
    orders = _make_oco_orders(symbol="BTCUSDT", exit_side="SELL", tp=tp, sl=68000)
    client.get_active_orders.return_value = orders

    trade_state = _make_trade_state("LONG", entry, tp_price=tp, sl_price=68000)
    result, level = executor.guardian_check("BTCUSDT", trade_state,
                                            current_level=0)

    client.execute_partial_market_close.assert_called_once()
    close_call = client.execute_partial_market_close.call_args
    assert abs(close_call[1]["qty"] - 0.5 * L1_TP) < 0.001
    assert close_call[1]["side"] == "SELL"
    client.place_oco_order.assert_called()
    oco_call = client.place_oco_order.call_args
    expected_sl = entry + (tp - entry) * L1_SL
    assert abs(oco_call[1]["stop_price"] - expected_sl) < 10
    assert abs(result.get("sl_price") - expected_sl) < 10
    assert level == 1


def test_exit_ladder_l1_idempotent_via_level():
    """current_level=1 -> L1 skipped, L2 not met -> no partial close."""
    executor, client = _make_executor()
    entry = 70000.0
    tp = 75000.0
    current_price = entry + 0.28 * (tp - entry)
    client.get_ticker_price.return_value = current_price
    client.get_symbol_position.return_value = MarginPosition(
        "BTCUSDT", "BTC", "USDT", net_qty=0.4, borrowed=0.0, free=0.4, locked=0.0
    )
    client.get_avg_entry_price.return_value = entry
    orders = _make_oco_orders(symbol="BTCUSDT", exit_side="SELL", tp=tp, sl=entry)
    client.get_active_orders.return_value = orders

    trade_state = _make_trade_state("LONG", entry, tp_price=tp, sl_price=entry)
    result, level = executor.guardian_check("BTCUSDT", trade_state,
                                            current_level=1)

    client.execute_partial_market_close.assert_not_called()


def test_exit_ladder_l2_triggers_long():
    """L1 done, L2 placeholder (tp_ratio=0) → no close, advance to L3 check."""
    executor, client = _make_executor()
    entry = 70000.0
    tp = 75000.0
    current_price = entry + 0.75 * (tp - entry)
    client.get_ticker_price.return_value = current_price
    client.get_symbol_position.return_value = MarginPosition(
        "BTCUSDT", "BTC", "USDT", net_qty=0.4, borrowed=0.0, free=0.4, locked=0.0
    )
    client.get_avg_entry_price.return_value = entry
    orders = _make_oco_orders(symbol="BTCUSDT", exit_side="SELL", tp=tp, sl=entry)
    client.get_active_orders.return_value = orders

    trade_state = _make_trade_state("LONG", entry, tp_price=tp, sl_price=entry)
    result, level = executor.guardian_check("BTCUSDT", trade_state,
                                            current_level=1)

    client.execute_partial_market_close.assert_not_called()
    assert level == 2


def test_exit_ladder_l3_triggers_long():
    """L2 done, progress >= L3 target -> L3 fires."""
    executor, client = _make_executor()
    entry = 70000.0
    tp = 75000.0
    current_price = entry + 0.95 * (tp - entry)
    client.get_ticker_price.return_value = current_price
    client.get_symbol_position.return_value = MarginPosition(
        "BTCUSDT", "BTC", "USDT", net_qty=0.32, borrowed=0.0, free=0.32, locked=0.0
    )
    client.get_avg_entry_price.return_value = entry
    orders = _make_oco_orders(symbol="BTCUSDT", exit_side="SELL", tp=tp, sl=entry)
    client.get_active_orders.return_value = orders

    trade_state = _make_trade_state("LONG", entry, tp_price=tp, sl_price=entry)
    result, level = executor.guardian_check("BTCUSDT", trade_state,
                                            current_level=2)

    client.execute_partial_market_close.assert_called_once()
    close_call = client.execute_partial_market_close.call_args
    assert abs(close_call[1]["qty"] - 0.32 * L3_TP) < 0.001
    assert level == 3


def test_multi_level_same_pulse():
    """Progress exceeds all targets -> all levels fire in one pulse."""
    executor, client = _make_executor()
    entry = 70000.0
    tp = 80000.0
    current_price = entry + 0.90 * (tp - entry)
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
    orders = _make_oco_orders(symbol="BTCUSDT", exit_side="SELL", tp=tp, sl=68000)
    client.get_active_orders.return_value = orders

    trade_state = _make_trade_state("LONG", entry, tp_price=tp, sl_price=68000)
    result, level = executor.guardian_check("BTCUSDT", trade_state,
                                            current_level=0)

    calls = client.execute_partial_market_close.call_args_list
    assert abs(calls[0][1]["qty"] - 0.5 * L1_TP) < 0.001
    idx = 1
    qty_remaining = 0.5 * (1 - L1_TP)
    if L2_TP > 0:
        assert abs(calls[idx][1]["qty"] - qty_remaining * L2_TP) < 0.001
        qty_remaining *= (1 - L2_TP)
        idx += 1
    assert abs(calls[idx][1]["qty"] - qty_remaining * L3_TP) < 0.001
    assert level == 3


def test_trailing_at_l1_with_sl_lock():
    """L1 active, no further trigger -> trailing SL applied with L1 sl_lock."""
    executor, client = _make_executor()
    entry = 70000.0
    tp = 75000.0
    current_price = entry + 0.60 * (tp - entry)
    client.get_ticker_price.return_value = current_price
    client.get_symbol_position.return_value = MarginPosition(
        "BTCUSDT", "BTC", "USDT", net_qty=0.5, borrowed=0.0, free=0.5, locked=0.0
    )
    client.get_avg_entry_price.return_value = entry
    orders = _make_oco_orders(symbol="BTCUSDT", exit_side="SELL", tp=tp, sl=entry)
    client.get_active_orders.return_value = orders

    trade_state = _make_trade_state("LONG", entry, tp_price=tp, sl_price=entry)
    client.place_oco_order.reset_mock()
    client.cancel_all_symbol_orders.reset_mock()

    result, level = executor.guardian_check("BTCUSDT", trade_state,
                                            current_level=1)

    client.execute_partial_market_close.assert_not_called()
    assert client.cancel_all_symbol_orders.called
    assert client.place_oco_order.called
    oco_call = client.place_oco_order.call_args
    new_sl = oco_call[1]["stop_price"]
    expected_sl = entry + (tp - entry) * L1_SL
    assert abs(new_sl - expected_sl) < 10


def test_trailing_at_l2_with_sl_lock():
    """L3 active, no further trigger -> trailing SL applied with L3 sl_lock."""
    executor, client = _make_executor()
    entry = 70000.0
    tp = 75000.0
    current_price = entry + 0.75 * (tp - entry)
    client.get_ticker_price.return_value = current_price
    client.get_symbol_position.return_value = MarginPosition(
        "BTCUSDT", "BTC", "USDT", net_qty=0.32, borrowed=0.0, free=0.32, locked=0.0
    )
    client.get_avg_entry_price.return_value = entry
    orders = _make_oco_orders(symbol="BTCUSDT", exit_side="SELL", tp=tp, sl=entry)
    client.get_active_orders.return_value = orders

    trade_state = _make_trade_state("LONG", entry, tp_price=tp, sl_price=entry)
    result, level = executor.guardian_check("BTCUSDT", trade_state,
                                            current_level=3)

    assert client.cancel_all_symbol_orders.called
    assert client.place_oco_order.called
    oco_call = client.place_oco_order.call_args
    new_sl = oco_call[1]["stop_price"]
    expected_sl = entry + (tp - entry) * L3_SL
    assert abs(new_sl - expected_sl) < 10


def test_trailing_at_l3_with_tight_sl_lock():
    """L3 active, no further trigger -> trailing SL applied with L3 sl_lock."""
    executor, client = _make_executor()
    entry = 70000.0
    tp = 75000.0
    current_price = entry + 0.95 * (tp - entry)
    client.get_ticker_price.return_value = current_price
    client.get_symbol_position.return_value = MarginPosition(
        "BTCUSDT", "BTC", "USDT", net_qty=0.256, borrowed=0.0, free=0.256, locked=0.0
    )
    client.get_avg_entry_price.return_value = entry
    orders = _make_oco_orders(symbol="BTCUSDT", exit_side="SELL", tp=tp, sl=entry)
    client.get_active_orders.return_value = orders

    trade_state = _make_trade_state("LONG", entry, tp_price=tp, sl_price=entry)
    result, level = executor.guardian_check("BTCUSDT", trade_state,
                                            current_level=3)

    oco_call = client.place_oco_order.call_args
    new_sl = oco_call[1]["stop_price"]
    expected_sl = entry + (tp - entry) * L3_SL
    assert abs(new_sl - expected_sl) < 10


def test_exit_ladder_l1_triggers_short():
    """SHORT: L1 fires when progress >= configured target."""
    executor, client = _make_executor()
    entry = 70000.0
    tp = 65000.0
    current_price = entry - 0.50 * (entry - tp)
    client.get_ticker_price.return_value = current_price
    client.get_symbol_position.return_value = MarginPosition(
        "BTCUSDT", "BTC", "USDT", net_qty=-0.5, borrowed=0.5, free=0.0, locked=0.0
    )
    client.get_avg_entry_price.return_value = entry
    orders = _make_oco_orders(symbol="BTCUSDT", exit_side="BUY", tp=tp, sl=72000)
    client.get_active_orders.return_value = orders

    trade_state = _make_trade_state("SHORT", entry, tp_price=tp, sl_price=72000)
    result, level = executor.guardian_check("BTCUSDT", trade_state,
                                            current_level=0)

    client.execute_partial_market_close.assert_called_once()
    close_call = client.execute_partial_market_close.call_args
    assert abs(close_call[1]["qty"] - 0.5 * L1_TP) < 0.001
    assert close_call[1]["side"] == "BUY"
    client.place_oco_order.assert_called()
    expected_sl = entry - (entry - tp) * L1_SL
    assert abs(result.get("sl_price") - expected_sl) < 10
    assert level == 1


def test_exit_ladder_skips_when_long_in_loss():
    """LONG in loss: deviation <= 0 → exit ladder does NOT fire."""
    executor, client = _make_executor()
    atr = 1000.0
    entry = 70000.0
    current_price = entry - 1.5 * atr
    client.get_ticker_price.return_value = current_price
    client.get_symbol_position.return_value = MarginPosition(
        "BTCUSDT", "BTC", "USDT", net_qty=0.5, borrowed=0.0, free=0.5, locked=0.0)
    client.get_avg_entry_price.return_value = entry
    orders = _make_oco_orders(symbol="BTCUSDT", exit_side="SELL", tp=75000, sl=68000)
    client.get_active_orders.return_value = orders

    trade_state = _make_trade_state("LONG", entry, tp_price=75000, sl_price=68000)
    result, level = executor.guardian_check("BTCUSDT", trade_state,
                                            current_level=0)

    client.execute_partial_market_close.assert_not_called()
    assert result != {}


def test_exit_ladder_skips_when_short_in_loss():
    """SHORT in loss: deviation <= 0 → exit ladder does NOT fire."""
    executor, client = _make_executor()
    atr = 1000.0
    entry = 70000.0
    current_price = entry + 1.5 * atr
    client.get_ticker_price.return_value = current_price
    client.get_symbol_position.return_value = MarginPosition(
        "BTCUSDT", "BTC", "USDT", net_qty=-0.5, borrowed=0.5, free=0.0, locked=0.0)
    client.get_avg_entry_price.return_value = entry
    orders = _make_oco_orders(symbol="BTCUSDT", exit_side="BUY", tp=65000, sl=72000)
    client.get_active_orders.return_value = orders

    trade_state = _make_trade_state("SHORT", entry, tp_price=65000, sl_price=72000)
    result, level = executor.guardian_check("BTCUSDT", trade_state,
                                            current_level=0)

    client.execute_partial_market_close.assert_not_called()
    assert result != {}


def test_oco_replace_failure_emergency_closes():
    """When OCO re-place fails after cancel, emergency market close."""
    executor, client = _make_executor()
    entry = 70000.0
    tp = 75000.0
    current_price = entry + 0.55 * (tp - entry)
    client.get_ticker_price.return_value = current_price
    client.get_symbol_position.return_value = MarginPosition(
        "BTCUSDT", "BTC", "USDT", net_qty=0.5, borrowed=0.0, free=0.5, locked=0.0
    )
    client.get_avg_entry_price.return_value = entry
    orders = _make_oco_orders(symbol="BTCUSDT", exit_side="SELL", tp=tp, sl=68000)
    client.get_active_orders.return_value = orders
    client.place_oco_order.return_value = False

    trade_state = _make_trade_state("LONG", entry, tp_price=tp, sl_price=68000)
    result, level = executor.guardian_check("BTCUSDT", trade_state,
                                            current_level=0)

    client.execute_market_close.assert_any_call("BTCUSDT")
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
    client.get_ticker_price.return_value = entry + 1.0 * 1000
    orders = _make_oco_orders(symbol="BTCUSDT", exit_side="SELL", tp=75000, sl=68000)
    client.get_active_orders.return_value = orders

    trade_state = _make_trade_state("LONG", entry, tp_price=75000, sl_price=68000)
    level = executor.find_level_and_sync_sl("BTCUSDT", trade_state)
    assert level == 0


def test_find_level_l2_fired_syncs_sl():
    """find_level: SL=entry, progress past L2 target -> returns 2, syncs SL."""
    executor, client = _make_executor()
    atr = 1000.0
    entry = 70000.0
    client.get_symbol_position.return_value = MarginPosition(
        "BTCUSDT", "BTC", "USDT", net_qty=0.32, borrowed=0.0, free=0.32, locked=0.0
    )
    client.get_avg_entry_price.return_value = entry
    client.get_ticker_price.return_value = entry + 4.0 * atr
    # SL at entry → L1 fired
    orders = _make_oco_orders(symbol="BTCUSDT", exit_side="SELL", tp=75000, sl=entry)
    client.get_active_orders.return_value = orders

    trade_state = _make_trade_state("LONG", entry, tp_price=75000, sl_price=entry)
    level = executor.find_level_and_sync_sl("BTCUSDT", trade_state)

    assert level == 2
    if client.place_oco_order.called:
        oco_call = client.place_oco_order.call_args
        expected_sl = entry + (75000 - entry) * L2_SL
        assert abs(oco_call[1]["stop_price"] - expected_sl) < 100


def test_find_level_l3_all_fired():
    """find_level: SL=entry, progress past L3 target -> returns 3."""
    executor, client = _make_executor()
    atr = 1000.0
    entry = 70000.0
    client.get_symbol_position.return_value = MarginPosition(
        "BTCUSDT", "BTC", "USDT", net_qty=0.256, borrowed=0.0, free=0.256, locked=0.0
    )
    client.get_avg_entry_price.return_value = entry
    client.get_ticker_price.return_value = entry + 6.0 * atr
    orders = _make_oco_orders(symbol="BTCUSDT", exit_side="SELL", tp=76500, sl=entry)
    client.get_active_orders.return_value = orders

    trade_state = _make_trade_state("LONG", entry, tp_price=76500, sl_price=entry)
    level = executor.find_level_and_sync_sl("BTCUSDT", trade_state)

    assert level == 3
    if client.place_oco_order.called:
        oco_call = client.place_oco_order.call_args
        expected_sl = entry + (76500 - entry) * L3_SL
        assert abs(oco_call[1]["stop_price"] - expected_sl) < 100


def test_find_level_short():
    """find_level_and_sync_sl: SHORT, progress past L2 target -> returns 2."""
    executor, client = _make_executor()
    atr = 1000.0
    entry = 70000.0
    client.get_symbol_position.return_value = MarginPosition(
        "BTCUSDT", "BTC", "USDT", net_qty=-0.32, borrowed=0.32, free=0.0, locked=0.0
    )
    client.get_avg_entry_price.return_value = entry
    client.get_ticker_price.return_value = entry - 4.0 * atr
    orders = _make_oco_orders(symbol="BTCUSDT", exit_side="BUY", tp=65000, sl=entry)
    client.get_active_orders.return_value = orders

    trade_state = _make_trade_state("SHORT", entry, tp_price=65000, sl_price=entry)
    level = executor.find_level_and_sync_sl("BTCUSDT", trade_state)

    assert level == 2
    if client.place_oco_order.called:
        oco_call = client.place_oco_order.call_args
        expected_sl = entry - (entry - 65000) * L2_SL
        assert abs(oco_call[1]["stop_price"] - expected_sl) < 100


def test_find_level_cancel_fails_returns_next_level():
    """find_level: cancel fails -> returns next_level anyway (no sync, no crash)."""
    executor, client = _make_executor()
    atr = 1000.0
    entry = 70000.0
    client.get_symbol_position.return_value = MarginPosition(
        "BTCUSDT", "BTC", "USDT", net_qty=0.32, borrowed=0.0, free=0.32, locked=0.0
    )
    client.get_avg_entry_price.return_value = entry
    client.get_ticker_price.return_value = entry + 4.0 * atr
    # SL != entry -> needs sync, but cancel will fail
    orders = _make_oco_orders(symbol="BTCUSDT", exit_side="SELL", tp=75000, sl=71000)
    client.get_active_orders.return_value = orders
    client.cancel_all_symbol_orders.return_value = False

    trade_state = _make_trade_state("LONG", entry, tp_price=75000, sl_price=71000)
    level = executor.find_level_and_sync_sl("BTCUSDT", trade_state)

    assert level == 2
    client.place_oco_order.assert_not_called()


def test_daemon_qty_change_resets_level():
    """Daemon-level: qty changes -> level reset to None -> find_level re-initialized."""
    executor, client = _make_executor()
    atr = 1000.0
    entry = 70000.0

    # --- Pulse 1: L1 fires, daemon stores level=1 ---
    client.get_ticker_price.return_value = entry + 2.5 * atr
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
    result, level = executor.guardian_check("BTCUSDT", trade_state,
                                            current_level=0)
    assert level == 1

    # --- Simulate qty change: daemon detects level is stale ---
    client.cancel_all_symbol_orders.reset_mock()
    client.place_oco_order.reset_mock()
    client.execute_partial_market_close.reset_mock()

    client.get_symbol_position.side_effect = None
    client.get_symbol_position.return_value = MarginPosition(
        "BTCUSDT", "BTC", "USDT", net_qty=0.6, borrowed=0.0, free=0.6, locked=0.0
    )
    client.get_ticker_price.return_value = entry + 2.0 * atr
    orders2 = _make_oco_orders(symbol="BTCUSDT", exit_side="SELL", tp=75000, sl=entry)
    client.get_active_orders.return_value = orders2

    # Daemon would: reset level → call find_level_and_sync_sl
    find_level = executor.find_level_and_sync_sl("BTCUSDT", trade_state)
    assert find_level == 1

    # Pass the found level to guardian_check — should skip L1, not re-trigger it
    result, level = executor.guardian_check("BTCUSDT", trade_state,
                                            current_level=find_level)
    client.execute_partial_market_close.assert_not_called()
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
    client.get_ticker_price.return_value = entry + 2.5 * atr
    orders = _make_oco_orders(symbol="BTCUSDT", exit_side="SELL", tp=75000, sl=68000)
    client.get_active_orders.return_value = orders

    trade_state = _make_trade_state("LONG", entry, tp_price=75000, sl_price=68000)
    result, level = executor.guardian_check("BTCUSDT", trade_state,
                                            current_level=0)
    assert level == 1
    assert result

    # Now simulate position closed externally: net_qty=0, no OCO
    client.get_symbol_position.return_value = MarginPosition(
        "BTCUSDT", "BTC", "USDT", net_qty=0.0, borrowed=0.0, free=0.0, locked=0.0
    )
    client.get_active_orders.return_value = []

    result, level = executor.guardian_check("BTCUSDT", trade_state,
                                            current_level=1)
    assert result == {}
