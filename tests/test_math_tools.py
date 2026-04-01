import unittest
import sys
import os

# Setup paths (tests/ -> PROJECT_ROOT)
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.agent.tools.math_tools import MathTools

class TestMathTools(unittest.TestCase):
    def test_risk_reward_precision(self):
        # Case: Standard Bullish - Entry 60000, TP 63000, SL 58000
        # tp_dist = 3000, sl_dist = 2000, rr = 1.5
        res = MathTools.calculate_risk_reward(60000, 63000, 58000)
        self.assertEqual(res['rr_ratio'], 1.5)

        # Case: RR below 1.0
        res = MathTools.calculate_risk_reward(100, 110, 80)
        self.assertEqual(res['rr_ratio'], 0.5)

    def test_atr_metrics_standardization(self):
        # Case: Entry 100, SL 90, ATR 10 -> 1.0 ATR distance
        res = MathTools.calculate_atr_metrics(100, 90, 150, 10)
        self.assertEqual(res['entry_to_sl_atr'], 1.0)
        self.assertEqual(res['entry_to_tp_atr'], 5.0)

    def test_structural_proximity(self):
        # Case: SL 49500, ATR 100, POC 50000
        # (49500 - 50000) / 100 = -5.0 (Negative = SL is below anchor)
        res = MathTools.calculate_structural_proximity(49500, 100, poc=50000)
        self.assertEqual(res['sl_to_poc_atr'], -5.0)

    def test_projected_holding_time(self):
        # Case: TP dist 2000, ATR 200, Intensity 1.0, 1h macro (60 min)
        # effective_vel = 200 * 1.0 = 200 per macro candle
        # hours = (2000 / 200) * 1.0 = 10.0
        # Use explicit floor 0.5
        res = MathTools.project_holding_time(50000, 52000, 200, 1.0, 60, 0.5)
        self.assertEqual(res['projected_holding_hours'], 10.0)

if __name__ == '__main__':
    unittest.main()
