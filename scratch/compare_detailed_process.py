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
        'price_move_pct': forensics.get('total_price_change_pct', 0) # This is move from T0 to end of window
    }

timestamps = ["20260311_040000", "20260315_190000", "20260320_110000", "20260325_030000", "20260329_190000", "20260403_110000", "20260408_030000"]
results = []

for ts in timestamps:
    v6_path = f"data/backtest/sessions/v6.5/BTCUSDT_audit_{ts}.json"
    v10_path = f"data/backtest/sessions/v10.2/audits/BTCUSDT_audit_{ts}.json"
    
    a6 = extract_detailed_audit(v6_path)
    a10 = extract_detailed_audit(v10_path)
    
    if a6 and a10:
        results.append({
            'TS': ts,
            'v6': a6,
            'v10': a10
        })

print(f"{'TS':<16} | {'v6 Op':<8} | {'v6 Res':<10} | {'v6 MFE%':<7} | {'v10 Op':<8} | {'v10 Res':<10} | {'v10 MFE%':<7}")
print("-" * 100)
for r in results:
    v6 = r['v6']
    v10 = r['v10']
    row = f"{r['TS']:<16} | {v6['opinion']:<8} | {str(v6['result']):<10} | {v6['mfe_pct']:<7.2f} | {v10['opinion']:<8} | {str(v10['result']):<10} | {v10['mfe_pct']:<7.2f}"
    print(row)

print("\n--- Process Comparison (Direction Accuracy) ---")
for r in results:
    v6 = r['v6']
    v10 = r['v10']
    # Check if opinion matched real move direction
    # price_move_pct > 0 -> Up
    actual_dir = "BULLISH" if v6['price_move_pct'] > 0 else "BEARISH"
    v6_correct = "YES" if v6['opinion'] == actual_dir else ("N/A" if v6['opinion'] == "NEUTRAL" else "NO")
    v10_correct = "YES" if v10['opinion'] == actual_dir else ("N/A" if v10['opinion'] == "NEUTRAL" else "NO")
    
    print(f"[{r['TS']}] Actual Move: {v6['price_move_pct']:.2f}% ({actual_dir})")
    print(f"  v6: Op={v6['opinion']:<8} | Correct={v6_correct:<3} | Max Floating Profit={v6['mfe_pct']:.2f}%")
    print(f"  v10: Op={v10['opinion']:<8} | Correct={v10_correct:<3} | Max Floating Profit={v10['mfe_pct']:.2f}%")
