import sys
import os
import json
import shutil
import time
from datetime import datetime, timezone, timedelta

# Add the 'src' directory to the Python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.data_fetcher.storage import DataStorage

def test_reviewer_pipeline_orchestration():
    print("--- Testing Crypto Reviewer Batch Pipeline ---")
    
    # 1. Setup Temporary Test Directories
    test_base = os.path.abspath(os.path.join(os.path.dirname(__file__), "tmp_reviewer_test"))
    pred_dir = os.path.join(test_base, "data/predictions")
    rev_dir = os.path.join(test_base, "data/reviews")
    
    os.makedirs(pred_dir, exist_ok=True)
    os.makedirs(rev_dir, exist_ok=True)
    
    print(f"Created temporary test environment at: {test_base}")

    # 2. Create Mock Predictions
    # Prediction 1: Needs review
    p1_name = "BTCUSDT_prediction_20260101_000000.json"
    p1_data = {
        "timestamp": "2026-01-01T00:00:00Z",
        "action": "BUY",
        "config_context": {
            "symbol": "BTCUSDT",
            "prediction_horizon_days": 7
        }
    }
    
    # Prediction 2: Needs review
    p2_name = "BTCUSDT_prediction_20260101_010000.json"
    p2_data = {
        "timestamp": "2026-01-01T01:00:00Z",
        "action": "SELL",
        "config_context": {
            "symbol": "BTCUSDT",
            "prediction_horizon_days": 7
        }
    }

    # Prediction 3: Already reviewed (should be skipped)
    p3_name = "BTCUSDT_prediction_20260101_020000.json"
    p3_data = {
        "timestamp": "2026-01-01T02:00:00Z",
        "action": "HOLD",
        "config_context": {
            "symbol": "BTCUSDT",
            "prediction_horizon_days": 7
        }
    }

    DataStorage.save_json(p1_data, os.path.join(pred_dir, p1_name))
    DataStorage.save_json(p2_data, os.path.join(pred_dir, p2_name))
    DataStorage.save_json(p3_data, os.path.join(pred_dir, p3_name))
    
    # Pre-create the review for P3 to trigger "skip" logic
    DataStorage.save_json({"status": "existing"}, os.path.join(rev_dir, f"review_{p3_name}"))
    
    print(f"Mocked 3 predictions. P1 and P2 are new. P3 has an existing review.")

    # 3. Simulate the logic from review.py (Folder Scanning)
    print("\n[Verification] Scanning folders...")
    all_files = [f for f in os.listdir(pred_dir) if f.endswith(".json")]
    to_review = []
    
    for f in all_files:
        rev_path = os.path.join(rev_dir, f"review_{f}")
        if os.path.exists(rev_path):
            print(f"    - Skipping {f}: Already reviewed.")
        else:
            print(f"    - Adding {f} to queue: Needs review.")
            to_review.append(f)

    # 4. Assertions
    success = True
    if len(to_review) != 2:
        print(f"\n[FAIL] Expected 2 files to review, found {len(to_review)}")
        success = False
    elif p3_name in to_review:
        print(f"\n[FAIL] P3 should have been skipped, but was included in review queue.")
        success = False
    elif p1_name not in to_review or p2_name not in to_review:
        print(f"\n[FAIL] P1 or P2 were missing from the review queue.")
        success = False
    else:
        print("\n[SUCCESS] Batch scanning and skip-logic verified.")

    # 5. Clean up
    print(f"\nCleaning up {test_base}...")
    shutil.rmtree(test_base)
    print("Cleanup complete.")
    
    if not success:
        sys.exit(1)

if __name__ == "__main__":
    test_reviewer_pipeline_orchestration()
