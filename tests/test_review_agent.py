import sys
import os
import json

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from src.agent.reviewer_agent import ReviewerAgent

def test_review_agent_mock():
    print("--- Testing Crypto Dual-Agent Reviewer Layer ---")
    
    # Mock data for Agent A's past prediction
    historical_prediction = {
        "timestamp": "2026-03-01T12:00:00Z",
        "action": "BUY",
        "current_price": 65000,
        "take_profit": 72000,
        "stop_loss": 63000,
        "confidence": 85,
        "reasoning": "Price broke out above POC on high volume, funding rate is negative indicating shorts are trapped."
    }
    
    # Mock data for what actually happened (e.g., a fakeout trap)
    actual_outcome = {
        "max_price_reached": 68000,
        "min_price_reached": 62000,
        "close_price_after_7_days": 63000,
        "result": "Loss",
        "notes": "Price instantly reversed after breaking POC, dropping 7% within 168 hours."
    }
    
    # Mock current config
    current_config = {
        "trading": {
            "symbol": "BTCUSDT", 
            "strategy": "swing",
        },
        "prediction": {
            "trade_horizon_days": 7,
            "macro_timeframe": {"interval": "1d", "limit": 100},
            "micro_timeframe": {"interval": "4h", "limit": 168},
        },
        "agent": {
            "trader_model": "gemini-flash-latest",
            "reviewer_model": "gemini-flash-latest",
            "review_temperature": 1.0,
            "coach_temperature": 1.0
        }
    }
    
    print("\n[1] Invoking Agent B (Reviewer)...")
    print("Note: Ensure GEMINI_API_KEY environment variable is set.")
    
    # Agent B execution
    reviewer = ReviewerAgent(
        model_name=current_config['agent']['reviewer_model'],
        prompts_dir=os.path.join(os.path.dirname(__file__), '..', 'src', 'agent', 'prompts')
    )
    
    if not os.environ.get("GEMINI_API_KEY"):
        print("    GEMINI_API_KEY not found in environment. Mocking Agent B output for testing...")
        agent_output = json.dumps({
            "evaluation_score": 10,
            "flaw_analysis": "Agent A was trapped in a fakeout. It ignored micro-level rejection wicks.",
            "prompt_patch_suggestion": "Wait for a 1D candle close above POC before confirming a breakout.",
            "config_update_suggestion": {}
        }, indent=2)
    else:
        # For testing, we can pass dummy paths or valid ones if they exist
        dummy_chart_paths = [
            os.path.join(os.path.dirname(__file__), '..', 'data', 'images', 'BTCUSDT_1d_chart.png'),
            os.path.join(os.path.dirname(__file__), '..', 'data', 'images', 'BTCUSDT_4h_chart.png')
        ]
        agent_output = reviewer.review(
            historical_prediction=historical_prediction, 
            actual_outcome=actual_outcome, 
            config=current_config,
            chart_image_paths=dummy_chart_paths
        )
        
    print(f"\n    Agent B Output:\n{agent_output}")

if __name__ == "__main__":
    test_review_agent_mock()
