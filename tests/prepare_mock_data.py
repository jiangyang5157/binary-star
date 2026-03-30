import os
import json
from datetime import datetime, timedelta, timezone

def generate_mock_environment(data_root, count=5):
    # Ensure full hierarchy
    for sub in ["strategies", "reviewers", "klines"]:
        os.makedirs(os.path.join(data_root, sub), exist_ok=True)
    
    symbol = "BTCUSDT"
    now = datetime.now(timezone.utc)
    
    for i in range(count):
        ts = (now - timedelta(hours=i)).strftime("%Y%m%d_%H%M%S")
        
        # 1. Create a mock strategy session
        strat_filename = f"{symbol}_strategy_{ts}.json"
        strat_path = os.path.join(data_root, "strategies", strat_filename)
        
        strat_session = {
            "observation": {
                "symbol": symbol,
                "timestamp": (now - timedelta(hours=i)).isoformat(),
                "quantitative_metrics": {"price_dynamics": {"atr_macro": 100.0}},
                "visual_assets": {
                    "macro_snapshot": f"data/test/klines/{symbol}_1h_klines_{ts}.png",
                    "micro_snapshot": f"data/test/klines/{symbol}_15m_klines_{ts}.png"
                }
            },
            "final_decision": {
                "opinion": "BULLISH",
                "limit_order": {"entry": 60000.0, "take_profit": 62000.0, "stop_loss": 59000.0}
            }
        }
        
        with open(strat_path, 'w') as f:
            json.dump(strat_session, f, indent=2)

        # 2. Create a high-fidelity forensic report
        review_filename = f"{symbol}_reviewers_{ts}.json"
        review_path = os.path.join(data_root, "reviewers", review_filename)
        
        mock_review = {
            "audit_timestamp": now.isoformat(),
            "strategy_session": strat_session,
            "market_outcome": {
                "tp_sl_result": "TP_HIT" if i % 2 == 0 else "SL_HIT",
                "intercept_status": {"is_intercepted": False, "reason": "NONE"},
                "market_context": {
                    "atr_t0": 100.0,
                    "atr_t1": 110.0,
                    "max_atr_used": 115.0,
                    "visual_evidence": {}
                },
                "trade_execution_metrics": {
                    "duration_candles": 10,
                    "actual_hours": 2.5,
                    "mae_stress_level": 15.0,
                    "mfe_efficiency": 85.0
                }
            },
            "audit_findings": {
                "evaluation_score": 85 if i % 2 == 0 else 40,
                "adversarial_audit": {
                    "protocol_breach": "None" if i % 2 == 0 else "Misaligned SL depth",
                    "hallucination_detected": False
                },
                "post_mortem": "[TRAJECTORY REALITY] -> Win."
            }
        }
        
        with open(review_path, 'w') as f:
            json.dump(mock_review, f, indent=2)
            
    print(f"Mock environment initialized in {data_root}")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="data/test")
    args = parser.parse_args()
    
    generate_mock_environment(args.root)
