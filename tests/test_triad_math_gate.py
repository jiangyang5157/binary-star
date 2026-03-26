import unittest
import os
import sys

# Setup paths
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from strategist import calculate_math_fact_check

class TestTriadMathGate(unittest.TestCase):
    def setUp(self):
        self.observation = {
            "quantitative_metrics": {
                "price_dynamics": {
                    "atr_macro": 500.0
                }
            }
        }
        self.draft = {
            "limit_order": {
                "entry": 70000.0,
                "take_profit": 71500.0,
                "stop_loss": 69750.0
            }
        }

    def test_calculate_math_fact_check_success(self):
        result = calculate_math_fact_check(self.observation, self.draft)
        self.assertIsNotNone(result)
        # sl_dist = 70000 - 69750 = 250
        # tp_dist = 71500 - 70000 = 1500
        # actual_rr = 1500 / 250 = 6.0
        # sl_atr_distance = 250 / 500 = 0.5
        # projected_holding_hours = 1500 / 500 = 3.0
        self.assertEqual(result["actual_rr"], 6.0)
        self.assertEqual(result["sl_atr_distance"], 0.5)
        self.assertEqual(result["projected_holding_hours"], 3.0)

    def test_calculate_math_fact_check_missing_limit_order(self):
        draft = {}
        result = calculate_math_fact_check(self.observation, draft)
        self.assertIsNone(result)

    def test_calculate_math_fact_check_incomplete_limit_order(self):
        draft = {
            "limit_order": {
                "entry": 70000.0
                # missing tp, sl
            }
        }
        result = calculate_math_fact_check(self.observation, draft)
        self.assertIsNone(result)

    def test_calculate_math_fact_check_zero_atr(self):
        obs = {
            "quantitative_metrics": {
                "price_dynamics": {
                    "atr_macro": 0.0
                }
            }
        }
        result = calculate_math_fact_check(obs, self.draft)
        self.assertIsNotNone(result)
        self.assertEqual(result["sl_atr_distance"], 0)
        self.assertEqual(result["projected_holding_hours"], 0)

    def test_calculate_math_fact_check_zero_sl_dist(self):
        draft = {
            "limit_order": {
                "entry": 70000.0,
                "take_profit": 71500.0,
                "stop_loss": 70000.0
            }
        }
        result = calculate_math_fact_check(self.observation, draft)
        self.assertIsNotNone(result)
        self.assertEqual(result["actual_rr"], 0)

    def test_calculate_math_fact_check_invalid_types(self):
        draft = {
            "limit_order": {
                "entry": "invalid",
                "take_profit": 71500.0,
                "stop_loss": 69750.0
            }
        }
        result = calculate_math_fact_check(self.observation, draft)
        self.assertIsNone(result)

if __name__ == '__main__':
    unittest.main()
