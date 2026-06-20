from typing import Dict, Any

def parse_liquidation_data(liq: Dict[str, Any]) -> Dict[str, Any]:
    """
    Unifies liquidation data format across different sources (REST vs WebSocket).
    
    Returns:
        Dict with keys: price (float), qty (float), side (str: BUY/SELL)
    """
    try:
        # Price: 'p' (WS) or 'price' (REST)
        price = float(liq.get('price') or liq.get('p', 0))
        
        # Quantity: 'q' (WS), 'qty' (REST), or 'origQty' (Execution)
        qty = float(liq.get('qty') or liq.get('q') or liq.get('origQty', 0))
        
        # Side: 'S' (WS) or 'side' (REST)
        side = str(liq.get('side') or liq.get('S', 'BUY')).upper()
        
        return {
            "price": price,
            "qty": qty,
            "side": side
        }
    except (ValueError, TypeError):
        return {"price": 0.0, "qty": 0.0, "side": "BUY"}

def calculate_indicator_warmup(
    iir_periods: list[int],
    fir_periods: list[int],
    multiplier: float = 5.0,   # industry standard: 5× longest IIR period
    extra_buffer: int = 2,
) -> int:
    """
    Calculates the required 'warmup' period to ensure technical indicators
    (IIR like EMA/ATR, and FIR like Windowed/Lookback) are stable.

    Args:
        iir_periods: List of periods for IIR indicators (e.g. [21, 50]).
        fir_periods: List of periods for FIR/Lookback indicators (e.g. [336]).
        multiplier: Multiplier for IIR convergence (default: 5.0).
        extra_buffer: Small additive safety buffer (default: 2).

    Returns:
        The total warmup candle count (int).
    """
    max_iir = max(iir_periods) if iir_periods else 0
    max_fir = max(fir_periods) if fir_periods else 0
    return int(max(max_iir * multiplier, max_fir) + extra_buffer)
