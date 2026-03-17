import sys
import os
import json
import shutil
from datetime import datetime, timezone, timedelta

# Add the project root to the Python path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, PROJECT_ROOT)

from reviewer_main import run_reviewer_pipeline
from src.data_fetcher.storage import DataStorage

def test_aging_protection_logic():
    """
    Verifies that run_reviewer_pipeline:
    1. Skips recent files by default.
    2. Processes them when force=True.
    """
    print("--- Testing Aging Protection & Force Flag ---")
    
    # Setup mock env
    test_base = os.path.join(PROJECT_ROOT, "tests/tmp_cli_test")
    data_dir = os.path.join(test_base, "data/raw")
    pred_dir = os.path.join(data_dir, "predictions")
    rev_dir = os.path.join(data_dir, "reviews")
    
    os.makedirs(pred_dir, exist_ok=True)
    os.makedirs(rev_dir, exist_ok=True)
    
    # Create a RECENT prediction (10 minutes ago)
    now = datetime.now(timezone.utc)
    recent_ts = (now - timedelta(minutes=10)).isoformat() + "Z"
    filename = "BTCUSDT_prediction_recent.json"
    pred_data = {
        "timestamp": recent_ts,
        "symbol": "BTCUSDT",
        "action": "BUY"
    }
    DataStorage.save_json(pred_data, os.path.join(pred_dir, filename))
    
    # Override config logic for the test
    # Note: run_reviewer_pipeline loads config from file. 
    
    print(f"[1] Running normal pipeline (should skip)...")
    # We need to point the pipeline to our temp data dir. 
    # Since run_reviewer_pipeline reads config.yaml, it might be hard to redirect without mocking.
    # However, we can mock 'load_config' inside reviewer_main.
    
    import reviewer_main
    original_load = reviewer_main.load_config
    reviewer_main.load_config = lambda: {
        "paths": {"raw_data_dir": data_dir, "images_dir": "data/images", "prompts_dir": "src/agent/prompts"},
        "trading": {"symbol": "BTCUSDT"},
        "agent": {"model_name": "gemini-flash-latest"},
        "automation": {"reviewer_interval_hours": 16.0}
    }
    
    try:
        # Run WITHOUT force
        run_reviewer_pipeline()
        
        review_file = os.path.join(rev_dir, f"review_{filename}")
        if os.path.exists(review_file):
            print("[FAIL] Review was created for a recent file without --force!")
            assert False
        else:
            print("[SUCCESS] Recent file was correctly skipped.")

        print(f"[2] Running with force=True (should process)...")
        # Run WITH force
        # Note: It might still fail on AI/Binance calls if keys aren't set, 
        # but we want to see it REAACH the fetching stage.
        # We'll mock the internal components enough to avoid network calls.
        
        original_agent_review = reviewer_main.ReviewerAgent.review
        reviewer_main.ReviewerAgent.review = lambda *args, **kwargs: json.dumps({"evaluation_score": 100})
        
        original_fetch = reviewer_main.BinanceDataFetcher.fetch_historical_klines
        reviewer_main.BinanceDataFetcher.fetch_historical_klines = lambda *args, **kwargs: [
            [0, "100", "110", "90", "105", 0, 0] # Mock kline
        ]
        
        run_reviewer_pipeline(force=True)
        
        if os.path.exists(review_file):
            print("[SUCCESS] Review was created for recent file with force=True.")
        else:
            print("[FAIL] Review was NOT created despite force=True.")
            assert False
            
    finally:
        # Restore and Cleanup
        reviewer_main.load_config = original_load
        reviewer_main.ReviewerAgent.review = original_agent_review
        reviewer_main.BinanceDataFetcher.fetch_historical_klines = original_fetch
        shutil.rmtree(test_base)

if __name__ == "__main__":
    test_aging_protection_logic()
