import pytest
from src.utils.math_utils import MathTools

class TestMathTools:
    
    @pytest.mark.parametrize("entry, tp, sl, expected_rr", [
        (60000, 63000, 58000, 1.5),   # 正常看涨
        (60000, 57000, 62000, 1.5),   # 正常看跌
        (100, 110, 80, 0.5),          # 低 RR
        (100, 100.1, 99.9, 1.0),      # 微小波动
    ])
    def test_risk_reward_precision(self, entry, tp, sl, expected_rr):
        res = MathTools.calculate_risk_reward(entry, tp, sl)
        assert res['rr_ratio'] == expected_rr
        assert 'error' not in res

    def test_risk_reward_edge_cases(self):
        # 零止损距离
        res = MathTools.calculate_risk_reward(100, 110, 100)
        assert res['rr_ratio'] == 0.0
        assert 'warning' in res

        # 负价格输入
        res = MathTools.calculate_risk_reward(-100, 110, 90)
        assert 'error' in res

    @pytest.mark.parametrize("entry, sl, tp, atr, expected_sl_atr", [
        (100, 90, 150, 10, 1.0),
        (100, 95, 110, 2.5, 2.0),
    ])
    def test_atr_metrics_standardization(self, entry, sl, tp, atr, expected_sl_atr):
        res = MathTools.calculate_atr_metrics(entry, sl, tp, atr)
        assert res['entry_to_sl_atr'] == expected_sl_atr
        assert 'error' not in res

    def test_atr_metrics_invalid_atr(self):
        # ATR <= 0
        res = MathTools.calculate_atr_metrics(100, 90, 110, 0)
        assert 'error' in res
        res = MathTools.calculate_atr_metrics(100, 90, 110, -5)
        assert 'error' in res

    def test_structural_proximity(self):
        # 正常情况
        res = MathTools.calculate_structural_proximity(49500, 100, poc=50000)
        assert res['sl_to_poc_atr'] == -5.0
        
        # 锚点不存在
        res = MathTools.calculate_structural_proximity(49500, 100, poc=None)
        assert res['sl_to_poc_atr'] is None

    def test_projected_holding_time(self):
        # 正常情况: 距离 2000, 速度 200 (ATR 200 * Intensity 1.0), 60min interval, modifier 1.0
        res = MathTools.project_holding_time(50000, 52000, 200, 1.0, 60, 0.5, 1.0)
        assert res['projected_holding_hours'] == 10.0
        
        # 极低速度触发 Floor (Velocity 200 * Floor 0.5 = 100)
        res = MathTools.project_holding_time(50000, 52000, 200, 0.1, 60, 0.5, 1.0)
        assert res['effective_velocity_per_candle'] == 100.0
        assert res['projected_holding_hours'] == 20.0

    def test_mae_stress_tiers(self):
        # 定义测试用的阈值
        t = {"pinpoint": 15.0, "standard": 50.0, "luck": 80.0}
        
        # PINPOINT (MAE 10, ATR 100 => 10%)
        res = MathTools.calculate_mae_stress(10, 100, t)
        assert res['stress_tier'] == "PINPOINT"
        
        # LUCK (MAE 75, ATR 100 => 75%)
        res = MathTools.calculate_mae_stress(75, 100, t)
        assert res['stress_tier'] == "LUCK"

        # LOGIC_FAILURE (MAE 90, ATR 100 => 90%)
        res = MathTools.calculate_mae_stress(90, 100, t)
        assert res['stress_tier'] == "LOGIC_FAILURE"

    def test_opportunity_cost(self):
        # 正常踏空 (Miss 1.5, ATR 1.0 => 1.5 < 2.0)
        res = MathTools.calculate_opportunity_cost(1.5, 1.0, 2.0)
        assert res['is_catastrophic_miss'] is False
        
        # 灾难性踏空 (Miss 2.5, ATR 1.0 => 2.5 > 2.0)
        res = MathTools.calculate_opportunity_cost(2.5, 1.0, 2.0)
        assert res['is_catastrophic_miss'] is True
