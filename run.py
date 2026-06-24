#!/usr/bin/env python3
"""Singularity — unified CLI entry point.
Each run_*.py also has a standalone main() for direct invocation
(e.g. ``python run_session.py --symbol BTC``).  The argparse definitions
are intentionally duplicated — the run_*.py scripts are independent
entry points that must work without importing run.py.
"""

import os
import sys
import argparse
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

# Ensure project root is on sys.path
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from dotenv import load_dotenv
from src.utils.pipeline_utils import load_global_config, add_data_path_argument
from src.utils.logger_utils import setup_logger
from src.utils.datetime_utils import parse_iso_to_utc

load_dotenv()
logger = setup_logger("Singularity")


# ── Date parser (shared between session subcommand and the old run_session) ──

def _parse_date(date_str: str) -> datetime:
    """Parse flexible dates: T-30d, ISO-8601, YYYY-MM-DD, or 'now'."""
    from src.utils.datetime_utils import parse_flexible_date
    try:
        return parse_flexible_date(date_str)
    except ValueError as e:
        raise argparse.ArgumentTypeError(str(e))


# ── Shared helpers ────────────────────────────────────────────────────────────

def _resolve_data_path(args: argparse.Namespace, default: str) -> str:
    if hasattr(args, "path") and args.path:
        return args.path
    return default


# ═══════════════════════════════════════════════════════════════════════════════
# Subcommand: session
# ═══════════════════════════════════════════════════════════════════════════════

def _add_session_parser(subparsers):
    p = subparsers.add_parser("session", help="Run a Binary Star analysis cycle")
    p.add_argument("--symbol", type=str, required=True,
                   help="Trading pair prefix (e.g. BTC)")
    p.add_argument("--timestamp", "-ts", type=str,
                   help="Precise historical timestamp (ISO-8601)")
    p.add_argument("--start", type=_parse_date,
                   help="Start date for backtest (YYYY-MM-DD or T-30d)")
    p.add_argument("--end", type=_parse_date, default="now",
                   help="End date for backtest (default: now)")
    p.add_argument("--samples", type=int, default=None,
                   help="Number of historical samples (backtest mode)")
    add_data_path_argument(p)
    p.set_defaults(func=_cmd_session)


def _cmd_session(args):
    from run_session import SessionEngine, SessionController

    # Resolve mode
    if not args.path:
        args.path = "data/prod"

    if getattr(args, "timestamp", None):
        logger.info("Mode: SIMULATION (single historical point)")
        logger.info("  --timestamp '%s'", args.timestamp)
    elif getattr(args, "start", None):
        if args.samples is None:
            raise SystemExit("Error: --samples is required for backtest mode.")
        logger.info("Mode: BACKTEST (batch historical)")
        logger.info("  --start '%s', --end '%s', --samples %s",
                    args.start, args.end, args.samples)
    else:
        logger.info("Mode: PROD (live execution)")

    print()
    controller = SessionController(args)
    controller.run()


# ═══════════════════════════════════════════════════════════════════════════════
# Subcommand: sniper
# ═══════════════════════════════════════════════════════════════════════════════

def _add_sniper_parser(subparsers):
    p = subparsers.add_parser("sniper", help="Run the real-time Sniper monitoring daemon")
    p.add_argument("--symbol", type=str, required=True,
                   help="Trading pair prefix(es), CSV for multiple (e.g. BTC,ETH,XAUT)")
    p.add_argument("--trade", nargs='?', const=True, default=False, type=float,
                   help="Enable automated margin trading. Optionally specify manual balance (e.g. --trade 1000). "
                        "Without a value, uses real Binance cross-margin balance.")
    add_data_path_argument(p)
    p.set_defaults(func=_cmd_sniper)


def _cmd_sniper(args):
    from run_sniper import SniperDaemon

    if not args.path:
        args.path = "data/prod"

    daemon = SniperDaemon(args)
    daemon.run_forever()


# ═══════════════════════════════════════════════════════════════════════════════
# Subcommand: audit
# ═══════════════════════════════════════════════════════════════════════════════

