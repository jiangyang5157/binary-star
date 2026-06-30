"""Symbol resolution utilities.

All user-facing symbol inputs use the PREFIX format (e.g., "BTC").
These utilities append the configured quote currency at the outermost layer
so internal code always works with full symbols like "BTCUSDT".

The quote currency is read from global_config.yaml → trade_management.quote_currency.
"""

from functools import lru_cache


@lru_cache(maxsize=1)
def get_quote_currency() -> str:
    """Return the quote currency from global_config.yaml (cached).

    Defaults to "USDT" if the config key is missing.
    """
    from src.utils.path_utils import resolve_project_root
    import os
    import yaml

    config_path = os.path.join(resolve_project_root(), "config", "global_config.yaml")
    try:
        with open(config_path, 'r') as f:
            cfg = yaml.safe_load(f)
        return str(cfg.get("trade_management", {}).get("quote_currency", "USDT"))
    except Exception:
        return "USDT"


def resolve_symbol(raw: str) -> str:
    """Resolve a single symbol prefix to its full form.

    Args:
        raw: Symbol prefix (e.g., "BTC") or full symbol (e.g., "BTCUSDT").

    Returns:
        Full symbol string (e.g., "BTCUSDT").

    Raises:
        ValueError: If the symbol is empty, too short, or non-alphanumeric.
    """
    symbol = raw.strip().upper()

    if len(symbol) < 2:
        raise ValueError(f"Symbol must be at least 2 characters, got: {repr(raw)}")

    if not symbol.isalnum():
        raise ValueError(f"Symbol must be alphanumeric, got: {repr(raw)}")

    quote = get_quote_currency()
    if not symbol.endswith(quote):
        symbol = symbol + quote

    return symbol


def resolve_symbols(raw: str) -> list[str]:
    """Resolve a CSV of symbol prefixes to a deduplicated list of full symbols.

    Args:
        raw: Comma-separated symbol prefixes (e.g., "BTC,XAUT").

    Returns:
        List of full symbol strings in original order, with duplicates removed.

    Raises:
        ValueError: If no valid symbols are provided, or any symbol is invalid.
    """
    parts = [p.strip() for p in raw.split(",") if p.strip()]

    if not parts:
        raise ValueError("At least one symbol required")

    seen: set[str] = set()
    result: list[str] = []

    for p in parts:
        symbol = resolve_symbol(p)
        if symbol not in seen:
            seen.add(symbol)
            result.append(symbol)

    return result
