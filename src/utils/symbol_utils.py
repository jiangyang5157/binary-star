"""Symbol resolution utilities.

All user-facing symbol inputs use the PREFIX format (e.g., "BTC").
These utilities append "USDT" at the outermost layer so internal
code always works with full symbols like "BTCUSDT".
"""


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

    if not symbol.endswith("USDT"):
        symbol = symbol + "USDT"

    return symbol


def resolve_symbols(raw: str) -> list[str]:
    """Resolve a CSV of symbol prefixes to a deduplicated list of full symbols.

    Args:
        raw: Comma-separated symbol prefixes (e.g., "BTC,ETH,XAUT").

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
