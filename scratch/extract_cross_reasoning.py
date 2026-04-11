import json
import os

def extract_reasoning(filepath):
    if not os.path.exists(filepath): return None
    try:
        with open(filepath, 'r') as f: data = json.load(f)
    except: return None
    
    # Audit files have 'session' key, Session files don't
    sess = data.get('session') if 'session' in data else data
    fd = sess.get('final_decision', {})
    tp = fd.get('tactical_parameters', {})
    return {
        'opinion': fd.get('opinion'),
        'tp': tp.get('take_profit'),
        'sl': tp.get('stop_loss'),
        'entry': tp.get('entry'),
        'reasoning': fd.get('reasoning_chain'),
        'critic': fd.get('critic_impact')
    }

targets = [
    {"ts": "20260325_030000", "versions": ["v1", "v6.5", "v9.1", "v10.2"]},
    {"ts": "20260403_110000", "versions": ["v1", "v6.5", "v9.1", "v10.1", "v10.2"]},
    {"ts": "20260323_050000", "versions": ["v1", "v9.1", "v10.1", "v10.3"]}
]

all_data = {}

for target in targets:
    ts = target['ts']
    all_data[ts] = {}
    for v in target['versions']:
        # Map paths based on version structure
        if v == 'v9.1':
            path = f"data/backtest/sessions/{v}/sessions/BTCUSDT_session_{ts}.json"
        elif v in ['v10.1', 'v10.2', 'v10.3']:
            path = f"data/backtest/sessions/{v}/sessions/BTCUSDT_session_{ts}.json"
        else:
            path = f"data/backtest/sessions/{v}/BTCUSDT_session_{ts}.json"
        
        data = extract_reasoning(path)
        if data:
            all_data[ts][v] = data

# Print summaries for analysis
for ts, versions in all_data.items():
    print(f"\n{'='*50}\nTIMESTAMP: {ts}\n{'='*50}")
    for v, d in versions.items():
        print(f"[{v}] Opinion: {d['opinion']} | Entry: {d['entry']} | TP: {d['tp']} | SL: {d['sl']}")
        print(f"Reasoning: {d['reasoning'][:300]}...")
        if d['critic']:
            print(f"Critic Impact: {d['critic'][:200]}...")
        print("-" * 30)
