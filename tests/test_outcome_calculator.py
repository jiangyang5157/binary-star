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
        klines = [
            [0, 100.5, 101.0, 99.5, 100.0],
            [0, 100.0, 102.0, 99.0, 101.0],
            [0, 101.0, 111.0, 100.0, 110.5],
        ]
        result = OutcomeCalculator.calculate(klines, 100.0, self.strategy_bullish, atr_macro_t0=5.0, atr_macro_t1=5.0, interval_hours=1)
        
        # Check Top-level Conclusion
        self.assertEqual(result["tp_sl_result"], "TP_HIT")
        self.assertEqual(result["highest_reached_price"], 111.0)
        self.assertEqual(result["lowest_reached_price"], 99.0)
        self.assertEqual(result["total_price_change_pct"], 10.5)
        
        context = result["market_context"]
        self.assertEqual(context["audit_duration_candles"], 3)
        self.assertEqual(context["max_atr_used"], 5.0)

        metrics = result["trade_execution_metrics"]
        self.assertEqual(metrics["mfe_efficiency"], "110.0%")
        self.assertEqual(metrics["mae_atr_ratio"], 0.2)
        self.assertEqual(metrics["mae_stress_level"], "20.0%")

    def test_bullish_sl_hit(self):
        klines = [
            [0, 100.0, 101.0, 99.0, 100.0],
            [0, 100.0, 101.0, 94.0, 95.0],
        ]
        result = OutcomeCalculator.calculate(klines, 100.0, self.strategy_bullish, atr_macro_t0=5.0, atr_macro_t1=5.0)
        self.assertEqual(result["tp_sl_result"], "SL_HIT")
        metrics = result["trade_execution_metrics"]
        self.assertEqual(metrics["mae_stress_level"], "120.0%")
        self.assertEqual(metrics["mae_atr_ratio"], 1.2)

    def test_bearish_tp_hit(self):
        klines = [
            [0, 99.5, 100.5, 99.0, 100.0],
            [0, 100.0, 101.0, 89.0, 90.0],
        ]
        result = OutcomeCalculator.calculate(klines, 100.0, self.strategy_bearish, atr_macro_t0=5.0, atr_macro_t1=5.0)
        self.assertEqual(result["tp_sl_result"], "TP_HIT")
        metrics = result["trade_execution_metrics"]
        self.assertEqual(metrics["mfe_efficiency"], "110.0%")
        self.assertEqual(metrics["mae_atr_ratio"], 0.2)
        self.assertEqual(metrics["mae_stress_level"], "20.0%")

    def test_neither_hit_entry_was_active(self):
        klines = [
            [0, 100.0, 102.0, 98.0, 101.0],
        ]
        result = OutcomeCalculator.calculate(klines, 100.0, self.strategy_bullish, atr_macro_t0=5.0, atr_macro_t1=5.0)
        self.assertEqual(result["tp_sl_result"], "NEITHER")
        metrics = result["trade_execution_metrics"]
        self.assertEqual(metrics["mae_atr_ratio"], 0.4)

    def test_temporal_efficiency_long_window_early_hit(self):
        klines = [
            [0, 100.0, 101.0, 99.0, 100.5],
            [0, 100.5, 115.0, 100.0, 110.0],
            [0, 110.0, 112.0, 108.0, 111.0],
            [0, 111.0, 113.0, 109.0, 112.0],
            [0, 112.0, 114.0, 110.0, 113.0],
        ]
        strategy = {
            "opinion": "BULLISH",
            "limit_order": {
                "entry": 100.0,
                "take_profit": 110.0,
                "stop_loss": 90.0,
                "holding_time_hours": 10
            }
        }
        result = OutcomeCalculator.calculate(klines, 100.0, strategy, atr_macro_t0=5.0, atr_macro_t1=5.0, interval_hours=1)
        self.assertEqual(result["tp_sl_result"], "TP_HIT")
        metrics = result["trade_execution_metrics"]
        self.assertEqual(metrics["duration_candles"], 2)
        self.assertEqual(metrics["actual_hours"], 2.0)
        self.assertEqual(metrics["time_efficiency_multiplier"], 0.2)

    def test_no_entry_hit(self):
        klines = [
            [0, 101.0, 102.0, 100.5, 101.5],
        ]
        result = OutcomeCalculator.calculate(klines, 100.0, self.strategy_bullish, atr_macro_t0=5.0, atr_macro_t1=5.0, interval_hours=1)
        self.assertEqual(result["tp_sl_result"], "NEITHER")
        metrics = result["trade_execution_metrics"]
        market_context = result["market_context"]
        
        self.assertIsNone(result["highest_reached_price"])
        self.assertIsNone(result["lowest_reached_price"])
        self.assertIsNone(result["total_price_change_pct"])
        self.assertEqual(market_context["missed_relative_range"], 0.3)
        self.assertEqual(market_context["highest_reached_at_t1"], 102.0)
        self.assertEqual(metrics["duration_candles"], 1)

if __name__ == '__main__':
    unittest.main()
