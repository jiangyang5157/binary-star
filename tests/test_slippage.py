import pytest
from src.utils.math_utils import MathTools

def test_calculate_liquidity_slippage_basic():
    # Mock volume profile
    profile = [
        {"price": 100, "volume": 1000},
        {"price": 110, "volume": 500},
        {"price": 120, "volume": 100}
    ]
    
    # 1. 处于高成交量区 (Price 100, Quality 1.0)
    # base_slippage=5, max_slippage=50 => expected total slippage = 5
    res = MathTools.calculate_liquidity_slippage(100, profile, 10, 5.0, 50.0)
    assert res['slippage_bps'] == 5.0
    assert res['price_adjusted'] == 100.05 # 100 * (1 + 5/10000)
    
    # 2. 处于成交真空区 (Price 120, Quality 0.1)
    # liquidity_quality = 100/1000 = 0.1
    # extra_slippage = (1 - 0.1) * (50 - 5) = 0.9 * 45 = 40.5
    # total = 5 + 40.5 = 45.5
    res = MathTools.calculate_liquidity_slippage(120, profile, 10, 5.0, 50.0)
    assert res['slippage_bps'] == 45.5
    assert res['is_vacuum_zone'] == False # threshold is < 0.1
    
    # 3. 价格在两个桶之间
    res = MathTools.calculate_liquidity_slippage(105, profile, 10, 5.0, 50.0)
    # 距离 100 最近
    assert res['slippage_bps'] == 5.0
