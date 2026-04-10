import unittest
import sys
import os
from typing import Dict, Any

# Setup paths
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.analyzer.audit_assembler import AuditAssembler, AuditReviewConfig
from src.infrastructure.exchange.models import KlineData
from tests.mock_factory import MockDataFactory

class TestAuditAssembler(unittest.TestCase):
    def setUp(self):
        self.config = {
            "analysis_window": {"macro_context": {"time_interval": "1h"}, "micro_context": {"time_interval": "15m"}},
            "topography_parameters": {},
            "regime_parameters": {"anchor_drift_threshold": 0.5},
            "audit_review": {
                "forensic_resolution": "1m",
                "mae_stress_tolerance": 0.5,
                "atr_period": 14,
                "missed_opportunity_atr_threshold": 2.0,
                "unfilled_proximity_atr_limit": 0.1,
                "catastrophic_miss_atr_threshold": 3.0,
                "mae_stress_thresholds": {
                    "pinpoint": 15.0,
                    "standard": 50.0,
                    "luck": 80.0
                },
                "base_slippage_bps": 5.0,
                "max_slippage_bps": 50.0
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
        # klines now expected as KlineData objects
        klines = [
            KlineData(0, 60000, 60500, 59900, 60200, 100.0, 60000), # Entry hit (Low 59900 <= 60000)
            KlineData(0, 60200, 61000, 60100, 60800, 100.0, 60000),
            KlineData(0, 60800, 62500, 60700, 62100, 100.0, 60000), # TP hit (High 62500 >= 62000)
        ]
        
        outcome = self.assembler.calculate_outcome(klines, 60000, strategy, 500, 500, 1.5, 1.5, 1.0)
        
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
            KlineData(0, 60000, 60100, 59900, 59950, 100.0, 60000), # Entry hit
            KlineData(0, 59950, 60000, 58000, 58500, 100.0, 60000), # SL hit (Low 58000 <= 59000)
        ]
        
        outcome = self.assembler.calculate_outcome(klines, 60000, strategy, 500, 500, 1.5, 1.5, 1.0)
        
        self.assertTrue(outcome["is_filled"])
        self.assertEqual(outcome["tp_sl_result"], "SL_HIT")

    def test_opportunity_cost_neutral_paradox(self):
        # Scenario: Agent chose NEUTRAL, but price moved 3 ATRs (Missed Opportunity)
        strategy = {
            "final_decision": {"opinion": "NEUTRAL"},
            "observation": {
                "quantitative_metrics": {
                    "volume_profile": {"poc": 60000} # Structural data was available
                }
            }
        }
        
        # Consistent with v6.16 Schema
        outcome = {
            "market_forensics": {
                "window_volatility_intensity_atr": 3.0,
                "max_favorable_runup_atr": 1.5,
                "max_favorable_runup_pct": 1.5
            }
        }
        
        report = self.assembler.review(strategy, outcome)
        
        # Result: With missed_opportunity_atr_threshold=2.0 (from setUp), 3.0 > 2.0 -> NOT justified
        self.assertIn("forensic_verdict", report)
        self.assertFalse(report["forensic_verdict"]["is_justified_surrender"])

    def test_catastrophic_miss_detection(self):
        # Scenario: Trade NOT filled, but price moved 4 ATRs (Catastrophic Miss)
        strategy = {
            "final_decision": {"opinion": "BULLISH", "tactical_parameters": {"entry": 60000}},
            "observation": {"quantitative_metrics": {"volume_profile": {}}}
        }
        
        outcome = {
            "is_filled": False,
            "market_forensics": {
                "max_favorable_runup_atr": 4.0, # 4 > threshold 3.0
                "max_favorable_runup_pct": 1.0 # This should be ignored now
            }
        }
        
        report = self.assembler.review(strategy, outcome)
        
        self.assertTrue(report["forensic_verdict"]["is_catastrophic_miss"])

if __name__ == '__main__':
    unittest.main()
