import pytest
from scripts.calculate_qty import calculate_sized_qty
from src.utils.math_utils import effective_entry_delta

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


# ── Fee-adjusted sizing ──────────────────────────────────────────────

def test_fee_adjusted_reduces_qty():
    """With 0.1% taker fee, qty should be smaller than without."""
    equity, risk, entry, sl, p_qty = 1000, 0.01, 100, 99, 4

    _, final_no_fee = calculate_sized_qty(equity, risk, entry, sl, p_qty, taker_fee_rate=0.0)
    _, final_with_fee = calculate_sized_qty(equity, risk, entry, sl, p_qty, taker_fee_rate=0.001)

    assert final_no_fee == 10.0
    assert final_with_fee == 8.3333
    assert final_with_fee < final_no_fee


def test_fee_adjusted_total_loss_matches_budget():
    """Fee-adjusted qty: total loss (price + fee) at SL must equal max_loss."""
    equity, risk, entry, sl = 1000, 0.01, 100, 99
    taker_fee_rate = 0.001
    max_loss = equity * risk

    _, qty = calculate_sized_qty(equity, risk, entry, sl, 4, taker_fee_rate=taker_fee_rate)

    # When SL hit: effective_delta * qty ≈ max_loss (within rounding tolerance)
    total_loss = effective_entry_delta(entry, sl, taker_fee_rate) * qty
    assert abs(total_loss - max_loss) < 0.01


def test_fee_zero_equals_old_behavior():
    """taker_fee_rate=0 must produce identical result to the default."""
    args = (1000, 0.01, 100, 99, 4)
    _, final_default = calculate_sized_qty(*args)
    _, final_explicit = calculate_sized_qty(*args, taker_fee_rate=0.0)

    assert final_default == final_explicit == 10.0


def test_fee_adjusted_zero_delta_still_raises():
    """Zero SL delta raises ValueError regardless of fee rate."""
    import pytest
    with pytest.raises(ValueError, match="Stop loss distance is zero"):
        calculate_sized_qty(1000, 0.01, 100, 100, 4, taker_fee_rate=0.001)


def test_fee_adjusted_tight_sl_fee_dominates():
    """When SL is extremely tight, fee dominates the effective delta."""
    equity, risk, entry, sl = 1000, 0.01, 100, 99.9  # SL delta = 0.1

    _, qty = calculate_sized_qty(equity, risk, entry, sl, 4, taker_fee_rate=0.001)

    # effective_delta = 0.1 + 0.2 = 0.3
    # Without fee: qty = 10/0.1 = 100
    # With fee:    qty = 10/0.3 ≈ 33.33
    assert qty < 34  # fee more than halves the position size
