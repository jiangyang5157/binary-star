"""
Forensic Reviewer Mock Factory
==============================
Generates simulated 'Reviewer' JSON reports to test the Forensic Dashboard's 
filtering and visualization logic.

Usage:
    python3 tests/mock_forensic_reviewer_factory.py
"""
import json
import os
import random
from datetime import datetime, timedelta

def create_mock(filename, opinion, result, is_premature, is_filled=True, confidence=None, timestamp=None):
    if timestamp is None:
        timestamp = (datetime.utcnow() - timedelta(hours=random.randint(1, 24))).isoformat() + "Z"
    
    if confidence is None:
        confidence = round(random.uniform(40, 95), 1)

    data = {
        "audit_timestamp": datetime.utcnow().isoformat() + "Z",
        "strategy_session": {
            "observation": { 
                "symbol": "BTCUSDT", 
                "timestamp": timestamp 
            },
            "final_decision": {
                "opinion": opinion,
                "confidence": confidence,
                "limit_order": { 
                    "entry": 65000, 
                    "take_profit": 66000 if opinion == "BULLISH" else 64000, 
                    "stop_loss": 64500 if opinion == "BULLISH" else 65500, 
                    "holding_time_hours": random.uniform(2, 12) 
                }
            }
        },
        "market_outcome": {
            "tp_sl_result": result,
            "is_filled": is_filled,
            "intercept_status": {
                "is_intercepted": is_premature,
                "reason": "PREMATURE_WINDOW" if is_premature else "NONE"
            },
            "market_context": {
                "atr_t0": 100.0,
                "atr_t1": 105.0,
                "max_atr_used": 1.2,
                "visual_evidence": {}
            },
            "trade_execution_metrics": { 
                "duration_candles": 10,
                "actual_hours": 3.2,
                "mae_stress_level": 15.0,
                "mfe_efficiency": 85.0
            }
        }
    }
    
    # Ensure current working directory is the project root when running
    target_dir = os.path.join(os.getcwd(), "data/test/reviewers")
    os.makedirs(target_dir, exist_ok=True)
    
    path = os.path.join(target_dir, filename)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
    print(f"Generated: {path} (Opinion: {opinion}, Result: {result}, Filled: {is_filled}, Premature: {is_premature})")

if __name__ == "__main__":
    # 1. Clear previous mocks for a fresh run
    target_dir = "data/test/reviewers"
    if os.path.exists(target_dir):
        for f in os.listdir(target_dir):
            if f.startswith("BTCUSDT_reviewers_mock_"):
                os.remove(os.path.join(target_dir, f))
                
    # 2. Generate new diverse mocks
    create_mock("BTCUSDT_reviewers_mock_tp1.json", "BULLISH", "TP_HIT", False, is_filled=True, confidence=88.5)
    create_mock("BTCUSDT_reviewers_mock_tp2.json", "BEARISH", "TP_HIT", False, is_filled=True, confidence=91.0)
    create_mock("BTCUSDT_reviewers_mock_sl1.json", "BULLISH", "SL_HIT", False, is_filled=True, confidence=42.0)
    create_mock("BTCUSDT_reviewers_mock_sl2.json", "BEARISH", "SL_HIT", False, is_filled=True, confidence=55.0)
    create_mock("BTCUSDT_reviewers_mock_expired1.json", "BULLISH", "NEITHER", False, is_filled=True, confidence=65.0)
    create_mock("BTCUSDT_reviewers_mock_expired2.json", "BEARISH", "NEITHER", False, is_filled=True, confidence=58.0)
    create_mock("BTCUSDT_reviewers_mock_unfilled1.json", "BULLISH", "NEITHER", False, is_filled=False, confidence=72.0)
    create_mock("BTCUSDT_reviewers_mock_pending1.json", "BULLISH", "NEITHER", True, is_filled=True, confidence=77.0)
    create_mock("BTCUSDT_reviewers_mock_neutral1.json", "NEUTRAL", "TP_HIT", False, is_filled=True, confidence=50.0)
