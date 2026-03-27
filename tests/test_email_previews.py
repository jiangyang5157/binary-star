import os
import json
import sys

# Ensure project root is in path
# Now located in tests/, so need to go one level up for project root
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from src.infrastructure.notifications.email_notifier import StrategyNotifier

def test_notifications():
    # Use data/test as root for internal previews
    notifier = StrategyNotifier(data_root="data/test")
    symbol = "BTCUSDT"
    
    # 1. Test Strategy Preview (Forced BULLISH)
    # Using relative paths from project root
    strat_path = os.path.join(project_root, "data/live/strategies/BTCUSDT_strategies_20260327_201041.json")
    if os.path.exists(strat_path):
        with open(strat_path, 'r') as f:
            strat_data = json.load(f)
        strat_data["final_decision"]["opinion"] = "BULLISH"
        strat_data["final_decision"]["confidence"] = 92
        
        print(f"Generating Final Strategy HTML (BULLISH) from {os.path.basename(strat_path)}...")
        notifier.notify_strategy(symbol, strat_data, save_local=True)
    else:
        print(f"Strategy file not found: {strat_path}")

    # 2. Test Review Preview (Forced TP_HIT)
    review_path = os.path.join(project_root, "data/live/reviewers/BTCUSDT_reviewers_20260327_201041.json")
    if os.path.exists(review_path):
        with open(review_path, 'r') as f:
            review_data = json.load(f)
        # Update metrics to trigger dispatch in test
        if "market_outcome" not in review_data:
            review_data["market_outcome"] = {}
        if "trade_execution_metrics" not in review_data["market_outcome"]:
            review_data["market_outcome"]["trade_execution_metrics"] = {}
        
        review_data["market_outcome"]["trade_execution_metrics"]["tp_sl_result"] = "TP_HIT"
        review_data["strategy_session"]["final_decision"]["confidence"] = 92
        
        print(f"Generating Final Review HTML (TP_HIT) from {os.path.basename(review_path)}...")
        notifier.notify_review(symbol, review_data, save_local=True)
    else:
        print(f"Review file not found: {review_path}")

if __name__ == "__main__":
    test_notifications()
