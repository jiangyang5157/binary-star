import unittest
import os
import sys

# Setup paths
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
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
            [0, 101.0, 111.0, 100.0, 110.5], # TP hit at 111.0
        ]
        result = OutcomeCalculator.calculate(klines, 100.0, self.strategy_bullish, atr=2.0, interval_hours=1)
        self.assertEqual(result["trade_execution_metrics"]["tp_sl_result"], "TP_HIT")
        self.assertEqual(result["trade_execution_metrics"]["mfe_efficiency"], "110.0%")

    def test_bullish_sl_hit(self):
        klines = [
            [0, 100.0, 101.0, 99.0, 100.0], # Entry hit
            [0, 100.0, 101.0, 94.0, 95.0], # SL hit at 94.0
        ]
        result = OutcomeCalculator.calculate(klines, 100.0, self.strategy_bullish, atr=2.0)
        self.assertEqual(result["trade_execution_metrics"]["tp_sl_result"], "SL_HIT")

    def test_bearish_tp_hit(self):
        klines = [
            [0, 99.5, 100.5, 99.0, 100.0], # Entry hit at 100.5
            [0, 100.0, 101.0, 89.0, 90.0], # TP hit at 89.0
        ]
        result = OutcomeCalculator.calculate(klines, 100.0, self.strategy_bearish, atr=2.0)
        self.assertEqual(result["trade_execution_metrics"]["tp_sl_result"], "TP_HIT")

    def test_neither_hit(self):
        klines = [
            [0, 100.0, 102.0, 98.0, 101.0], # Entry hit
        ]
        result = OutcomeCalculator.calculate(klines, 100.0, self.strategy_bullish, atr=2.0)
        self.assertEqual(result["trade_execution_metrics"]["tp_sl_result"], "NEITHER")

if __name__ == '__main__':
    unittest.main()
