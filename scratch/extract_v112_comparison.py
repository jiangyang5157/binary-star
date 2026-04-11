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
    d112 = extract_detailed_audit(f"data/backtest/sessions/v11.2/audits/BTCUSDT_audit_{ts}.json")
    d106 = extract_detailed_audit(f"data/backtest/sessions/v10.6/audits/BTCUSDT_audit_{ts}.json")
    d105 = extract_detailed_audit(f"data/backtest/sessions/v10.5/audits/BTCUSDT_audit_{ts}.json")
    d104 = extract_detailed_audit(f"data/backtest/sessions/v10.4/audits/BTCUSDT_audit_{ts}.json")
    
    source_ver = "v1" if ts in ts_v1 else "v6.5"
    if source_ver == "v1":
        source_path = f"data/backtest/sessions/v1/BTCUSDT_audit_{ts}.json"
    else:
        source_path = f"data/backtest/sessions/v6.5/BTCUSDT_audit_{ts}.json"
    ds = extract_detailed_audit(source_path)
    
    rows.append({
        'TS': ts,
        'S_Res': ds['result'] if ds else 'N/A',
        'v104_Res': d104['result'] if d104 else 'N/A',
        'v105_Res': d105['result'] if d105 else 'N/A',
        'v106_Res': d106['result'] if d106 else 'N/A',
        'v112_Op': d112['opinion'] if d112 else 'N/A',
        'v112_Res': d112['result'] if d112 else 'N/A',
        'v112_MAE': d112['mae_stress'] if d112 else 'N/A'
    })

print(f"| Timestamp | Src_Res | v10.4 | v10.5 | v10.6 | **v11.2_Op** | **v11.2_Res** | **v11.2_MAE** |")
print(f"| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |")
for r in rows:
    print(f"| {r['TS']} | {r['S_Res']} | {r['v104_Res']} | {r['v105_Res']} | {r['v106_Res']} | {r['v112_Op']} | {r['v112_Res']} | {r['v112_MAE']} |")
