#!/usr/bin/env python3
import os
import sys
import argparse
import logging

# Ensure project root is in path
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.analyzer.audit_controller import AuditController
from src.utils.pipeline_utils import load_config
from src.utils.logger_utils import setup_logger

# Initialize standard hardened logger
logger = setup_logger("AuditEntry")

def main():
    parser = argparse.ArgumentParser(description="Official Singularity Audit Review Entry (v5.12)")
    parser.add_argument("--file", required=True, help="Path to the strategy/session JSON file for audit review")
    parser.add_argument("--email", action="store_true", help="Dispatch audit report via email")
    
    from src.utils.pipeline_utils import add_data_root_argument, resolve_data_root
    add_data_root_argument(parser)
    
    args = parser.parse_args()
    
    # 1. Resolve Data Root
    data_root = args.data_root or resolve_data_root(args.env_shortcut)
    
    if not os.path.exists(args.file):
        logger.error(f"Target file not found: {args.file}")
        sys.exit(1)

    # 2. Load context-aware configuration
    config = load_config()
    
    # 3. Initialize the Audit Controller (The Orchestrator)
    controller = AuditController(config_dict=config, logger=logger)
    
    try:
        logger.info(f"--- Initiating Audit Review for: {args.file} ---")
        
        # 4. Execute Analysis
        result = controller.run_manual_audit(args.file)
        
        # 5. --- v5.10 PHYSICAL HARDENING: Automated Persistence ---
        report_path = controller.save_report(result)
        
        # 6. Optional Email Notification & HTML Preview
        if args.email:
            from src.infrastructure.notifications.email_notifier import SessionNotifier
            from datetime import datetime, timezone
            notifier = SessionNotifier(data_root=data_root)
            
            # Reconstruct bundle for notifier
            bundle = {
                "strategy_session": result["session"],
                "market_outcome": result["outcome"],
                "audit_findings": result["report"],
                "audit_timestamp": datetime.now(timezone.utc).isoformat()
            }
            # notify_review internally calls save_html_preview with the new v5.10 naming
            notifier.notify_review(result["symbol"], bundle, save_local=True)
            print(f"Notifier: Audit email dispatched and HTML preview generated.")

        outcome = result.get('outcome', {})
        report = result.get('report', {})
        
        # 7. Standardized Audit Output
        print("\n" + "🔍 " + "="*60)
        print(f" SINGULARITY AUDIT REPORT | {result.get('symbol', 'UNKNOWN')}")
        print("="*64)
        print(f" REPORT SAVED : {report_path}")
        print(f" RESULT       : {outcome.get('tp_sl_result', 'N/A')}")
        print(f" IS_FILLED    : {outcome.get('is_filled', False)}")
        
        status = report.get('audit_status', {})
        print(f"\n JUSTICE      : {'JUSTIFIED SURRENDER' if status.get('is_justified_surrender') else 'UNJUSTIFIED (LOGIC GAP)'}")
        print(f" MAE STRESS   : {status.get('mae_stress_tier', 'N/A')}")
        
        if outcome.get('is_filled'):
            m = outcome.get('trade_execution_metrics', {})
            print(f" MAE %        : {m.get('mae_stress_level_pct', 0)}%")
            print(f" MFE %        : {m.get('mfe_efficiency_pct', 0)}%")
        
        print("\n" + "="*64 + "\n")
        
    except Exception as e:
        logger.error(f"Audit Review Failed: {e}", exc_info=True)
        sys.exit(1)

if __name__ == "__main__":
    main()