def _add_audit_parser(subparsers):
    p = subparsers.add_parser("audit", help="Run forensic audit on sessions")
    p.add_argument("--file", "-f", help="Path to a specific session JSON file")
    p.add_argument("--symbol", type=str,
                   help="Filter batch audit by symbol prefix (e.g. BTC)")
    p.add_argument("--force", action="store_true",
                   help="Bypass deduplication and maturity checks")
    add_data_path_argument(p, required=True)
    p.set_defaults(func=_cmd_audit)


def _cmd_audit(args):
    import concurrent.futures
    import multiprocessing
    from src.analyzer.audit_controller import AuditController
    from src.utils.pipeline_utils import load_combined_config
    from src.utils.path_utils import resolve_project_root

    root = resolve_project_root()
    data_root = args.path
    config = load_combined_config()

    log_path = os.path.join(data_root, "audit.log")
    setup_logger("", log_file=log_path)
    logger_audit = logging.getLogger("Audit")

    controller = AuditController(config_dict=config, data_root=data_root,
                                 logger=logger_audit)

    # Collect files
    files_to_audit: list[str] = []
    if args.file:
        if not os.path.exists(args.file):
            logger_audit.error("Target file not found: %s", args.file)
            sys.exit(1)
        files_to_audit.append(args.file)
    else:
        sessions_dir = os.path.join(root, data_root, "sessions")
        if not os.path.exists(sessions_dir):
            logger_audit.error("Sessions directory not found: %s", sessions_dir)
            sys.exit(1)
        logger_audit.info("Batch Mode: Scanning %s ...", sessions_dir)
        files_to_audit = [os.path.join(sessions_dir, f)
                          for f in os.listdir(sessions_dir)
                          if f.endswith(".json")]
        symbol = None
        if args.symbol:
            from src.utils.symbol_utils import resolve_symbol
            symbol = resolve_symbol(args.symbol)
        if symbol:
            logger_audit.info("Filtering by symbol: %s", symbol)
            files_to_audit = [f for f in files_to_audit
                              if os.path.basename(f).startswith(f"{symbol}_")]
        files_to_audit.sort()

    if not files_to_audit:
        logger_audit.warning("No sessions found to audit in %s.", data_root)
        return

    # Delegate to the audit runner logic from run_audit.py
    from run_audit import process_audit_file, worker_init, run_task

    print(f"Launching Parallel Audit Pool (Workers: {multiprocessing.cpu_count() or 1})...")

    task_args = [(f, data_root, args.force) for f in files_to_audit]

    with concurrent.futures.ProcessPoolExecutor(
        max_workers=min(multiprocessing.cpu_count(), 8),
        initializer=worker_init,
        initargs=(log_path, config, data_root),
    ) as executor:
        results = list(executor.map(run_task, task_args))

    success = results.count("SUCCESS")
    skip = results.count("EXISTS")
    mature = results.count("MATURING")
    empty = results.count("EMPTY")
    fail = results.count("FAILED")

    print("\n" + "=" * 60)
    print(" BATCH AUDIT SUMMARY")
    print("=" * 60)
    print(f" TOTAL SESSIONS : {len(files_to_audit)}")
    print(f" COMPLETED      : {success}")
    print(f" ALREADY EXISTS : {skip}")
    print(f" EMPTY (NO DATA): {empty}")
    print(f" MATURING (WAIT): {mature}")
    print(f" FAILED         : {fail}")
    print("=" * 60 + "\n")


# ═══════════════════════════════════════════════════════════════════════════════
# Subcommand: evolution
# ═══════════════════════════════════════════════════════════════════════════════

def _add_evolution_parser(subparsers):
    p = subparsers.add_parser("evolution", help="Run meta-evolution on audit results")
    p.add_argument("--symbol", type=str, required=True,
                   help="Trading pair prefix (e.g. BTC)")
    p.add_argument("--samples", type=int, required=True,
                   help="Number of audit reports to ingest")
    add_data_path_argument(p, required=True)
    p.set_defaults(func=_cmd_evolution)


def _cmd_evolution(args):
    from run_evolution import EvolutionEngine
    from src.utils.symbol_utils import resolve_symbol

    data_root = args.path
    symbol = resolve_symbol(args.symbol)

    engine = EvolutionEngine(data_root, symbol=symbol)
    try:
        engine.run_cycle(sample_size=args.samples)
    except Exception as e:
        print(f"Evolution Cycle Failed: {e}")
        sys.exit(1)


