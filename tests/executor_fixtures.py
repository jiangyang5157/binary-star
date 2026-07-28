"""Shared fixtures for MarginOrderExecutor tests."""

from unittest.mock import MagicMock
from src.infrastructure.exchange.models import MarginPosition, MarginOrder, MarginAccountSummary
from src.agent.order_executor import MarginOrderExecutor


def make_executor(global_config=None):
    """Build a MarginOrderExecutor with all client methods mocked.

    Args:
        global_config: Optional config dict. If None, loads global_config.yaml
            from disk (same as production). Exit-ladder tests should pass a
            config that includes the expected level definitions.
    """
    client = MagicMock()
    client.get_cross_margin_account.return_value = MarginAccountSummary(
        0.1, 0.0, 0.1, 999.0, "NORMAL", []
    )
    client.get_ticker_price.return_value = 70000.0
    client.get_symbol_position.return_value = MarginPosition(
        "BTCUSDT", "BTC", "USDT", 0.0, 0.0, 0.0, 0.0
    )
    client.cancel_all_symbol_orders.return_value = True
    client.execute_market_close.return_value = True
    client.place_limit_order.return_value = 12345
    client.place_otoco_order.return_value = 12345
    client.place_oco_order.return_value = True
    client.cancel_order.return_value = True
    client.get_avg_entry_price.return_value = 70000.0
    client.execute_partial_market_close.side_effect = (
        lambda *args, **kwargs: (
            kwargs.get('qty') if 'qty' in kwargs else (args[2] if len(args) > 2 else 0.001)
        )
    )

    executor = MarginOrderExecutor(client=client, global_config=global_config)
    return executor, client
