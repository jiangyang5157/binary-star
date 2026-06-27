#!/usr/bin/env python3
import os
import sys
import argparse
import logging
import concurrent.futures
import multiprocessing
from dotenv import load_dotenv

# Ensure project root is in path
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# Load environment before any logic
load_dotenv()

from src.analyzer.audit_controller import AuditController
from src.utils.pipeline_utils import add_data_path_argument
from src.utils.path_utils import resolve_project_root
from src.utils.logger_utils import setup_logger
from src.utils.datetime_utils import format_timestamp_for_filename

# Global logger reference
logger = None

def process_audit_file(file_path: str, controller: AuditController, data_root: str, force: bool = False) -> str:
    """Handles the full lifecycle of a single session audit."""
    try:
        logger.info(f"auditing | file={os.path.basename(file_path)}")

        # 1. Deduplication Gate: Skip if file already exists (unless forced)
        import json
        with open(file_path, 'r', encoding='utf-8') as f:
            session = json.load(f)

        obs = session.get("observation", {})
        symbol = obs.get("symbol", "UNKNOWN")
        obs_ts = obs.get("observed_at")
        ts_compact = format_timestamp_for_filename(obs_ts)

        if not force and controller.is_already_audited(symbol, ts_compact):
            logger.info(f"skipped | file={os.path.basename(file_path)} | reason=exists")
            return "EXISTS"

        # 2. Execute Analysis (Standardized 3-key Bundle: session, market_outcome, metadata)
        audit_bundle = controller.run_manual_audit(file_path, force=force)

        # 3. Automated Persistence
        report_path = controller.save_report(audit_bundle)

        outcome = audit_bundle.get('market_outcome', {})
        result_str = outcome.get('tp_sl_result', 'N/A')

        # 4. Standardized Audit Output
        print(f"🔍 AUDIT COMPLETE | {symbol} | {result_str} | {os.path.basename(report_path)}")
        return "SUCCESS"
    except Exception as e:
        if "SESSION_MATURING" in str(e):
            logger.info(f"skipped | file={os.path.basename(file_path)} | reason=maturing")
            return "MATURING"
        if "EMPTY_KLINES" in str(e):
            logger.info(f"skipped | file={os.path.basename(file_path)} | reason=empty")
            return "EMPTY"
        logger.error(f"audit failed | file={file_path} | error={e}")
        return "FAILED"

# --- Multiprocessing Glue ---
controller = None
def worker_init(log_path, config, data_root):
    global logger, controller
    setup_logger("", log_file=log_path,
                 max_bytes=10 * 1024 * 1024, backup_count=5)
    logger = logging.getLogger("AuditWorker")
    controller = AuditController(config_dict=config, data_root=data_root, logger=logger)

def run_task(args_tuple):
    """Wrapper to call process_audit_file with global controller."""
    f, data_root, force = args_tuple
    global controller
    return process_audit_file(f, controller, data_root, force=force)

def main():
    parser = argparse.ArgumentParser(description="Singularity Forensic Auditor")
    parser.add_argument("--file", "-f", help="Optional: Path to a specific session JSON file")
    parser.add_argument("--symbol", type=str, help="Optional: Filter batch audit by symbol prefix (e.g. BTC)")
    parser.add_argument("--force", action="store_true", help="Bypass deduplication and maturity checks")
    
    add_data_path_argument(parser, required=True)
    
    args = parser.parse_args()
    
    # 1. Resolve Project Root and Data Root
    root = resolve_project_root()
    data_root = args.path
    
    # 2. Load context-aware configuration (Unified merge)
    from src.utils.pipeline_utils import load_combined_config
    config = load_combined_config()
    
    # 3. Setup system-wide logging with physical persistence in data_root
    # Root-level configuration catches all sub-modules (Assembler, Observer, Notifier, etc.)
    global logger
    log_path = os.path.join(data_root, "audit.log")
    setup_logger("", log_file=log_path,
                 max_bytes=10 * 1024 * 1024, backup_count=5)
    logger = logging.getLogger("Audit")
    
    # 4. Initialize the Audit Controller (The Orchestrator)
    controller = AuditController(config_dict=config, data_root=data_root, logger=logger)
    
    # 5. Execution Branch: Batch vs Single
    files_to_audit = []
    success_count = 0
    skip_count = 0
    mature_count = 0
    empty_count = 0
    fail_count = 0
    if args.file:
        if not os.path.exists(args.file):
            logger.error(f"target file not found | file={args.file}")
            sys.exit(1)
        files_to_audit.append(args.file)
    else:
        # Batch Mode: Scan data_root/sessions
        sessions_dir = os.path.join(root, data_root, "sessions")
        if not os.path.exists(sessions_dir):
            logger.error(f"sessions directory not found | path={sessions_dir}")
            sys.exit(1)
            
        logger.info(f"batch scanning | path={sessions_dir}")
        files_to_audit = [os.path.join(sessions_dir, f) for f in os.listdir(sessions_dir) if f.endswith(".json")]
        
        # Resolve symbol: optional filter, prefix format
        symbol = None
        if args.symbol:
            from src.utils.symbol_utils import resolve_symbol
            symbol = resolve_symbol(args.symbol)
        
        if symbol:
            logger.info(f"filtering batch | symbol={symbol}")
            files_to_audit = [f for f in files_to_audit if os.path.basename(f).startswith(f"{symbol}_")]
            
        files_to_audit.sort() # Process in chronological order
        
    if not files_to_audit:
        logger.warning(f"no sessions found | path={data_root}")
        return

    # 5. Parallel Execution Core
    print(f"🚀 Launching Parallel Audit Pool (Workers: {multiprocessing.cpu_count() or 1})...")
    
    # Pack arguments for top-level run_task
    task_args = [(f, data_root, args.force) for f in files_to_audit]

    with concurrent.futures.ProcessPoolExecutor(
        max_workers=multiprocessing.cpu_count(),
        initializer=worker_init,
        initargs=(log_path, config, data_root)
    ) as executor:
        results = list(executor.map(run_task, task_args))

    for status in results:
        if status == "SUCCESS": success_count += 1
        elif status == "EXISTS": skip_count += 1
        elif status == "MATURING": mature_count += 1
        elif status == "EMPTY": empty_count += 1
        else: fail_count += 1
            
    print("\n" + "="*60)
    print(f" BATCH AUDIT SUMMARY")
    print("="*60)
    print(f" TOTAL SESSIONS : {len(files_to_audit)}")
    print(f" COMPLETED      : {success_count}")
    print(f" ALREADY EXISTS : {skip_count}")
    print(f" EMPTY (NO DATA): {empty_count}")
    print(f" MATURING (WAIT): {mature_count}")
    print(f" FAILED         : {fail_count}")
    print("="*60 + "\n")

if __name__ == "__main__":
    main()
