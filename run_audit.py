#!/usr/bin/env python3
import os
import sys
import argparse
from datetime import datetime, timezone

# Ensure project root is in path
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.analyzer.audit_controller import AuditController
from src.utils.pipeline_utils import load_config
from src.utils.logger_utils import setup_logger

# Initialize standard hardened logger
logger = setup_logger("AuditEntry")

def process_audit_file(file_path: str, controller: AuditController, email: bool, data_root: str):
    """Executes the complete forensic audit pipeline for a single session file."""
    try:
        logger.info(f"--- Initiating Audit Review: {os.path.basename(file_path)} ---")
        
        # 1. Execute Analysis
        result = controller.run_manual_audit(file_path)
        
        # 2. Automated Persistence
        report_path = controller.save_report(result)
        
        # 3. Email Notification & HTML Preview
        from src.infrastructure.notifications.email_notifier import SessionNotifier
        notifier = SessionNotifier(data_root=data_root)
        
        # Reconstruct high-fidelity bundle for notifier
        # v6.1: Structural alignment - metadata is managed within AuditController
        audit_result = {
            "strategy_session": result["session"],
            "market_outcome": result["outcome"],
            "audit_findings": result["report"],
            "audit_metadata": result.get("audit_metadata", {})
        }
        notifier.notify_audit(result["symbol"], audit_result, save_local=True, dispatch_email=email)

        outcome = result.get('outcome', {})
        
        # 4. Standardized Audit Output
        print(f"🔍 AUDIT COMPLETE | {result.get('symbol', 'UNKNOWN')} | {outcome.get('tp_sl_result', 'N/A')} | {report_path}")
        return True
    except Exception as e:
        logger.error(f"Failed to audit {file_path}: {e}")
        return False

def main():
    parser = argparse.ArgumentParser(description="Singularity Forensic Audit Review (v6.1)")
    parser.add_argument("--file", help="Optional: Path to a specific session JSON file")
    parser.add_argument("--email", action="store_true", help="Dispatch forensic reports via email")
    
    from src.utils.pipeline_utils import add_data_root_argument, resolve_data_root
    add_data_root_argument(parser)
    
    args = parser.parse_args()
    
    # 1. Resolve Data Root
    data_root = args.data_root or resolve_data_root(args.env_shortcut)
    
    # 2. Load context-aware configuration
    config = load_config()
    
    # 3. Initialize the Audit Controller (The Orchestrator)
    controller = AuditController(config_dict=config, logger=logger, data_root=data_root)
    
    # 4. Execution Branch: Batch vs Single
    files_to_audit = []
    if args.file:
        if not os.path.exists(args.file):
            logger.error(f"Target file not found: {args.file}")
            sys.exit(1)
        files_to_audit.append(args.file)
    else:
        # Batch Mode: Scan data_root/sessions
        sessions_dir = os.path.join(PROJECT_ROOT, data_root, "sessions")
        if not os.path.exists(sessions_dir):
            logger.error(f"Sessions directory not found: {sessions_dir}")
            sys.exit(1)
            
        logger.info(f"Batch Mode: Scanning for sessions in {sessions_dir}...")
        files_to_audit = [os.path.join(sessions_dir, f) for f in os.listdir(sessions_dir) if f.endswith(".json")]
        files_to_audit.sort() # Process in chronological order
        
    if not files_to_audit:
        logger.warning(f"No sessions found to audit in {data_root}.")
        return

    logger.info(f"Starting audit sequence for {len(files_to_audit)} session(s)...")
    
    success_count = 0
    for f in files_to_audit:
        if process_audit_file(f, controller, args.email, data_root):
            success_count += 1
            
    print("\n" + "="*60)
    print(f" BATCH AUDIT SUMMARY")
    print("="*60)
    print(f" TOTAL SESSIONS : {len(files_to_audit)}")
    print(f" SUCCESSFUL     : {success_count}")
    print(f" FAILED         : {len(files_to_audit) - success_count}")
    print("="*60 + "\n")

if __name__ == "__main__":
    main()
