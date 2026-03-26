import os
import json
import random
from datetime import datetime, timedelta, timezone

def _get_ts(base_time, offset_hours):
    return (base_time + timedelta(hours=offset_hours)).strftime("%Y%m%d_%H%M%S")

def _save_report(data_root, filename, report):
    review_dir = os.path.join(data_root, "reviewers")
    os.makedirs(review_dir, exist_ok=True)
    filepath = os.path.join(review_dir, filename)
    with open(filepath, 'w') as f:
        json.dump(report, f, indent=2)

def generate_tp(data_root, index, symbol="BTCUSDT", base_time=None):
    base_time = base_time or datetime.now(timezone.utc)
    ts = _get_ts(base_time, index * 2)
    filename = f"{symbol}_reviewers_tp_{index}_{ts}.json"
    
    entry = 60000 + random.randint(-500, 500)
    tp = entry + random.randint(600, 1000)
    sl = entry - random.randint(300, 500)
    
    report = {
        "strategy_session": {
            "observation": { "symbol": symbol, "timestamp": (base_time + timedelta(hours=index*2)).isoformat() },
            "final_decision": {
                "opinion": "BULLISH", "confidence": random.randint(75, 95),
                "limit_order": { "entry": entry, "take_profit": tp, "stop_loss": sl, "holding_time_hours": round(random.uniform(2, 6), 2) }
            }
        },
        "market_outcome": { "trade_execution_metrics": { "is_premature_audit": False, "tp_sl_result": "TP_HIT" } }
    }
    _save_report(data_root, filename, report)
    return filename

def generate_sl(data_root, index, symbol="BTCUSDT", base_time=None):
    base_time = base_time or datetime.now(timezone.utc)
    ts = _get_ts(base_time, index * 2)
    filename = f"{symbol}_reviewers_sl_{index}_{ts}.json"
    
    entry = 60000 + random.randint(-500, 500)
    tp = entry + random.randint(600, 1000)
    sl = entry - random.randint(300, 500)
    
    report = {
        "strategy_session": {
            "observation": { "symbol": symbol, "timestamp": (base_time + timedelta(hours=index*2)).isoformat() },
            "final_decision": {
                "opinion": "BULLISH", "confidence": random.randint(60, 80),
                "limit_order": { "entry": entry, "take_profit": tp, "stop_loss": sl, "holding_time_hours": round(random.uniform(2, 6), 2) }
            }
        },
        "market_outcome": { "trade_execution_metrics": { "is_premature_audit": False, "tp_sl_result": "SL_HIT" } }
    }
    _save_report(data_root, filename, report)
    return filename

def generate_neither(data_root, index, symbol="BTCUSDT", base_time=None):
    base_time = base_time or datetime.now(timezone.utc)
    ts = _get_ts(base_time, index * 2)
    filename = f"{symbol}_reviewers_neither_{index}_{ts}.json"
    
    report = {
        "strategy_session": {
            "observation": { "symbol": symbol, "timestamp": (base_time + timedelta(hours=index*2)).isoformat() },
            "final_decision": {
                "opinion": "BEARISH", "confidence": random.randint(65, 85),
                "limit_order": { "entry": 60000, "take_profit": 59000, "stop_loss": 60500, "holding_time_hours": 4.0 }
            }
        },
        "market_outcome": { "trade_execution_metrics": { "is_premature_audit": False, "tp_sl_result": "NEITHER" } }
    }
    _save_report(data_root, filename, report)
    return filename

def generate_neutral(data_root, index, symbol="BTCUSDT", base_time=None):
    base_time = base_time or datetime.now(timezone.utc)
    ts = _get_ts(base_time, index * 2 + 1)
    filename = f"{symbol}_reviewers_neutral_{index}_{ts}.json"
    
    report = {
        "strategy_session": {
            "observation": { "symbol": symbol, "timestamp": (base_time + timedelta(hours=index*2 + 1)).isoformat() },
            "final_decision": { "opinion": "NEUTRAL", "confidence": None }
        },
        "market_outcome": { "trade_execution_metrics": { "is_premature_audit": False, "tp_sl_result": "NEITHER" } }
    }
    _save_report(data_root, filename, report)
    return filename

def generate_pending(data_root, index, symbol="BTCUSDT", base_time=None):
    base_time = base_time or datetime.now(timezone.utc)
    ts = _get_ts(base_time, index * 2 + 0.5)
    filename = f"{symbol}_reviewers_pending_{index}_{ts}.json"
    
    report = {
        "market_outcome": { "trade_execution_metrics": { "is_premature_audit": True, "tp_sl_result": "NEITHER" } }
    }
    _save_report(data_root, filename, report)
    return filename

def generate_random_tp_sl(data_root, index, symbol="BTCUSDT", base_time=None):
    if random.random() > 0.5:
        return generate_tp(data_root, index, symbol, base_time)
    else:
        return generate_sl(data_root, index, symbol, base_time)

def generate_batch_reports(data_root, total_count=40):
    import shutil
    review_dir = os.path.join(data_root, "reviewers")
    if os.path.exists(review_dir):
        shutil.rmtree(review_dir)
    os.makedirs(review_dir)
    
    base_time = datetime.now(timezone.utc) - timedelta(days=2)
    
    # Weights for variety (TP: 15, SL: 10, Neither: 8, Neutral: 5, Pending: 2)
    methods = [
        generate_tp, generate_sl, generate_neither, generate_neutral, generate_pending
    ]
    weights = [15, 10, 8, 5, 2]
    
    selected_methods = random.choices(methods, weights=weights, k=total_count)
    
    for i, method in enumerate(selected_methods):
        method(data_root, i, base_time=base_time)
            
    print(f"Generated {total_count} randomized/mixed test reports in {data_root}/reviewers")

if __name__ == "__main__":
    generate_batch_reports("data/test", 40)
