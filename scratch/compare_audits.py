import os
import json
from collections import Counter

def analyze_audits(audit_dir):
    if not os.path.exists(audit_dir):
        return f"Directory {audit_dir} not found."
    
    results = []
    opinions = []
    timestamps = []
    rr_ratios = []
    confidences = []
    holding_hours = []
    
    for f in os.listdir(audit_dir):
        if f.endswith(".json"):
            try:
                with open(os.path.join(audit_dir, f), 'r') as file:
                    data = json.load(file)
                    outcome = data.get("market_outcome", {})
                    res = outcome.get("tp_sl_result", "UNKNOWN")
                    results.append(res)
                    
                    session = data.get("session", {})
                    decision = session.get("final_decision", {})
                    opinion = decision.get("opinion", "UNKNOWN")
                    opinions.append(opinion)
                    
                    params = decision.get("tactical_parameters", {})
                    rr = params.get("rr_ratio")
                    if rr is not None: rr_ratios.append(rr)
                    
                    conf = decision.get("confidence_score")
                    if conf is not None: confidences.append(conf)
                    
                    hold = params.get("projected_holding_hours")
                    if hold is not None: holding_hours.append(hold)
                    
                    obs = session.get("observation", {})
                    ts = obs.get("observed_at", "")
                    if ts:
                        timestamps.append(ts)
            except Exception as e:
                print(f"Error parsing {f}: {e}")
                
    res_counts = Counter(results)
    op_counts = Counter(opinions)
    
    total = len(results)
    if total == 0:
        return "No audit files found."
        
    summary = f"Audit Analysis for {audit_dir}:\n"
    summary += f"Total Sessions: {total}\n"
    if timestamps:
        summary += f"Time Range: {min(timestamps)} to {max(timestamps)}\n"
    summary += "Outcome Counts:\n"
    for res, count in res_counts.items():
        summary += f"  - {res}: {count} ({count/total*100:.1f}%)\n"
    
    if rr_ratios:
        summary += f"Avg RR Ratio: {sum(rr_ratios)/len(rr_ratios):.2f}\n"
    if confidences:
        summary += f"Avg Confidence: {sum(confidences)/len(confidences):.1f}\n"
    if holding_hours:
        summary += f"Avg Holding Hours: {sum(holding_hours)/len(holding_hours):.1f}\n"
        
    summary += "Opinion Counts:\n"
    for op, count in op_counts.items():
        summary += f"  - {op}: {count} ({count/total*100:.1f}%)\n"
        
    return summary

print(analyze_audits("data/prod/audits"))
print("\n" + "="*40 + "\n")
print(analyze_audits("data/backtest/v18_r50/audits"))
