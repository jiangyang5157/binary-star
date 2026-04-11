import json
import os

def extract_detailed_audit(filepath):
    if not os.path.exists(filepath): return None
    try:
        with open(filepath, 'r') as f: data = json.load(f)
    except: return None
    
    outcome = data.get('market_outcome', {})
    tm = outcome.get('trade_execution_metrics', {}) or {}
    sess = data.get('session') if 'session' in data else data
    fd = sess.get('final_decision', {})
    
    return {
        'opinion': fd.get('opinion'),
        'result': outcome.get('tp_sl_result'),
        'mae_stress': tm.get('mae_stress_level_pct', 'N/A'),
        'mfe_eff': tm.get('mfe_efficiency_pct', 'N/A')
    }

timestamps = ["20260323_050000", "20260325_190000", "20260326_230000", "20260329_130000"]
versions = ["v1", "v9.1", "v10.1", "v10.3"]

rows = []
for ts in timestamps:
    for v in versions:
        if v == 'v9.1' or v.startswith('v10'):
            path = f"data/backtest/sessions/{v}/audits/BTCUSDT_audit_{ts}.json"
        else:
            path = f"data/backtest/sessions/{v}/BTCUSDT_audit_{ts}.json"
            
        data = extract_detailed_audit(path)
        if data:
            rows.append({
                'TS': ts,
                'Ver': v,
                'Op': data['opinion'],
                'Res': data['result'],
                'MAE': data['mae_stress'],
                'MFE': data['mfe_eff']
            })

# Print formatted Markdown-style table
print(f"| Timestamp | Version | Opinion | Result | MAE Stress% | MFE Efficiency% |")
print(f"| :--- | :--- | :--- | :--- | :--- | :--- |")
for r in rows:
    print(f"| {r['TS']} | {r['Ver']} | {r['Op']} | {r['Res']} | {r['MAE']} | {r['MFE']} |")
