import json
import os
import pandas as pd

def extract_audit_data(filepath):
    if not os.path.exists(filepath):
        return None
    try:
        with open(filepath, 'r') as f:
            data = json.load(f)
    except Exception as e:
        print(f"Error reading {filepath}: {e}")
        return None
    
    outcome = data.get('market_outcome', {})
    exec_forensics = outcome.get('execution_forensics', {})
    trade_metrics = outcome.get('trade_execution_metrics', {})
    
    # Handle cases where trade_metrics might be None or simplified for NEUTRAL/NOT_FILLED
    if trade_metrics is None:
        trade_metrics = {}
    if exec_forensics is None:
        exec_forensics = {}
    
    return {
        'result': outcome.get('tp_sl_result'),
        'mae_atr': exec_forensics.get('theoretical_mae_atr', 'N/A'),
        'mfe_atr': exec_forensics.get('theoretical_mfe_atr', 'N/A'),
        'mae_stress': trade_metrics.get('mae_stress_level_pct', 'N/A'),
        'mfe_eff': trade_metrics.get('mfe_efficiency_pct', 'N/A'),
        'filled': outcome.get('is_filled', False)
    }

timestamps = [
    "20260323_050000",
    "20260325_030000",
    "20260325_190000",
    "20260326_230000",
    "20260329_130000",
    "20260403_110000",
    "20260408_030000"
]

results = []

for ts in timestamps:
    v9_file = f"data/backtest/sessions/v9.1/audits/BTCUSDT_audit_{ts}.json"
    v10_file = f"data/backtest/sessions/v10.1/audits/BTCUSDT_audit_{ts}.json"
    
    v9_audit = extract_audit_data(v9_file)
    v10_audit = extract_audit_data(v10_file)
    
    if v9_audit and v10_audit:
        results.append({
            'Timestamp': ts,
            'v9_Result': v9_audit['result'],
            'v10_Result': v10_audit['result'],
            'v9_MAE_STR': v9_audit['mae_stress'],
            'v10_MAE_STR': v10_audit['mae_stress'],
            'v9_MFE_EFF': v9_audit['mfe_eff'],
            'v10_MFE_EFF': v10_audit['mfe_eff'],
            'v9_Filled': v9_audit['filled'],
            'v10_Filled': v10_audit['filled']
        })

# Printing comparison table
header = f"{'TS':<16} | {'v9 Result':<10} | {'v10 Result':<10} | {'v9 MAE %':<8} | {'v10 MAE %':<8} | {'v9 MFE %':<8} | {'v10 MFE %':<8}"
print(header)
print("-" * len(header))
for r in results:
    v9_res = r['v9_Result'] if r['v9_Filled'] or r['v9_Result'] == 'NEUTRAL' else "NOT_FILLED"
    v10_res = r['v10_Result'] if r['v10_Filled'] or r['v10_Result'] == 'NEUTRAL' else "NOT_FILLED"
    row = f"{r['Timestamp']:<16} | {str(v9_res):<10} | {str(v10_res):<10} | {str(r['v9_MAE_STR']):<8} | {str(r['v10_MAE_STR']):<8} | {str(r['v9_MFE_EFF']):<8} | {str(r['v10_MFE_EFF']):<8}"
    print(row)
