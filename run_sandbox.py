#!/usr/bin/env python3
import os
import sys
import json
import shutil
import logging
import argparse
from datetime import datetime
from dotenv import load_dotenv

# Setup absolute project paths
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.agent.evolver_sandbox import EvolverSandbox
from src.utils.pipeline_utils import resolve_data_root, add_data_root_argument, load_combined_config
from src.utils.json_utils import load_json, save_json
from src.utils.logger_utils import setup_logger

def main():
    parser = argparse.ArgumentParser(description="Singularity Standalone Shadow Sandbox (v6.1)")
    parser.add_argument("--file", required=True, help="Path to the evolution proposal JSON file")
    add_data_root_argument(parser)
    
    args = parser.parse_args()
    
    # 1. Resolve Data Root and Setup Logging
    data_root_rel = args.data_root or resolve_data_root(args.env_shortcut)
    data_root = os.path.join(PROJECT_ROOT, data_root_rel)
    
    log_path = os.path.join(data_root, "sandbox_run.log")
    setup_logger("", log_file=log_path)
    logger = logging.getLogger("SandboxRunner")
    
    # 2. Load Proposal
    if not os.path.exists(args.file):
        logger.error(f"Proposal file not found: {args.file}")
        sys.exit(1)
        
    proposal = load_json(args.file)
    metadata = proposal.get("metadata", {})
    symbol = metadata['symbol']
    audit_reports_list = metadata.get("audit_reports", [])
    
    if not audit_reports_list:
        logger.error(f"Proposal metadata missing 'audit_reports' list. Cannot perform batch validation.")
        sys.exit(1)
        
    # 3. Load All Audit Reports
    reports = []
    for filename in audit_reports_list:
        audit_file = os.path.join(data_root, "audits", filename)
        if os.path.exists(audit_file):
            report = load_json(audit_file)
            if report:
                reports.append(report)
        else:
            logger.warning(f"Audit report not found: {filename}. Skipping.")

    if not reports:
        logger.error("No valid audit reports found to validate against.")
        sys.exit(1)
        
    # 4. Setup Directories
    base_dir = os.path.join(data_root, "evolution")
    dirs = {
        "sandbox": os.path.join(base_dir, "sandbox_results"),
        "accepted": os.path.join(base_dir, "sandbox_accepted"),
        "rejected": os.path.join(base_dir, "sandbox_rejected")
    }
    for d in dirs.values():
        os.makedirs(d, exist_ok=True)
        
    # 5. Run Batch Sandbox Validation
    load_dotenv()
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        logger.critical("GEMINI_API_KEY Missing.")
        sys.exit(1)
        
    full_config = load_combined_config()
    sandbox = EvolverSandbox(
        api_key=api_key, 
        data_root=data_root_rel, 
        config_dict=full_config
    )
    
    validation = sandbox.run_batch_validation(
        audit_reports=reports,
        config_patch=proposal.get('config_patch'),
        instruction_patch=proposal.get('semantic_refinement')
    )
    is_accepted = validation.get('is_accepted', False)
    
    # 6. Save Detailed Sandbox Result
    evolver_at = metadata["evolver_at"]
    # v6.12: Unified forensic timestamp conversion (ISO -> YYYYMMDD_HHMMSS)
    ts_compact = evolver_at.replace("-", "").replace(":", "").replace("T", "_").split(".")[0].split("+")[0]
    
    sandbox_id = f"{symbol}_evolution_sandbox_{ts_compact}"
    sandbox_file = os.path.join(dirs['sandbox'], f"{sandbox_id}.json")
    save_json(validation, sandbox_file)
    
    # 8. Routing
    if is_accepted:
        logger.info(f"Sandbox: [PASS] Routing proposal to 'sandbox_accepted' ({len(validation.get('accepted_cases', []))}/{len(reports)} cases accepted)")
        target_file = os.path.join(dirs['accepted'], os.path.basename(args.file))
        shutil.move(args.file, target_file)
        print(f"✅ Sandbox Passed | Result: {sandbox_file} | Proposal moved to accepted.")
    else:
        logger.warning(f"Sandbox: [FAIL] Routing proposal to 'sandbox_rejected' ({len(validation.get('rejected_cases', []))}/{len(reports)} cases rejected)")
        target_file = os.path.join(dirs['rejected'], os.path.basename(args.file))
        shutil.move(args.file, target_file)
        print(f"❌ Sandbox Failed | Result: {sandbox_file} | Proposal moved to rejected.")

if __name__ == "__main__":
    main()
