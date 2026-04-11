import json
import os
import glob
import pandas as pd

def extract_session_data(filepath):
    if not os.path.exists(filepath):
        return None
    try:
        with open(filepath, 'r') as f:
            data = json.load(f)
    except Exception as e:
        print(f"Error reading {filepath}: {e}")
        return None
    
    final_decision = data.get('final_decision', {})
    tactical = final_decision.get('tactical_parameters', {})
    
    return {
        'opinion': final_decision.get('opinion'),
        'confidence': final_decision.get('confidence_score'),
        'entry': tactical.get('entry'),
        'sl': tactical.get('stop_loss'),
        'tp': tactical.get('take_profit'),
        'rr': tactical.get('rr_ratio'),
        'reasoning': final_decision.get('reasoning_chain', '')[:300]
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
    v9_file = f"data/backtest/sessions/v9.1/sessions/BTCUSDT_session_{ts}.json"
    v10_file = f"data/backtest/sessions/v10.1/sessions/BTCUSDT_session_{ts}.json"
    
    v9_data = extract_session_data(v9_file)
    v10_data = extract_session_data(v10_file)
    
    if v9_data and v10_data:
        results.append({
            'Timestamp': ts,
            'v9_Opinion': v9_data['opinion'],
            'v10_Opinion': v10_data['opinion'],
            'v9_Conf': v9_data['confidence'],
            'v10_Conf': v10_data['confidence'],
            'v9_RR': v9_data['rr'],
            'v10_RR': v10_data['rr'],
            'v9_Entry': v9_data['entry'],
            'v10_Entry': v10_data['entry'],
            'v9_Reasoning': v9_data['reasoning'],
            'v10_Reasoning': v10_data['reasoning']
        })

# Manual printing since tabulate is missing
header = f"{'TS':<16} | {'v9 Op':<8} | {'v10 Op':<8} | {'v9 RR':<5} | {'v10 RR':<5} | {'v9 Conf':<7} | {'v10 Conf':<7}"
print(header)
print("-" * len(header))
for r in results:
    row = f"{r['Timestamp']:<16} | {str(r['v9_Opinion']):<8} | {str(r['v10_Opinion']):<8} | {str(r['v9_RR']):<5} | {str(r['v10_RR']):<5} | {str(r['v9_Conf']):<7} | {str(r['v10_Conf']):<7}"
    print(row)

print("\n--- Reasoning Comparison ---")
for r in results:
    print(f"\n[{r['Timestamp']}]")
    print(f"v9:  {r['v9_Reasoning']}...")
    print(f"v10: {r['v10_Reasoning']}...")
