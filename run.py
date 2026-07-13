#!/usr/bin/env python3
"""BinaryStar — unified CLI entry point.
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
logger = setup_logger("BinaryStar", console_color=True)


# ── Date parser (used by backtest-run subcommand) ──

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
    p = subparsers.add_parser("session", help="Run a live Binary Star analysis cycle")
    p.add_argument("--symbol", type=str, required=True,
                   help="Trading pair prefix (e.g. BTC)")
    p.add_argument("--write_status", action="store_true",
                   help="Write progress to .session_run_status.json for status polling")
    add_data_path_argument(p)
    p.set_defaults(func=_cmd_session)


def _cmd_session(args):
    from run_session import SessionEngine, SessionController, write_status_file_callback

    if not args.path:
        args.path = "data/prod"

    progress_cb = None
    if getattr(args, "write_status", False):
        progress_cb = write_status_file_callback(args.path)

    controller = SessionController(args, progress_callback=progress_cb)
    controller.run()


# ═══════════════════════════════════════════════════════════════════════════════
# Subcommand: sniper
# ═══════════════════════════════════════════════════════════════════════════════

def _add_sniper_parser(subparsers):
    p = subparsers.add_parser("sniper", help="Run the real-time Sniper monitoring daemon")
    p.add_argument("--symbol", type=str, required=True,
                   help="Trading pair prefix(es), CSV for multiple (e.g. BTC,XAUT)")
    p.add_argument("--llm", action="store_true", default=False,
                   help="Enable AI session dispatch on trigger. Without this, "
                        "signals are evaluated and logged but no LLM tokens are spent.")
    p.add_argument("--trade", nargs='?', const=True, default=False, type=float,
                   help="Enable automated margin trading (implies --llm). "
                        "Optionally specify manual balance (e.g. --trade 1000). "
                        "Without a value, uses real Binance cross-margin balance.")
    add_data_path_argument(p)
    p.set_defaults(func=_cmd_sniper)


def _cmd_sniper(args):
    from run_sniper import SniperDaemon

    # --trade implies --llm
    if args.trade and not args.llm:
        args.llm = True

    if not args.path:
        args.path = "data/prod"

    daemon = SniperDaemon(args)
    daemon.run_forever()


# ═══════════════════════════════════════════════════════════════════════════════
# Subcommand: backtest-run
# ═══════════════════════════════════════════════════════════════════════════════

def _add_backtest_runner_parser(subparsers):
    p = subparsers.add_parser(
        "backtest-run",
        help="Run session cycles against historical timestamps",
        description="Dashboard mode (--write-status) reads timestamps from status file. "
                    "CLI modes (--timestamp or --start/--end/--samples) sample independently.",
    )
    p.add_argument("--symbol", type=str, required=True,
                   help="Trading pair (e.g. BTCUSDT)")

    # CLI: single-point
    p.add_argument("--timestamp", "-ts", type=str, default=None,
                   help="Run against a single historical timestamp (ISO-8601)")

    # CLI: batch range
    p.add_argument("--start", type=_parse_date, default=None,
                   help="Start date for batch sampling (YYYY-MM-DD or T-30d)")
    p.add_argument("--end", type=_parse_date, default="now",
                   help="End date for batch sampling (default: now)")
    p.add_argument("--samples", type=int, default=None,
                   help="Number of historical samples (requires --start)")

    p.add_argument("--write-status", action="store_true",
                   help="Write progress to .backtest_status.json for status polling")
    add_data_path_argument(p)
    p.set_defaults(func=_cmd_backtest_runner)


def _cmd_backtest_runner(args):
    from run_backtest import BacktestRunner

    if not args.path:
        args.path = "data/prod"

    # Validate mode exclusivity
    modes = sum([
        args.write_status,
        args.timestamp is not None,
        args.start is not None,
    ])
    if modes == 0:
        raise SystemExit(
            "Error: one of --write-status, --timestamp, or --start is required."
        )
    if modes > 1:
        raise SystemExit(
            "Error: --write-status, --timestamp, and --start are mutually exclusive."
        )
    if args.start and not args.samples:
        raise SystemExit("Error: --samples is required with --start for batch mode.")

    runner = BacktestRunner(args)
    runner.run()


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
    setup_logger("", log_file=log_path,
                 max_bytes=10 * 1024 * 1024, backup_count=5)
    logger_audit = logging.getLogger("Audit")

    controller = AuditController(config_dict=config, data_root=data_root,
                                 logger=logger_audit)

    # Collect files
    files_to_audit: list[str] = []
    if args.file:
        if not os.path.exists(args.file):
            logger_audit.error("target file not found | file=%s", args.file)
            sys.exit(1)
        files_to_audit.append(args.file)
    else:
        sessions_dir = os.path.join(root, data_root, "sessions")
        if not os.path.exists(sessions_dir):
            logger_audit.error("sessions directory not found | path=%s", sessions_dir)
            sys.exit(1)
        logger_audit.info("batch scanning | path=%s", sessions_dir)
        files_to_audit = [os.path.join(sessions_dir, f)
                          for f in os.listdir(sessions_dir)
                          if f.endswith(".json")]
        symbol = None
        if args.symbol:
            from src.utils.symbol_utils import resolve_symbol
            symbol = resolve_symbol(args.symbol)
        if symbol:
            logger_audit.info("filtering batch | symbol=%s", symbol)
            files_to_audit = [f for f in files_to_audit
                              if os.path.basename(f).startswith(f"{symbol}_")]
        files_to_audit.sort()

    if not files_to_audit:
        logger_audit.warning("no sessions found | path=%s", data_root)
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
        logger.error(f"evolution cycle failed | error={e}")
        sys.exit(1)


# ═══════════════════════════════════════════════════════════════════════════════
# Subcommand: patch
# ═══════════════════════════════════════════════════════════════════════════════

def _add_patch_parser(subparsers):
    p = subparsers.add_parser("patch", help="Apply an evolution proposal to config/prompts")
    p.add_argument("--file", "-f", required=True,
                   help="Path to the validated evolution proposal JSON")
    p.add_argument("--symbol", type=str,
                   help="Trading symbol (e.g., XAUT, BTC). If provided, patches "
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
        logger_patch.error("proposal JSON not found | file=%s", args.file)
        sys.exit(1)

    proposal = load_json(args.file)
    logger_patch.info("patching | file=%s", os.path.basename(args.file))

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
                logger_patch.info("patch applied | key=%s | symbol=%s", key, symbol)
            else:
                logger_patch.warning("patch FAILED | key=%s | symbol=%s", key, symbol)
        else:
            updates = ConfigPatcher.apply_patch(config_abs, key, val, t_path)
            if updates > 0:
                logger_patch.info("patch applied | key=%s | config=%s", key, target_config)
            else:
                logger_patch.warning("patch FAILED | key=%s | config=%s", key, target_config)

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
            logger_patch.error("patch FAILED | module=%s | reason=unknown", module)
            continue
        abs_path = os.path.join(root, rel_path)
        replacements = PromptDistiller.apply_distillation(abs_path, anchor, logic)
        if replacements > 0:
            logger_patch.info("prompt patched | replacements=%d | path=%s", replacements, rel_path)
        else:
            logger_patch.warning("prompt patch FAILED | reason=no_match | path=%s", rel_path)

    logger_patch.info(f"sync complete | file={os.path.basename(args.file)}")


# ═══════════════════════════════════════════════════════════════════════════════
# Main entry point
# ═══════════════════════════════════════════════════════════════════════════════

def _build_version_string() -> str:
    """Build the --version output string including git commit."""
    from src.utils.pipeline_utils import get_project_version, get_git_commit
    ver = get_project_version()
    commit = get_git_commit()
    return f"binary-star {ver} (commit {commit})"


def main():
    parser = argparse.ArgumentParser(
        description="BinaryStar — AI-driven crypto quantitative trading engine",
    )
    parser.add_argument(
        "--version", action="version",
        version=_build_version_string(),
    )
    subparsers = parser.add_subparsers(dest="command", title="commands")
    _add_session_parser(subparsers)
    _add_sniper_parser(subparsers)
    _add_backtest_runner_parser(subparsers)
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
