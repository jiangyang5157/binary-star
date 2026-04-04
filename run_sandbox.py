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
from src.utils.pipeline_utils import resolve_data_root, add_data_root_argument
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
    symbol = metadata.get("symbol", "BTCUSDT")
    failure_case_filename = metadata.get("primary_failure_case")
    
    if not failure_case_filename:
        logger.error(f"Proposal metadata missing 'primary_failure_case'. Cannot replay.")
        sys.exit(1)
        
    # 3. Load Failure Case (The Audit Report)
    audit_file = os.path.join(data_root, "audits", failure_case_filename)
    if not os.path.exists(audit_file):
        logger.error(f"Audit report not found at {audit_file}. Metadata reference may be stale.")
        sys.exit(1)
        
    failure_case = load_json(audit_file)
    
    # 4. Setup Directories
    base_dir = os.path.join(data_root, "evolution")
    dirs = {
        "sandbox": os.path.join(base_dir, "sandbox_results"),
        "accepted": os.path.join(base_dir, "sandbox_accepted"),
        "rejected": os.path.join(base_dir, "sandbox_rejected")
    }
    for d in dirs.values():
        os.makedirs(d, exist_ok=True)
        
    # 5. Run Sandbox Validation
    load_dotenv()
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        logger.critical("GEMINI_API_KEY Missing.")
        sys.exit(1)
        
    logger.info(f"Sandbox: Initializing validation for {os.path.basename(args.file)}...")
    sandbox = EvolverSandbox(api_key, data_root_rel) # EvolverSandbox expects relative data_root
    
    validation = sandbox.validate_evolution(
        failure_case=failure_case,
        proposed_patch=proposal.get('config_patch'),
        proposed_prompts=proposal.get('semantic_refinement')
    )
    is_valid = validation.get('is_validated', False)
    
    # 6. Save Sandbox Result
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    sandbox_id = f"{symbol}_evolution_sandbox_{timestamp}"
    sandbox_file = os.path.join(dirs['sandbox'], f"{sandbox_id}.json")
    save_json(validation, sandbox_file)
    
    # 7. Routing
    if is_valid:
        logger.info(f"Sandbox: [PASS] Routing proposal to 'sandbox_accepted'...")
        target_file = os.path.join(dirs['accepted'], os.path.basename(args.file))
        shutil.move(args.file, target_file)
        print(f"✅ Sandbox Passed | Result: {sandbox_file} | Proposal moved to accepted.")
    else:
        logger.warning(f"Sandbox: [FAIL] Routing proposal to 'sandbox_rejected'...")
        target_file = os.path.join(dirs['rejected'], os.path.basename(args.file))
        shutil.move(args.file, target_file)
        print(f"❌ Sandbox Failed | Result: {sandbox_file} | Proposal moved to rejected.")

if __name__ == "__main__":
    main()
