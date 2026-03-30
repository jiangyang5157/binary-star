import sys
import os
from unittest.mock import MagicMock, patch

# Setup paths
PROJECT_ROOT = os.path.dirname(os.path.abspath(os.path.dirname(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from reviewer import OutcomeCalculator, ReviewerOrchestrator

def test_outcome_calculator_max_atr():
    print("Testing OutcomeCalculator with updated ATR logic...")
    klines = [
        [0, 100, 105, 95, 100, 10, 0],   # Entry at 100
        [1, 100, 100, 85, 90, 10, 1],    # MAE of 15 (85 - 100)
        [2, 90, 120, 90, 115, 10, 2]     # TP at 120
    ]
    strategy = {
        "opinion": "BULLISH",
        "limit_order": {
            "entry": 100,
            "stop_loss": 80,
            "take_profit": 120
        }
    }
    
    # ATR T0 = 10 (High volatility expansion later)
    # If we use ATR=10, MAE = 15 -> mae_atr_ratio = 1.5
    # If we use ATR=20 (Max ATR), MAE = 15 -> mae_atr_ratio = 0.75
    
    atr_t0 = 10
    atr_t1 = 20
    max_atr = max(atr_t0, atr_t1)
    
    outcome = OutcomeCalculator.calculate(klines, 100, strategy, atr=max_atr, interval_hours=1)
    
    print(f"Outcome Metrics: {outcome['trade_execution_metrics']}")
    assert outcome['trade_execution_metrics']['mae_atr_ratio'] == 0.75
    print("Test Passed: MAE ATR ratio correctly uses max_atr.")

if __name__ == "__main__":
    try:
        test_outcome_calculator_max_atr()
    except Exception as e:
        print(f"Test Failed: {e}")
        sys.exit(1)
