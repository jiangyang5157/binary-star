import os
import sys
import argparse
import json
import logging
from datetime import datetime, timezone
from dotenv import load_dotenv

# Ensure project root is in path
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.agent.reviewer_agent import ReviewerAgent
from src.utils.agent_utils import load_config, add_data_root_argument, resolve_data_root
from src.utils.logger_utils import setup_logger

logger = setup_logger("ReviewerReplay")

def main():
    """
    Isolated Replay Audit Utility for Reviewer Reports.
    
    Accepts observation/strategy JSON files and triggers a direct AI audit 
    using a simulated market outcome (mock price action).
    """
    parser = argparse.ArgumentParser(description="Reviewer Replay Audit - AI Verification")
    parser.add_argument("--file", type=str, required=True, help="Path to a professional strategy session JSON")
    parser.add_argument("--save", action="store_true", help="Save the review result to the data_root")
    
    add_data_root_argument(parser)
    
    args = parser.parse_args()
    
    # Resolve data_root
    data_root = args.data_root or resolve_data_root(args.env_shortcut)
    if not data_root:
        print("Error: --data_root or environment shortcut (e.g., prod, live) must be provided.")
        sys.exit(1)

    load_dotenv()
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        logger.error("GEMINI_API_KEY not found in environment.")
        sys.exit(1)
        
    config = load_config()
    
    if not os.path.exists(args.file):
        logger.error(f"File not found: {args.file}")
        sys.exit(1)

    with open(args.file, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    # Robust Input Handling:
    # If it's a raw observation (from observer.py), wrap it.
    # Otherwise assume it's a full strategy session (from strategist.py).
    if "observation" not in data:
        logger.info("Ingesting standalone observation file. Wrapping in replay session.")
        session = {
            "observation": data,
            "draft": {"opinion": "NEUTRAL", "reasoning": "Replay data."},
            "critique": {"adversarial_tone": "REPLAY_AUDIT - Replay Mode"},
            "final_decision": {"opinion": "NEUTRAL", "reasoning": "Replay context."}
        }
    else:
        logger.info("Ingesting full strategy session file.")
        session = data

    reviewer = ReviewerAgent(config, api_key=api_key)
    
    # Forensic context construction for isolated replay
    # We use T0 assets as T1 proxies if T1 isn't available in the file
    obs = session["observation"]
    assets_raw = obs.get("visual_assets", {})
    assets = assets_raw if isinstance(assets_raw, dict) else {}
    
    # Resolve paths relative to PROJECT_ROOT
    def resolve(p):
        if not p: return None
        return p if os.path.isabs(p) else os.path.join(PROJECT_ROOT, p)

    visual_context = {
        "t0_macro": resolve(assets.get("macro_snapshot")),
        "t0_micro": resolve(assets.get("micro_snapshot")),
        "t1_macro": resolve(assets.get("macro_snapshot")), # Simplified for mock audit
        "t1_micro": resolve(assets.get("micro_snapshot")), # Simplified for mock audit
    }

    # Execute isolated review pass
    logger.info("=== Triggering Replay Reviewer AI Pass ===")
    
    # [DIAGNOSTIC MOCK EXAMPLES]
    # To test different AI reactions, you can swap the actual_outcome block below:
    # 
    # Example 1: TP_HIT (Optimistic Success)
    # mock_outcome = {
    #     "entry_price_at_t0": obs.get("price", 70000),
    #     "highest_reached_price": 72500,
    #     "lowest_reached_price": 69800,
    #     "exit_price_at_t1": 72500,
    #     "total_price_change_pct": 3.5,
    #     "max_favorable_runup_pct": 3.5,
    #     "max_adverse_drawdown_pct": -0.2,
    #     "audit_duration_candles": 12,
    #     "trade_execution_metrics": {"tp_sl_result": "TP_HIT", "mae_stress_level": "15%"}
    # }
    # 
    # Example 2: SL_HIT (Critical Failure)
    # mock_outcome = {
    #     "entry_price_at_t0": obs.get("price", 70000),
    #     "highest_reached_price": 70200,
    #     "lowest_reached_price": 68500,
    #     "exit_price_at_t1": 68500,
    #     "total_price_change_pct": -2.1,
    #     "max_favorable_runup_pct": 0.3,
    #     "max_adverse_drawdown_pct": -2.1,
    #     "audit_duration_candles": 5,
    #     "trade_execution_metrics": {"tp_sl_result": "SL_HIT", "mae_stress_level": "100%"}
    # }

    audit_result = reviewer.review(
        historical_strategy=session,
        actual_outcome={
            "entry_price_at_t0": float(obs.get("price", 0)),
            "highest_reached_price": float(obs.get("price", 0)) * 1.01,
            "lowest_reached_price": float(obs.get("price", 0)) * 0.99,
            "exit_price_at_t1": obs.get("price", 0),
            "total_price_change_pct": 0.0,
            "max_favorable_runup_pct": 1.0,
            "max_adverse_drawdown_pct": -1.0,
            "audit_duration_candles": 1,
            "trade_execution_metrics": {
                "tp_sl_result": "NEITHER",
                "mae_stress_level": "0%",
                "mae_atr_ratio": 0.0,
                "mfe_efficiency": 0.0,
                "time_efficiency_multiplier": 1.0,
                "missed_relative_range": 0.0
            }
        },
        current_observation=obs,
        visual_context=visual_context
    )
    
    # 4. Persistence
    output_dir = os.path.join(PROJECT_ROOT, data_root, "reviewers")
    os.makedirs(output_dir, exist_ok=True)
    
    # Extract metadata for standardized naming: SYMBOL_reviewers_replay_YYYYMMDD_HHMMSS.json
    observation = session.get("observation", {})
    symbol = observation.get("symbol", "UNKNOWN")
    raw_ts = observation.get("timestamp", "")
    
    import re
    match = re.search(r"(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})", raw_ts)
    if match:
        ts_str = f"{match.group(1)}{match.group(2)}{match.group(3)}_{match.group(4)}{match.group(5)}{match.group(6)}"
    else:
        ts_str = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

    output_filename = f"{symbol}_reviewers_replay_{ts_str}.json"
    output_path = os.path.join(output_dir, output_filename)
    
    # Standardized record format (Omitting redundant top-level symbol)
    final_record = {
        "audit_timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "strategy_session": session,
        "market_outcome": {
            "trade_execution_metrics": {}
        },
        "audit_findings": audit_result
    }

    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(final_record, f, indent=2, ensure_ascii=False)
    
    logger.info(f"Audit complete. Results saved to: {output_path}")
    print("\n--- AI AUDIT FINDINGS ---")
    print(json.dumps(audit_result, indent=2, ensure_ascii=False))

if __name__ == "__main__":
    main()
