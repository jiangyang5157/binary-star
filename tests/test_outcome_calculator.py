import unittest
import os
import sys

# Setup paths
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from reviewer import OutcomeCalculator

class TestOutcomeCalculator(unittest.TestCase):
    def setUp(self):
        self.strategy_bullish = {
            "opinion": "BULLISH",
            "limit_order": {
                "entry": 100.0,
                "take_profit": 110.0,
                "stop_loss": 95.0,
                "holding_time_hours": 24
            }
        }
        self.strategy_bearish = {
            "opinion": "BEARISH",
            "limit_order": {
                "entry": 100.0,
                "take_profit": 90.0,
                "stop_loss": 105.0,
                "holding_time_hours": 24
            }
        }

    def test_empty_klines(self):
        result = OutcomeCalculator.calculate([], 100.0, self.strategy_bullish)
        self.assertEqual(result, {})

    def test_bullish_tp_hit(self):
        # [OpenTime, Open, High, Low, Close, Volume, CloseTime]
        klines = [
            [0, 100.5, 101.0, 99.5, 100.0], # No entry hit yet
            [0, 100.0, 102.0, 99.0, 101.0], # Entry hit at 99.0
            [0, 101.0, 111.0, 100.0, 110.5], # TP hit at 111.0 (limit 110.0)
        ]
        result = OutcomeCalculator.calculate(klines, 100.0, self.strategy_bullish, atr=5.0, interval_hours=1)
        metrics = result["trade_execution_metrics"]
        self.assertEqual(metrics["tp_sl_result"], "TP_HIT")
        self.assertEqual(metrics["mfe_efficiency"], "110.0%")
        self.assertEqual(metrics["mae_atr_ratio"], 0.2) # (100 - 99) / 5.0 = 0.2
        self.assertEqual(metrics["mae_stress_level"], "20.0%") # (100 - 99) / (100 - 95) * 100 = 1 / 5 * 100 = 20%
        self.assertEqual(metrics["time_efficiency_multiplier"], 0.12) # (3 candles * 1h) / 24h = 0.125 -> 0.12?
        # actual_hours = 3 * 1 = 3. time_multiplier = round(3 / 24, 2) = 0.12.

    def test_bullish_sl_hit(self):
        klines = [
            [0, 100.0, 101.0, 99.0, 100.0], # Entry hit
            [0, 100.0, 101.0, 94.0, 95.0], # SL hit at 94.0
        ]
        result = OutcomeCalculator.calculate(klines, 100.0, self.strategy_bullish, atr=5.0)
        metrics = result["trade_execution_metrics"]
        self.assertEqual(metrics["tp_sl_result"], "SL_HIT")
        self.assertEqual(metrics["mae_stress_level"], "120.0%") # (100 - 94) / (100 - 95) * 100 = 6 / 5 * 100 = 120%
        self.assertEqual(metrics["mae_atr_ratio"], 1.2) # (100 - 94) / 5.0 = 1.2

    def test_bearish_tp_hit(self):
        klines = [
            [0, 99.5, 100.5, 99.0, 100.0], # Entry hit at 100.5
            [0, 100.0, 101.0, 89.0, 90.0], # TP hit at 89.0
        ]
        result = OutcomeCalculator.calculate(klines, 100.0, self.strategy_bearish, atr=5.0)
        metrics = result["trade_execution_metrics"]
        self.assertEqual(metrics["tp_sl_result"], "TP_HIT")
        self.assertEqual(metrics["mfe_efficiency"], "110.0%") # (100 - 89) / (100 - 90) = 11 / 10 = 1.1 -> 110%
        self.assertEqual(metrics["mae_atr_ratio"], 0.2) # (101 - 100) / 5.0 = 1.0 / 5 = 0.2
        self.assertEqual(metrics["mae_stress_level"], "20.0%") # 1.0 / (105 - 100) = 1.0 / 5 = 20%

    def test_neither_hit_entry_was_active(self):
        klines = [
            [0, 100.0, 102.0, 98.0, 101.0], # Entry hit at 100.0, then stays between 98.0 and 102.0
        ]
        result = OutcomeCalculator.calculate(klines, 100.0, self.strategy_bullish, atr=5.0)
        metrics = result["trade_execution_metrics"]
        self.assertEqual(metrics["tp_sl_result"], "NEITHER")
        self.assertTrue("mae_atr_ratio" in metrics) # Entry hit means MAE is calculated
        self.assertEqual(metrics["mae_atr_ratio"], 0.4) # (100 - 98) / 5.0 = 0.4

    def test_temporal_efficiency_long_window_early_hit(self):
        # 10 candles, but TP hit on candle 2
        klines = [
            [0, 100.0, 101.0, 99.0, 100.5], # Candle 1: Entry
            [0, 100.5, 115.0, 100.0, 110.0], # Candle 2: TP hit!
            [0, 110.0, 112.0, 108.0, 111.0], # Candle 3
            [0, 111.0, 113.0, 109.0, 112.0], # Candle 4
            [0, 112.0, 114.0, 110.0, 113.0], # Candle 5
        ]
        # Prediction: 10 hours. Interval: 1h.
        # Old logic: 5 candles * 1h = 5h. Multiplier = 5 / 10 = 0.5
        # New logic: 2 candles * 1h = 2h. Multiplier = 2 / 10 = 0.2
        strategy = {
            "opinion": "BULLISH",
            "limit_order": {
                "entry": 100.0,
                "take_profit": 110.0,
                "stop_loss": 90.0,
                "holding_time_hours": 10
            }
        }
        result = OutcomeCalculator.calculate(klines, 100.0, strategy, atr=5.0, interval_hours=1)
        metrics = result["trade_execution_metrics"]
        self.assertEqual(metrics["duration_candles"], 2)
        self.assertEqual(metrics["actual_hours"], 2.0)
        self.assertEqual(metrics["time_efficiency_multiplier"], 0.2)

    def test_no_entry_hit(self):
        klines = [
            [0, 101.0, 102.0, 100.5, 101.5], # High and Low > 100.0
        ]
        result = OutcomeCalculator.calculate(klines, 100.0, self.strategy_bullish, atr=5.0)
        metrics = result["trade_execution_metrics"]
        vol_analysis = result["volatility_analysis"]
        self.assertEqual(metrics["tp_sl_result"], "NEITHER")
        # missed_range = 102 - 100.5 = 1.5. rel_range = 1.5 / 5 = 0.3
        self.assertEqual(vol_analysis["missed_relative_range"], 0.3)

if __name__ == '__main__':
    unittest.main()
