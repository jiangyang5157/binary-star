import sys
import os
from unittest.mock import MagicMock, patch

# Add project root to path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from strategist import calculate_math_fact_check

def test_math_fix():
    print("Running Strategist Math Verification...")
    
    # Mock observation and draft
    observation = {
        "quantitative_metrics": {
            "price_dynamics": {"atr_macro": 100.0},
            "market_regime": {"trend_intensity": 1.0},
            "volume_topography": {"poc": 50000.0, "vah": 51000.0, "val": 49000.0}
        }
    }
    
    # Bullish Draft: Entry 50000, SL 49500 (Below POC 50000)
    draft_bullish = {
        "action": "BULLISH",
        "limit_order": {"entry": 50000.0, "take_profit": 52000.0, "stop_loss": 49500.0}
    }
    
    # Bearish Draft: Entry 50000, SL 50500 (Above POC 50000)
    draft_bearish = {
        "action": "BEARISH",
        "limit_order": {"entry": 50000.0, "take_profit": 48000.0, "stop_loss": 50500.0}
    }

    with patch('strategist.load_config') as mock_load:
        # Case 1: 1h Macro
        mock_load.return_value = {
            "strategist": {"min_trade_velocity": 0.4},
            "observer": {"macro_analysis_context": {"time_interval": "1h"}}
        }
        
        # Bullish Vector Check: (49500 - 50000) / 100 = -5.0 (Negative = Correct for Bullish)
        result1h = calculate_math_fact_check(observation, draft_bullish)
        print(f"1h Macro (Bullish) Result: {result1h['sl_to_poc_atr']} (Expected: -5.0)")
        assert result1h['sl_to_poc_atr'] == -5.0
        # Bullish Holding Time: (2000 / 100) * 1 = 20.0
        print(f"1h Macro (Bullish) Holding Time: {result1h['projected_holding_hours']} (Expected: 20.0)")
        assert result1h['projected_holding_hours'] == 20.0

        # Case 2: 4h Macro
        mock_load.return_value = {
            "strategist": {"min_trade_velocity": 0.4},
            "observer": {"macro_analysis_context": {"time_interval": "4h"}}
        }
        
        # 4h Holding Time: (2000 / 100) * 4 = 80.0
        result4h = calculate_math_fact_check(observation, draft_bullish)
        print(f"4h Macro (Bullish) Holding Time: {result4h['projected_holding_hours']} (Expected: 80.0)")
        assert result4h['projected_holding_hours'] == 80.0
        
        # Case 3: Bearish Vector Check
        # Bearish Vector Check: (50500 - 50000) / 100 = 5.0 (Positive = Correct for Bearish)
        result_bearish = calculate_math_fact_check(observation, draft_bearish)
        print(f"1h Macro (Bearish) Result: {result_bearish['sl_to_poc_atr']} (Expected: 5.0)")
        assert result_bearish['sl_to_poc_atr'] == 5.0

    print("\nSUCCESS: All math fixes verified.")

if __name__ == "__main__":
    try:
        test_math_fix()
    except Exception as e:
        print(f"\nFAILURE: {e}")
        sys.exit(1)
