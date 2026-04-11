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

ts_v1 = ["20260323_050000", "20260325_190000", "20260326_230000", "20260329_130000"]
ts_v65 = ["20260311_040000", "20260315_190000", "20260320_110000", "20260325_030000", "20260329_190000", "20260403_110000", "20260408_030000"]
all_ts = sorted(list(set(ts_v1 + ts_v65)))

rows = []
for ts in all_ts:
    d106 = extract_detailed_audit(f"data/backtest/sessions/v10.6/audits/BTCUSDT_audit_{ts}.json")
    d105 = extract_detailed_audit(f"data/backtest/sessions/v10.5/audits/BTCUSDT_audit_{ts}.json")
    d104 = extract_detailed_audit(f"data/backtest/sessions/v10.4/audits/BTCUSDT_audit_{ts}.json")
    
    source_ver = "v1" if ts in ts_v1 else "v6.5"
    if source_ver == "v1":
        source_path = f"data/backtest/sessions/v1/BTCUSDT_audit_{ts}.json"
    else:
        source_path = f"data/backtest/sessions/v6.5/BTCUSDT_audit_{ts}.json"
    ds = extract_detailed_audit(source_path)
    
    if d106:
        rows.append({
            'TS': ts,
            'S_Res': ds['result'] if ds else 'N/A',
            'v104_Res': d104['result'] if d104 else 'N/A',
            'v105_Res': d105['result'] if d105 else 'N/A',
            'v106_Op': d106['opinion'],
            'v106_Res': d106['result'],
            'v106_MAE': d106['mae_stress']
        })

print(f"| Timestamp | Src_Res | v10.4_Res | v10.5_Res | v10.6_Op | v10.6_Res | v10.6_MAE |")
print(f"| :--- | :--- | :--- | :--- | :--- | :--- | :--- |")
for r in rows:
    print(f"| {r['TS']} | {r['S_Res']} | {r['v104_Res']} | {r['v105_Res']} | {r['v106_Op']} | {r['v106_Res']} | {r['v106_MAE']} |")
