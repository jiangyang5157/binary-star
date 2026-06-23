#!/usr/bin/env python3
import os
import sys
import shutil
import logging
import argparse
from dotenv import load_dotenv

# Setup absolute project paths - Move up one level since we are in tools/
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.agent.evolver_sandbox import EvolverSandbox
from src.utils.pipeline_utils import add_data_path_argument, load_combined_config
from src.utils.json_utils import load_json, save_json
from src.utils.path_utils import resolve_project_root
from src.utils.logger_utils import setup_logger

def main():
    parser = argparse.ArgumentParser(description="Singularity Online Shadow Sandbox")
    parser.add_argument("--file", "-f", required=True, help="Path to the evolution proposal JSON file")
    add_data_path_argument(parser, required=True)
    
    args = parser.parse_args()
    
    # 1. Resolve Project Root and Data Root
    root = resolve_project_root()
    data_root_rel = args.path
    data_root = os.path.join(root, data_root_rel)
    
    log_path = os.path.join(data_root, "sandbox_online.log")
    setup_logger("", log_file=log_path)
    logger = logging.getLogger("SandboxOnline")
    
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
    from src.utils.pipeline_utils import resolve_api_key
    api_key = resolve_api_key()
    if not api_key:
        logger.critical("API_KEY not found for active provider.")
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
    # Unified forensic timestamp conversion (ISO -> YYYYMMDD_HHMMSS)
    ts_compact = evolver_at.replace("-", "").replace(":", "").replace("T", "_").split(".")[0].split("+")[0]
    
    sandbox_id = f"{symbol}_evolution_sandbox_{ts_compact}"
    sandbox_file = os.path.join(dirs['sandbox'], f"{sandbox_id}.json")
    save_json(validation, sandbox_file)
    
    # 8. Summary & Routing
    # Simplified Selection Rule - New logic is accepted if IMPROVED > BROKEN (Net Improvement)
    
    accepted_cases = validation.get('accepted_cases', [])
    rejected_cases = validation.get('rejected_cases', [])
    unknown_cases = validation.get('unknown_cases', [])
    total = len(reports)
    
    status_str = "✅ PASSED" if is_accepted else "❌ FAILED"
    
    print(f"\n{'='*60}")
    print(f"  Sandbox Online Complete")
    print(f"{'='*60}")
    print(f"  Against Evolution: {os.path.relpath(args.file, root)}")
    print(f"  Status: {status_str}")
    print(f"  Selection Rule: Net Improvement (Improved > Broken)")
    print(f"  Improved: {len(accepted_cases)}/{total} ({len(accepted_cases)/total*100:.1f}%)" if total > 0 else "  Improved:  0/0")
    print(f"  Stable/Worse: {len(rejected_cases)}/{total}")
    print(f"  Unknown: {len(unknown_cases)}/{total}")
    print(f"  Result: {sandbox_file}")
    print(f"{'='*60}\n")

    if is_accepted:
        logger.info(f"Sandbox: [PASS] Routing proposal to 'sandbox_accepted'")
        target_file = os.path.join(dirs['accepted'], os.path.basename(args.file))
        shutil.move(args.file, target_file)
        print(f"Proposal successfully moved to: {os.path.relpath(target_file, root)}")
    else:
        logger.warning(f"Sandbox: [FAIL] Routing proposal to 'sandbox_rejected'")
        target_file = os.path.join(dirs['rejected'], os.path.basename(args.file))
        shutil.move(args.file, target_file)
        print(f"Proposal successfully moved to: {os.path.relpath(target_file, root)}")

if __name__ == "__main__":
    main()
