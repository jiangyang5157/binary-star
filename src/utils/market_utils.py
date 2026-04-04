from typing import Dict, Any, Union

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
