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
        # Full Configuration from strategy_config.yaml (Thresholds + Modifiers)
        cfg = {
            "dilation_dead_water": 3.0, "dilation_highway": 1.1, "dilation_climax": 2.0, "dilation_standard": 1.5
        }
        # Thresholds (Moved to positional to match hardened signature if needed, or kept in kwargs)
        thresholds = {
            "vr_base": 1.3, "vr_extreme": 2.0, "ti_strong": 0.5, "ti_thresh": 0.95
        }

        # 1. 场景：极度高潮 (Chaos) - VR 2.2 (>= 2.0)
        # Expected: Dist 2000 / (ATR 200 * Velocity 1.0) = 10 candles.
        # Modifier 2.0. Hours = 10 * 60 * 2.0 / 60 = 20.0
        res = MathTools.project_holding_time(
            current_price=60000, entry=50000, take_profit=52000, atr=200, 
            trend_intensity=1.0, volatility_intensity_index=2.2, normalized_velocity=1.0, 
            interval_minutes=60, min_velocity_floor=0.5, **cfg, **thresholds
        )
        assert res['temporal_dilation_factor'] == 2.0
        assert res['projected_holding_hours'] == 20.0

        # 2. 场景：死水区 (Dead Water) - VR 1.0 (< 1.3), TI 0.2 (< 0.5)
        # Expected: Dist 2000 / (ATR 200 * Floor 0.5) = 20 candles. 
        # Modifier 3.0. Hours = 20 * 60 * 3.0 / 60 = 60.0
        res = MathTools.project_holding_time(
            current_price=60000, entry=50000, take_profit=52000, atr=200, 
            trend_intensity=0.2, volatility_intensity_index=1.0, normalized_velocity=0.2, 
            interval_minutes=60, min_velocity_floor=0.5, **cfg, **thresholds
        )
        assert res['temporal_dilation_factor'] == 3.0
        assert res['projected_holding_hours'] == 60.0
        
        # 3. 场景：高速公路 (Highway) - TI 0.96 (>= 0.95), VR 1.5 (1.3 <= 1.5 < 2.0)
        # Expected: Dist 2000 / (ATR 200 * Velocity 0.96) = 2000 / 192 = 10.416 candles.
        # Modifier 1.1. Hours = 10.416 * 60 * 1.1 / 60 = 11.458 -> 11.5
        res = MathTools.project_holding_time(
            current_price=60000, entry=50000, take_profit=52000, atr=200, 
            trend_intensity=0.96, volatility_intensity_index=1.5, normalized_velocity=0.96, 
            interval_minutes=60, min_velocity_floor=0.5, **cfg, **thresholds
        )
        assert res['temporal_dilation_factor'] == 1.1
        assert res['projected_holding_hours'] == 11.5

        # 4. 场景：标准扩张 (Standard) - VR 1.5, TI 0.6 (不满足 Highway 和 Dead Water)
        # Expected: Dist 2000 / (ATR 200 * Velocity 0.6) = 2000 / 120 = 16.666 candles.
        # Modifier 1.5. Hours = 16.666 * 60 * 1.5 / 60 = 25.0
        res = MathTools.project_holding_time(
            current_price=60000, entry=50000, take_profit=52000, atr=200, 
            trend_intensity=0.6, volatility_intensity_index=1.5, normalized_velocity=0.6, 
            interval_minutes=60, min_velocity_floor=0.5, **cfg, **thresholds
        )
        assert res['temporal_dilation_factor'] == 1.5
        assert res['projected_holding_hours'] == 25.0

        # 5. 等待时间校验 (Wait time test)
        # current_price=59000, entry=60000, TP=62000. Dist=1000. ATR=200. Velocity=1.0.
        # Expected: 1000 / (200 * 1.0) = 5 candles = 5 hours (at 60m interval).
        res_wait = MathTools.project_holding_time(
            current_price=59000, entry=60000, take_profit=62000, atr=200, 
            trend_intensity=1.0, volatility_intensity_index=2.2, normalized_velocity=1.0, 
            interval_minutes=60, min_velocity_floor=0.5, **cfg, **thresholds
        )
        assert res_wait['projected_waiting_hours'] == 5.0

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
