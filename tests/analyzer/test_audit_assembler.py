import unittest
import sys
import os
from typing import Dict, Any

# Setup paths
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.analyzer.audit_assembler import AuditAssembler, AuditReviewConfig
from tests.mock_factory import MockDataFactory

class TestAuditAssembler(unittest.TestCase):
    def setUp(self):
        self.config = {
            "analysis_window": {"macro_context": {"time_interval": "1h"}, "micro_context": {"time_interval": "15m"}},
            "topography_parameters": {},
            "regime_parameters": {"anchor_drift_threshold": 0.5},
            "audit_review": {
                "mae_stress_tolerance": 0.5,
                "atr_period": 14
            },
            "strategy_intent": "TEST"
        }
        self.rev_cfg = AuditReviewConfig.from_dict(self.config)
        self.assembler = AuditAssembler(self.rev_cfg)

    def test_calculate_outcome_tp_hit(self):
        # Scenario: Bullish trade, price goes up and hits TP
        # Entry 60000, TP 62000, SL 59000
        strategy = {
            "final_decision": {
                "opinion": "BULLISH",
                "tactical_parameters": {"entry": 60000, "take_profit": 62000, "stop_loss": 59000}
            }
        }
        
        # Open, High, Low, Close
        klines = [
            [0, 60000, 60500, 59900, 60200], # Entry hit (Low 59900 <= 60000)
            [0, 60200, 61000, 60100, 60800],
            [0, 60800, 62500, 60700, 62100], # TP hit (High 62500 >= 62000)
        ]
        
        outcome = self.assembler.calculate_outcome(klines, 60000, strategy, atr_macro_t0=500)
        
        self.assertTrue(outcome["is_filled"])
        self.assertEqual(outcome["tp_sl_result"], "TP_HIT")
        self.assertLess(outcome["trade_execution_metrics"]["mae_stress_level_pct"], 100)

    def test_calculate_outcome_sl_hit(self):
        # Scenario: Bullish trade, price goes down and hits SL
        strategy = {
            "final_decision": {
                "opinion": "BULLISH",
                "tactical_parameters": {"entry": 60000, "take_profit": 62000, "stop_loss": 59000}
            }
        }
        
        klines = [
            [0, 60000, 60100, 59900, 59950], # Entry hit
            [0, 59950, 60000, 58000, 58500], # SL hit (Low 58000 <= 59000)
        ]
        
        outcome = self.assembler.calculate_outcome(klines, 60000, strategy, atr_macro_t0=500)
        
        self.assertTrue(outcome["is_filled"])
        self.assertEqual(outcome["tp_sl_result"], "SL_HIT")

    def test_opportunity_cost_neutral_paradox(self):
        # Scenario: Agent chose NEUTRAL, but price moved 3 ATRs
        strategy = {
            "final_decision": {"opinion": "NEUTRAL"},
            "observation": {
                "quantitative_metrics": {
                    "volume_profile": {"poc": 60000} # Structural data was available
                }
            }
        }
        
        # Outcome has high missed range
        outcome = {
            "market_context": {"is_catastrophic_miss": True}
        }
        
        report = self.assembler.review(strategy, outcome)
        
        self.assertFalse(report["audit_status"]["is_justified_surrender"])
        self.assertEqual(report["audit_status"]["data_availability_at_t0"], "HIGH")

if __name__ == '__main__':
    unittest.main()
