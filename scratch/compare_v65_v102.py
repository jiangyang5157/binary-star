import json
import os

def extract_session_data(filepath):
    if not os.path.exists(filepath): return None
    try:
        with open(filepath, 'r') as f: data = json.load(f)
    except: return None
    fd = data.get('final_decision', {})
    tp = fd.get('tactical_parameters', {})
    return {'opinion': fd.get('opinion'), 'entry': tp.get('entry'), 'sl': tp.get('stop_loss'), 'tp': tp.get('take_profit')}

def extract_audit_data(filepath):
    if not os.path.exists(filepath): return None
    try:
        with open(filepath, 'r') as f: data = json.load(f)
    except: return None
    outcome = data.get('market_outcome', {})
    tm = outcome.get('trade_execution_metrics', {}) or {}
    return {'result': outcome.get('tp_sl_result'), 'mae': tm.get('mae_stress_level_pct', 'N/A'), 'mfe': tm.get('mfe_efficiency_pct', 'N/A')}

timestamps = ["20260311_040000", "20260315_190000", "20260320_110000", "20260325_030000", "20260329_190000", "20260403_110000", "20260408_030000"]
results = []

for ts in timestamps:
    v6_sess = f"data/backtest/sessions/v6.5/BTCUSDT_session_{ts}.json"
    v6_audi = f"data/backtest/sessions/v6.5/BTCUSDT_audit_{ts}.json"
    v10_sess = f"data/backtest/sessions/v10.2/sessions/BTCUSDT_session_{ts}.json"
    v10_audi = f"data/backtest/sessions/v10.2/audits/BTCUSDT_audit_{ts}.json"
    
    d6 = extract_session_data(v6_sess)
    a6 = extract_audit_data(v6_audi)
    d10 = extract_session_data(v10_sess)
    a10 = extract_audit_data(v10_audi)
    
    if d6 and d10:
        results.append({
            'TS': ts,
            'v6_Op': d6['opinion'], 'v10_Op': d10['opinion'],
            'v6_Res': a6.get('result') if a6 else 'N/A', 'v10_Res': a10.get('result') if a10 else 'N/A',
            'v6_MAE': a6.get('mae') if a6 else 'N/A', 'v10_MAE': a10.get('mae') if a10 else 'N/A'
        })

print(f"{'Timestamp':<16} | {'v6 Op':<8} | {'v10 Op':<8} | {'v6 Res':<10} | {'v10 Res':<10} | {'v6 MAE':<7} | {'v10 MAE':<7}")
print("-" * 80)
for r in results:
    print(f"{r['TS']:<16} | {str(r['v6_Op']):<8} | {str(r['v10_Op']):<8} | {str(r['v6_Res']):<10} | {str(r['v10_Res']):<10} | {str(r['v6_MAE']):<7} | {str(r['v10_MAE']):<7}")
