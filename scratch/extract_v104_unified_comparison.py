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

# All 11 timestamps
ts_v1 = ["20260323_050000", "20260325_190000", "20260326_230000", "20260329_130000"]
ts_v65 = ["20260311_040000", "20260315_190000", "20260320_110000", "20260325_030000", "20260329_190000", "20260403_110000", "20260408_030000"]
all_ts = sorted(list(set(ts_v1 + ts_v65)))

rows = []
for ts in all_ts:
    v104_path = f"data/backtest/sessions/v10.4/audits/BTCUSDT_audit_{ts}.json"
    d104 = extract_detailed_audit(v104_path)
    
    # Identify source version
    source_ver = "v1" if ts in ts_v1 else "v6.5"
    if source_ver == "v1":
        source_path = f"data/backtest/sessions/v1/BTCUSDT_audit_{ts}.json"
    else:
        source_path = f"data/backtest/sessions/v6.5/BTCUSDT_audit_{ts}.json"
    
    d_source = extract_detailed_audit(source_path)
    
    if d104:
        rows.append({
            'TS': ts,
            'Source': source_ver,
            'Src_Op': d_source['opinion'] if d_source else 'N/A',
            'Src_Res': d_source['result'] if d_source else 'N/A',
            'v104_Op': d104['opinion'],
            'v104_Res': d104['result'],
            'v104_MAE': d104['mae_stress']
        })

# Print formatted Markdown table
print(f"| Timestamp | Source | Src_Op | v10.4_Op | Src_Result | v10.4_Result | v10.4_MAE% |")
print(f"| :--- | :--- | :--- | :--- | :--- | :--- | :--- |")
for r in rows:
    print(f"| {r['TS']} | {r['Source']} | {r['Src_Op']} | {r['v104_Op']} | {r['Src_Res']} | {r['v104_Res']} | {r['v104_MAE']} |")