# ═══════════════════════════════════════════════════════════════════════════════
# Subcommand: patch
# ═══════════════════════════════════════════════════════════════════════════════

def _add_patch_parser(subparsers):
    p = subparsers.add_parser("patch", help="Apply an evolution proposal to config/prompts")
    p.add_argument("--file", "-f", required=True,
                   help="Path to the validated evolution proposal JSON")
    p.add_argument("--symbol", type=str,
                   help="Trading symbol (e.g., BTC, XAUT). If provided, patches "
                        "symbol_config.yaml overrides first, then falls back to "
                        "strategy_config.yaml.")
    p.set_defaults(func=_cmd_patch)


def _cmd_patch(args):
    import logging as _logging
    from src.utils.json_utils import load_json
    from src.utils.evolution_utils import ConfigPatcher, PromptDistiller
    from src.utils.path_utils import resolve_project_root

    root = resolve_project_root()
    setup_logger("PatchRunner")
    logger_patch = _logging.getLogger("PatchRunner")

    if not os.path.exists(args.file):
        logger_patch.error("Proposal JSON NOT found: %s", args.file)
        sys.exit(1)

    proposal = load_json(args.file)
    logger_patch.info("Patching from: %s ...", os.path.basename(args.file))

    # Resolve symbol if provided (symbol-aware patching)
    symbol = None
    if args.symbol:
        from src.utils.symbol_utils import resolve_symbol
        symbol = resolve_symbol(args.symbol)

    target_config = "config/strategy_config.yaml"
    config_abs = os.path.join(root, target_config)

    for p in proposal.get("config_patch", []):
        key = p.get("target_key")
        val = p.get("replaced_with")
        t_path = p.get("target_path", "")

        if symbol:
            from src.config.symbol_resolver import patch_config
            updates = patch_config(symbol, t_path, key, val)
            if updates > 0:
                logger_patch.info("  (+) Updated '%s' for %s (overrides)", key, symbol)
            else:
                logger_patch.warning("  (!) FAILED to update '%s' for %s", key, symbol)
        else:
            updates = ConfigPatcher.apply_patch(config_abs, key, val, t_path)
            if updates > 0:
                logger_patch.info("  (+) Updated '%s' in %s", key, target_config)
            else:
                logger_patch.warning("  (!) FAILED to update '%s' in %s", key, target_config)

    PROMPT_MAP = {
        "session": "config/prompts/session.md",
        "critic": "config/prompts/critic.md",
        "binary_star": "config/prompts/binary_star.md",
    }
    for p in proposal.get("semantic_refinement", []):
        module = p.get("target_module", "").lower()
        anchor = p.get("anchor_text")
        logic = p.get("replaced_with")
        rel_path = PROMPT_MAP.get(module)
        if not rel_path:
            logger_patch.error("  (!) Unknown module: %s. Skipping.", module)
            continue
        abs_path = os.path.join(root, rel_path)
        replacements = PromptDistiller.apply_distillation(abs_path, anchor, logic)
        if replacements > 0:
            logger_patch.info("  (+) Replaced %d instances in %s", replacements, rel_path)
        else:
            logger_patch.warning("  (!) NO MATCH for anchor in %s", rel_path)

    logger_patch.info("Physical synchronization COMPLETE.")
    print(f"Physical Sync Successful: {os.path.basename(args.file)} moved to production.")


# ═══════════════════════════════════════════════════════════════════════════════
# Main entry point
# ═══════════════════════════════════════════════════════════════════════════════

def _build_version_string() -> str:
    """Build the --version output string including git commit."""
    from src.utils.pipeline_utils import get_project_version, get_git_commit
    ver = get_project_version()
    commit = get_git_commit()
    return f"singularity {ver} (commit {commit})"


def main():
    parser = argparse.ArgumentParser(
        description="Singularity — AI-driven crypto quantitative trading engine",
    )
    parser.add_argument(
        "--version", action="version",
        version=_build_version_string(),
    )
    subparsers = parser.add_subparsers(dest="command", title="commands")
    _add_session_parser(subparsers)
    _add_sniper_parser(subparsers)
    _add_audit_parser(subparsers)
    _add_evolution_parser(subparsers)
    _add_patch_parser(subparsers)

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)

    args.func(args)


if __name__ == "__main__":
    main()
