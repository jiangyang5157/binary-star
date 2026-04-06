#!/usr/bin/env python3
"""
Singularity Offline Sandbox Review (v1.0)

Re-evaluates a sandbox report against the original audit reports using
the Darwinian Fitness Evaluator. This allows offline quality assessment
without re-running the full sandbox replay.

Usage:
  python tools/sandbox_review.py -f <sandbox_report.json> -p <data_root>
"""
import os
import sys
import logging
import argparse
from datetime import datetime, timezone

# Setup absolute project paths - Move up one level since we are in tools/
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.utils.fitness_evaluator import FitnessEvaluator
from src.utils.pipeline_utils import add_data_path_argument, load_combined_config
from src.utils.json_utils import load_json, save_json
from src.utils.path_utils import resolve_project_root
from src.utils.datetime_utils import format_timestamp_for_filename
from src.utils.logger_utils import setup_logger


def _observed_at_to_audit_filename(symbol: str, observed_at: str) -> str:
    """
    Converts an observed_at ISO timestamp to the standard audit filename.
    Audit files are named by session start time (observed_at), NOT audit completion time.
    Example: '2026-03-10T01:00:00Z' -> 'BTCUSDT_audit_20260310_010000.json'
    """
    ts_compact = format_timestamp_for_filename(observed_at)
    return f"{symbol}_audit_{ts_compact}.json"


def main():
    parser = argparse.ArgumentParser(description="Singularity Offline Sandbox Review (v1.0)")
    parser.add_argument("--file", "-f", required=True, help="Path to the sandbox result JSON file")
    add_data_path_argument(parser, required=True)

    args = parser.parse_args()

    # 1. Resolve paths
    root = resolve_project_root()
    data_root = os.path.join(root, args.path)

    log_path = os.path.join(data_root, "sandbox_offline.log")
    setup_logger("", log_file=log_path)
    logger = logging.getLogger("SandboxOffline")

    # 2. Load sandbox report
    if not os.path.exists(args.file):
        logger.error(f"Sandbox report not found: {args.file}")
        sys.exit(1)

    sandbox_report = load_json(args.file)
    if not sandbox_report:
        logger.error(f"Failed to parse sandbox report: {args.file}")
        sys.exit(1)

    # 3. Collect ALL cases from sandbox (both accepted and rejected are new audit results)
    all_new_cases = []
    for case in sandbox_report.get('accepted_cases', []):
        all_new_cases.append(case)
    for case in sandbox_report.get('rejected_cases', []):
        all_new_cases.append(case)

    if not all_new_cases:
        logger.error("Sandbox report contains no cases to review.")
        sys.exit(1)

    logger.info(f"Loaded {len(all_new_cases)} cases from sandbox report.")

    # 4. Initialize Fitness Evaluator
    full_config = load_combined_config()
    evaluator = FitnessEvaluator(config_dict=full_config)

    audits_dir = os.path.join(data_root, "audits")

    # 5. Evaluate each case
    accepted_cases = []
    rejected_cases = []
    # Initialize with existing unknown cases from the source report to preserve data
    unknown_cases = list(sandbox_report.get('unknown_cases', []))

    for idx, new_case in enumerate(all_new_cases):
        # Extract identifiers from the new case
        observation = new_case.get('session', {}).get('observation', {})
        symbol = observation.get('symbol', 'UNKNOWN')
        observed_at = observation.get('observed_at', '')
        session_id = f"{symbol}_{observed_at}"

        logger.info(f"[Case {idx+1}/{len(all_new_cases)}] Reviewing {session_id}...")

        # 6. Find matching old audit report by observed_at (session start time = filename key)
        if not observed_at:
            logger.warning(f"  Case missing 'observed_at' in observation. -> UNKNOWN")
            unknown_cases.append(new_case)
            continue

        old_audit_filename = _observed_at_to_audit_filename(symbol, observed_at)
        old_audit_path = os.path.join(audits_dir, old_audit_filename)

        if not os.path.exists(old_audit_path):
            logger.warning(f"  Old audit not found: {old_audit_filename} -> UNKNOWN")
            unknown_cases.append(new_case)
            continue

        old_report = load_json(old_audit_path)
        if not old_report:
            logger.warning(f"  Failed to parse old audit: {old_audit_filename} -> UNKNOWN")
            unknown_cases.append(new_case)
            continue

        # 7. Forensic comparison
        old_outcome = old_report.get('market_outcome', {})
        new_outcome = new_case.get('market_outcome', {})

        old_score = evaluator.get_fitness_score(old_outcome)
        new_score = evaluator.get_fitness_score(new_outcome)

        if evaluator.is_superior(old_outcome, new_outcome):
            accepted_cases.append(new_case)
            logger.info(f"  -> ACCEPTED (old={old_score}, new={new_score})")
        else:
            rejected_cases.append(new_case)
            logger.info(f"  -> REJECTED (old={old_score}, new={new_score})")

    # 8. Calculate acceptance
    total = len(all_new_cases)
    sandbox_cfg = full_config.get('sandbox', {})
    threshold = float(sandbox_cfg['acceptance_rate_threshold'])

    success_rate = len(accepted_cases) / total if total > 0 else 0
    is_accepted = success_rate >= threshold

    # 9. Build result
    result = {
        "is_accepted": is_accepted,
        "accepted_cases": accepted_cases,
        "rejected_cases": rejected_cases,
        "unknown_cases": unknown_cases
    }

    # 10. Save result
    now_ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    # Infer symbol from first case
    first_symbol = "UNKNOWN"
    if all_new_cases:
        first_symbol = all_new_cases[0].get('session', {}).get('observation', {}).get('symbol', 'UNKNOWN')

    output_dir = os.path.join(data_root, "evolution", "sandbox_results")
    os.makedirs(output_dir, exist_ok=True)
    output_file = os.path.join(output_dir, f"{first_symbol}_evolution_sandbox_{now_ts}.json")
    save_json(result, output_file)

    # 11. Summary
    status = "✅ ACCEPTED" if is_accepted else "❌ REJECTED"
    print(f"\n{'='*60}")
    print(f"  Sandbox Offline Complete")
    print(f"{'='*60}")
    print(f"  Against Sandbox: {os.path.relpath(args.file, root)}")
    print(f"  Status: {status}")
    print(f"  Threshold: {threshold*100:.0f}%")
    print(f"  Improved: {len(accepted_cases)}/{total} ({len(accepted_cases)/total*100:.1f}%)" if total > 0 else "  Improved:  0/0")
    print(f"  Stable/Worse: {len(rejected_cases)}/{total}")
    print(f"  Unknown: {len(unknown_cases)}/{total}")
    print(f"  Output: {output_file}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
