import os
import json
from datetime import datetime, timedelta, timezone

def generate_mock_reviewers(data_root, count=5):
    review_dir = os.path.join(data_root, "reviewers")
    os.makedirs(review_dir, exist_ok=True)
    
    symbol = "BTCUSDT"
    now = datetime.now(timezone.utc)
    
    for i in range(count):
        ts = (now - timedelta(hours=i)).strftime("%Y%m%d_%H%M%S")
        filename = f"{symbol}_reviewers_tp_{i}_{ts}.json"
        file_path = os.path.join(review_dir, filename)
        
        mock_data = {
            "symbol": symbol,
            "timestamp": (now - timedelta(hours=i)).isoformat(),
            "market_outcome": {
                "trade_execution_metrics": {
                    "is_premature_audit": False,
                    "tp_sl_result": "TP",
                    "pnl_net": 150.0
                }
            },
            "signals": {"trend": "bullish", "confidence": 0.85}
        }
        
        with open(file_path, 'w') as f:
            json.dump(mock_data, f, indent=2)
        print(f"Created mock reviewer: {filename}")

if __name__ == "__main__":
    generate_mock_reviewers("data/test")
    print("\nMock data prepared in data/test/reviewers/")
