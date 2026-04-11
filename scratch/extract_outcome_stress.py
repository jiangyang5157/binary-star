import json
import os

def extract_outcome_and_stress(filepath):
    if not os.path.exists(filepath): return None
    try:
        with open(filepath, 'r') as f: data = json.load(f)
    except: return None
    
    outcome = data.get('market_outcome', {})
    forensics = outcome.get('market_forensics', {})
    tm = outcome.get('trade_execution_metrics', {}) or {}
    sess = data.get('session') if 'session' in data else data
    fd = sess.get('final_decision', {})
    
    actual_move = forensics.get('total_price_change_pct', 0)
    actual_dir = "BULLISH" if actual_move > 0 else "BEARISH"
    opinion = fd.get('opinion')
    
    dir_correct = "YES" if opinion == actual_dir else ("N/A" if opinion == "NEUTRAL" else "NO")
    
    return {
        'result': outcome.get('tp_sl_result'),
        'dir_correct': dir_correct,
        'stress_mae': tm.get('mae_stress_level_pct', 'N/A'),
        'opinion': opinion,
        'actual_move': actual_move
    }

targets = [
    {"ts": "20260323_050000", "versions": ["v1", "v9.1", "v10.1", "v10.3"]},
    {"ts": "20260325_030000", "versions": ["v1", "v6.5", "v9.1", "v10.2"]},
    {"ts": "20260403_110000", "versions": ["v1", "v6.5", "v9.1", "v10.1", "v10.2"]}
]

results = {}

for target in targets:
    ts = target['ts']
    results[ts] = {}
    for v in target['versions']:
        if v == 'v9.1':
            path = f"data/backtest/sessions/{v}/audits/BTCUSDT_audit_{ts}.json"
        elif v in ['v10.1', 'v10.2', 'v10.3']:
            path = f"data/backtest/sessions/{v}/audits/BTCUSDT_audit_{ts}.json"
        else:
            path = f"data/backtest/sessions/{v}/BTCUSDT_audit_{ts}.json"
        
        data = extract_outcome_and_stress(path)
        if data:
            results[ts][v] = data

# Output formatted table
print(f"{'TS':<16} | {'Ver':<6} | {'Result':<10} | {'Dir Correct':<11} | {'Stress (MAE%)':<13}")
print("-" * 70)
for ts, versions in results.items():
    for v, d in versions.items():
        print(f"{ts:<16} | {v:<6} | {str(d['result']):<10} | {d['dir_correct']:<11} | {str(d['stress_mae']):<13}")
    print("-" * 70)
