#!/usr/bin/env python3
import os
import sys
import argparse
import logging
from datetime import datetime, timezone

# Ensure project root is in path
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.analyzer.audit_controller import AuditController
from src.utils.pipeline_utils import load_config
from src.utils.logger_utils import setup_logger

# v6.10: Global logger reference (will be properly initialized with file persistence)
logger = None

def process_audit_file(file_path: str, controller: AuditController, email: bool, data_root: str, force: bool = False) -> str:
    """Handles the full lifecycle of a single session audit."""
    try:
        logger.info(f"--- Initiating Audit Review: {os.path.basename(file_path)} ---")
        
        # 1. Deduplication Gate: Skip if file already exists (unless forced)
        import json
        with open(file_path, 'r', encoding='utf-8') as f:
            session = json.load(f)
        
        symbol = session.get("observation", {}).get("symbol", "UNKNOWN")
        obs_ts = session["observation"]["observed_at"]
        ts_compact = obs_ts.replace("-", "").replace(":", "").replace("T", "_").split(".")[0].split("+")[0].replace("Z", "")
        
        if not force and controller.is_already_audited(symbol, ts_compact):
            logger.info(f"🔍 [EXISTS] Skipped: {os.path.basename(file_path)} already has a audit report.")
            return "EXISTS"

        # 2. Execute Analysis
        result = controller.run_manual_audit(file_path, force=force)
        
        # 2. Automated Persistence
        report_path = controller.save_report(result)
        
        # 3. Notification Logic
        from src.infrastructure.notifications.email_notifier import SessionNotifier
        notifier = SessionNotifier(data_root=data_root)
        
        # Reconstruct structural bundle for notifier (v6.12 alignment)
        audit_result = {
            "session": result["session"],
            "market_outcome": result["outcome"],
            "metadata": result.get("metadata", {}),
            "audit_timestamp": result.get("audit_timestamp_compact")
        }
        
        # Decision: Notification control (只有当系统有交易意向时才发送邮件报告)
        should_dispatch = email and session.get("final_decision", {}).get("opinion", "").upper() != "NEUTRAL"
        notifier.notify_audit(result["symbol"], audit_result, save_local=True, dispatch_email=should_dispatch)

        outcome = result.get('outcome', {})
        
        # 4. Standardized Audit Output
        print(f"🔍 AUDIT COMPLETE | {result.get('symbol', 'UNKNOWN')} | {outcome.get('tp_sl_result', 'N/A')} | {report_path}")
        return "SUCCESS"
    except Exception as e:
        if "SESSION_MATURING" in str(e):
            logger.info(f"⏳ [WAITING] Skipped: {os.path.basename(file_path)} is still maturing. {e}")
            return "MATURING"
        logger.error(f"Failed to audit {file_path}: {e}")
        return "FAILED"

def main():
    parser = argparse.ArgumentParser(description="Singularity Forensic Audit Review (v6.1)")
    parser.add_argument("--file", help="Optional: Path to a specific session JSON file")
    parser.add_argument("--email", action="store_true", help="Dispatch forensic reports via email")
    parser.add_argument("--force", action="store_true", help="Bypass deduplication and maturity checks")
    
    from src.utils.pipeline_utils import add_data_root_argument, resolve_data_root
    add_data_root_argument(parser)
    
    args = parser.parse_args()
    
    # 1. Resolve Data Root
    data_root = args.data_root or resolve_data_root(args.env_shortcut)
    
    # 2. Load context-aware configuration (Unified merge)
    from src.utils.pipeline_utils import load_combined_config
    config = load_combined_config()
    
    # 3. Setup system-wide logging with physical persistence in data_root
    # Root-level configuration catches all sub-modules (Assembler, Observer, Notifier, etc.)
    global logger
    log_path = os.path.join(data_root, "audit.log")
    setup_logger("", log_file=log_path)
    logger = logging.getLogger("Audit")
    
    # 4. Initialize the Audit Controller (The Orchestrator)
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
    skip_count = 0
    fail_count = 0
    mature_count = 0
    
    for f in files_to_audit:
        status = process_audit_file(f, controller, args.email, data_root, force=args.force)
        if status == "SUCCESS": success_count += 1
        elif status == "EXISTS": skip_count += 1
        elif status == "MATURING": mature_count += 1
        else: fail_count += 1
            
    print("\n" + "="*60)
    print(f" BATCH AUDIT SUMMARY")
    print("="*60)
    print(f" TOTAL SESSIONS : {len(files_to_audit)}")
    print(f" COMPLETED      : {success_count}")
    print(f" ALREADY EXISTS : {skip_count}")
    print(f" MATURING (WAIT): {mature_count}")
    print(f" FAILED         : {fail_count}")
    print("="*60 + "\n")

if __name__ == "__main__":
    main()
