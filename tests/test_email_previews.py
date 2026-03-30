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
    data_root = "data/test"
    notifier = StrategyNotifier(data_root=data_root)
    symbol = "BTCUSDT"
    
    # 1. Test Strategy Preview
    strat_dir = os.path.join(project_root, data_root, "strategies")
    if os.path.exists(strat_dir) and os.listdir(strat_dir):
        # Pick the first one
        strat_filename = os.listdir(strat_dir)[0]
        strat_path = os.path.join(strat_dir, strat_filename)
        with open(strat_path, 'r') as f:
            strat_data = json.load(f)
        
        print(f"Generating Strategy HTML from {strat_filename}...")
        notifier.notify_strategy(symbol, strat_data, save_local=True)
    else:
        print(f"No mock strategies found in {strat_dir}")

    # 2. Test Review Preview
    review_dir = os.path.join(project_root, data_root, "reviewers")
    if os.path.exists(review_dir) and os.listdir(review_dir):
        # Pick a TP_HIT or SL_HIT one if possible
        review_files = [f for f in os.listdir(review_dir) if "tp" in f or "sl" in f]
        review_filename = review_files[0] if review_files else os.listdir(review_dir)[0]
        review_path = os.path.join(review_dir, review_filename)
        
        with open(review_path, 'r') as f:
            review_data = json.load(f)
        
        print(f"Generating Review HTML from {review_filename}...")
        notifier.notify_review(symbol, review_data, save_local=True)
    else:
        print(f"Review file not found in {review_dir}")

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


if __name__ == "__main__":
    print("--- Starting Email Preview Tests ---")
    test_notifications()
    test_dashboard_notification()
    print("--- Tests Completed ---")
