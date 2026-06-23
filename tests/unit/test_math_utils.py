import pytest
from src.utils.math_utils import MathTools, RegimePhysicsConfig

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

    # Shared config for projected_holding_time tests
    _physics = RegimePhysicsConfig(
        min_velocity_floor=0.5,
        ti_thresh=0.95, ti_strong=0.5, vr_base=1.3, vr_extreme=2.0,
        dilation_dead_water=3.0, dilation_highway=1.1, dilation_climax=2.0, dilation_standard=1.5,
        weight_dead_water=0.5, weight_highway=2.0, weight_climax=0.25, weight_standard=1.0,
    )

    def _call_holding_time(self, entry, tp, trend, vol_idx, velocity, atr=200, interval=60):
        return MathTools.project_holding_time(
            current_price=60000, entry=entry, take_profit=tp, atr=atr,
            trend_intensity=trend, volatility_intensity_index=vol_idx,
            normalized_velocity=velocity, interval_minutes=interval,
            physics=self._physics,
        )

    def test_projected_holding_climax(self):
        """Chaos regime: VR 2.2, weight 0.25, dilation 2.0 → 20 hours."""
        res = self._call_holding_time(50000, 52000, 1.0, 2.2, 1.0)
        assert res["temporal_weight_factor"] == 0.25
        assert res["projected_holding_hours"] == 20.0

    def test_projected_holding_dead_water(self):
        """Dead water: VR 1.0, TI 0.2, floor 0.5, weight 0.5, dilation 3.0 → 60h."""
        res = self._call_holding_time(50000, 52000, 0.2, 1.0, 0.2)
        assert res["temporal_weight_factor"] == 0.5
        assert res["projected_holding_hours"] == 60.0

    def test_projected_holding_highway(self):
        """Highway: TI 0.96, VR 1.5, weight 2.0, dilation 1.1 → 11.5h."""
        res = self._call_holding_time(50000, 52000, 0.96, 1.5, 0.96)
        assert res["temporal_weight_factor"] == 2.0
        assert res["projected_holding_hours"] == 11.5

    def test_projected_holding_standard(self):
        """Standard expansion: TI 0.6, VR 1.5, weight 1.0, dilation 1.5 → 25h."""
        res = self._call_holding_time(50000, 52000, 0.6, 1.5, 0.6)
        assert res["temporal_weight_factor"] == 1.0
        assert res["projected_holding_hours"] == 25.0

    def test_projected_waiting_time(self):
        """Wait time: entry=60000, TP=62000, dist=1000, vel=1.0 → 5h."""
        res = MathTools.project_holding_time(
            current_price=59000, entry=60000, take_profit=62000, atr=200,
            trend_intensity=1.0, volatility_intensity_index=2.2,
            normalized_velocity=1.0, interval_minutes=60,
            physics=self._physics,
        )
        assert res["projected_waiting_hours"] == 5.0

    def test_mae_stress_tiers(self):
        # 定义测试用的阈值
        pinpoint, standard, luck = 15.0, 50.0, 80.0
        
        # PINPOINT (MAE 10, ATR 100 => 10%)
        res = MathTools.calculate_mae_stress(10, 100, pinpoint, standard, luck)
        assert res['stress_tier'] == "PINPOINT"
        
        # LUCK (MAE 75, ATR 100 => 75%)
        res = MathTools.calculate_mae_stress(75, 100, pinpoint, standard, luck)
        assert res['stress_tier'] == "LUCK"

        # LOGIC_FAILURE (MAE 90, ATR 100 => 90%)
        res = MathTools.calculate_mae_stress(90, 100, pinpoint, standard, luck)
        assert res['stress_tier'] == "LOGIC_FAILURE"

    def test_opportunity_cost(self):
        # 正常踏空 (Miss 1.5, ATR 1.0 => 1.5 < 2.0)
        res = MathTools.calculate_opportunity_cost(1.5, 1.0, 2.0)
        assert res['is_catastrophic_miss'] is False
        
        # 灾难性踏空 (Miss 2.5, ATR 1.0 => 2.5 > 2.0)
        res = MathTools.calculate_opportunity_cost(2.5, 1.0, 2.0)
        assert res['is_catastrophic_miss'] is True
