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
    strat_path = os.path.join(project_root, "data/live/strategies/BTCUSDT_strategies_20260328_121037.json")
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
    review_path = os.path.join(project_root, "data/live/reviewers/BTCUSDT_reviewers_20260328_121037.json")
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

def test_dashboard_notification():
    # Use data/test as root for internal previews
    notifier = StrategyNotifier(data_root="data/test")
    symbol = "BTCUSDT"
    
    # Mock dataset for dashboard
    mock_dataset = [
        {"observation_time": "2026-03-29 01:10:37", "tp_sl_result": "TP_HIT", "estimated_pnl_pct": 2.5, "confidence": 92},
        {"observation_time": "2026-03-29 02:15:00", "tp_sl_result": "SL_HIT", "estimated_pnl_pct": -1.2, "confidence": 85},
        {"observation_time": "2026-03-29 03:20:00", "tp_sl_result": "NEITHER", "estimated_pnl_pct": 0.0, "confidence": 70},
        {"observation_time": "2026-03-29 04:30:00", "tp_sl_result": "TP_HIT", "estimated_pnl_pct": 1.8, "confidence": 88}
    ]
    
    print(f"Generating Aggregate Dashboard HTML for {symbol}...")
    
    # Create a dummy dashboard HTML file to simulate the actual Forensic Dashboard Output
    dummy_dashboard_path = os.path.join(project_root, "data/test/BTCUSDT_dummy_dashboard.html")
    with open(dummy_dashboard_path, "w") as f:
        f.write("<html><body><h1>GORGEOUS DASHBOARD SIMULATION</h1></body></html>")
        
    notifier.notify_dashboard(symbol, mock_dataset, dashboard_path=dummy_dashboard_path)
    
    # Cleanup dummy
    if os.path.exists(dummy_dashboard_path):
        os.remove(dummy_dashboard_path)

def test_coach_notification():
    # Use data/test as root for internal previews
    notifier = StrategyNotifier(data_root="data/test")
    symbol = "BTCUSDT"
    
    mock_analysis = {
        "analysis": "The agent triad is showing systemic slippage in high-volatility regimes. Recommend expanding ATR-SL multipliers by 0.5x when trend_intensity > 2.0."
    }
    
    mock_dataset = [
        {"observation_time": "2026-03-30 01:00:00", "tp_sl_result": "TP_HIT", "estimated_pnl_pct": 1.5, "confidence": 85},
        {"observation_time": "2026-03-30 05:00:00", "tp_sl_result": "SL_HIT", "estimated_pnl_pct": -0.8, "confidence": 72}
    ]
    
    print(f"Generating Unitary Coach + Dashboard HTML for {symbol}...")
    notifier.notify_coach(symbol, mock_analysis, mock_dataset)

if __name__ == "__main__":
    print("--- Starting Email Preview Tests ---")
    test_notifications()
    test_dashboard_notification()
    test_coach_notification()
    print("--- Tests Completed ---")
