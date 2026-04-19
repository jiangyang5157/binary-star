import pytest
from calculate_qty import calculate_sized_qty

def test_calculate_sized_qty_standard():
    # Equity=1000, Risk=0.7%, Delta=600
    equity = 1000.0
    risk_pct = 0.007
    entry = 74450.0
    sl = 73850.0
    p_qty = 4
    
    target, final = calculate_sized_qty(equity, risk_pct, entry, sl, p_qty)
    
    # Max loss = 7.0
    # Qty = 7 / 600 = 0.011666...
    assert round(target, 8) == 0.01166667
    assert final == 0.0117

def test_calculate_sized_qty_min_clamp():
    # Very small risk/large delta results in Qty < min_qty
    equity = 100.0
    risk_pct = 0.001 # 0.1% = $0.1
    entry = 100000.0
    sl = 90000.0    # Delta = 10000
    p_qty = 4
    min_qty = 0.001
    
    # Target = 0.1 / 10000 = 0.00001
    target, final = calculate_sized_qty(equity, risk_pct, entry, sl, p_qty, min_qty)
    
    assert target == 0.00001
    assert final == 0.001 # Clamped to min_qty

def test_calculate_sized_qty_zero_delta():
    with pytest.raises(ValueError, match="Stop loss distance is zero"):
        calculate_sized_qty(1000, 0.01, 70000, 70000, 4)

def test_calculate_sized_qty_rounding():
    # Check rounding up/down
    # Target 0.01164 -> 0.0116 (if p_qty=4)
    target, final = calculate_sized_qty(11.64, 1.0, 1000, 0, 4) # loss=11.64, delta=1000 -> 0.01164
    assert final == 0.0116
    
    # Target 0.01165 -> 0.0117 (if p_qty=4)
    target, final = calculate_sized_qty(11.65, 1.0, 1000, 0, 4) # loss=11.65, delta=1000 -> 0.01165
    assert final == 0.0117
