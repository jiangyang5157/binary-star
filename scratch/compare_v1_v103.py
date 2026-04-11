import json
import os

def extract_detailed_audit(filepath):
    if not os.path.exists(filepath): return None
    try:
        with open(filepath, 'r') as f: data = json.load(f)
    except: return None
    
    sess = data.get('session', {})
    fd = sess.get('final_decision', {})
    outcome = data.get('market_outcome', {})
    forensics = outcome.get('market_forensics', {})
    exec_metrics = outcome.get('trade_execution_metrics', {}) or {}
    
    return {
        'opinion': fd.get('opinion'),
        'result': outcome.get('tp_sl_result'),
        'mfe_pct': forensics.get('max_favorable_runup_pct', 0),
        'mae_pct': forensics.get('max_adverse_drawdown_pct', 0),
        'mfe_eff': exec_metrics.get('mfe_efficiency_pct', 0),
        'is_filled': outcome.get('is_filled', False),
        'price_move_pct': forensics.get('total_price_change_pct', 0)
    }

timestamps = ["20260323_050000", "20260325_190000", "20260326_230000", "20260329_130000"]
results = []

for ts in timestamps:
    v1_audi = f"data/backtest/sessions/v1/BTCUSDT_audit_{ts}.json"
    v10_audi = f"data/backtest/sessions/v10.3/audits/BTCUSDT_audit_{ts}.json"
    
    a1 = extract_detailed_audit(v1_audi)
    a10 = extract_detailed_audit(v10_audi)
    
    if a1 and a10:
        results.append({
            'TS': ts,
            'v1': a1,
            'v10': a10
        })

print(f"{'Timestamp':<16} | {'v1 Op':<8} | {'v10 Op':<8} | {'v1 Res':<10} | {'v10 Res':<10} | {'v1 MFE%':<7} | {'v10 MFE%':<7}")
print("-" * 100)
for r in results:
    v1 = r['v1']
    v10 = r['v10']
    print(f"{r['TS']:<16} | {str(v1['opinion']):<8} | {str(v10['opinion']):<8} | {str(v1['result']):<10} | {str(v10['result']):<10} | {v1['mfe_pct']:<7.2f} | {v10['mfe_pct']:<7.2f}")
