import sys
import os
import json
import shutil
from datetime import datetime, timezone

# Add the project root to the Python path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, PROJECT_ROOT)

from src.data_fetcher.storage import DataStorage

def test_coach_pipeline_scanning():
    print("--- Testing Coach Batch Scanning ---")
    
    # Setup mock env
    test_base = os.path.join(PROJECT_ROOT, "tests/tmp_coach_test")
    rev_dir = os.path.join(test_base, "data/reviews")
    if os.path.exists(test_base):
        shutil.rmtree(test_base)
    os.makedirs(rev_dir, exist_ok=True)
    
    # Create mock reviews for BTCUSDT
    symbol = "BTCUSDT"
    for i in range(5):
        rev_data = {"prediction": {"content": {"test": i}}}
        DataStorage.save_json(rev_data, os.path.join(rev_dir, f"review_{symbol}_pred_{i}.json"))
    
    # Create ONE review for ETHUSDT (should be ignored for BTC)
    DataStorage.save_json({"test": "eth"}, os.path.join(rev_dir, "review_ETHUSDT_pred_0.json"))

    # Simulate logic from coach.py
    print(f"[Verification] Looking for reviews for {symbol}...")
    prefix = f"review_{symbol}"
    found = [f for f in os.listdir(rev_dir) if f.startswith(prefix)]
    
    # Assertions
    success = True
    if len(found) != 5:
        print(f"[FAIL] Expected 5 reviews for {symbol}, found {len(found)}")
        success = False
    else:
        print(f"[SUCCESS] Correctly identified {len(found)} reviews for {symbol}.")

    # Clean up
    shutil.rmtree(test_base)
    if not success:
        sys.exit(1)

if __name__ == "__main__":
    test_coach_pipeline_scanning()
