#!/usr/bin/env python3
"""
Clean NEUTRAL Session Reports
-----------------------------
Delete all session reports under <data_root>/sessions/ whose final_decision.opinion
is "NEUTRAL" — i.e. sessions where the Binary Star debate converged on no trade.

Usage:
    python scripts/clean_neutral_sessions.py -p data/prod
    python scripts/clean_neutral_sessions.py -p data/backtest --symbol BTC,XAUT
    python scripts/clean_neutral_sessions.py -p data/prod --dry-run
"""

import os
import sys

# ── Path Setup ────────────────────────────────────────────────────────────────
TOOLS_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(TOOLS_DIR, ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import argparse
import json
import logging

from src.utils.pipeline_utils import add_data_path_argument

logger = logging.getLogger(__name__)


def setup_logger(verbose: bool = False):
    """Configure minimal console logging for the cleanup script."""
    level = logging.DEBUG if verbose else logging.INFO
    fmt = "%(asctime)s [%(levelname)s] %(message)s"
    logging.basicConfig(level=level, format=fmt)


def is_neutral(session_path: str) -> bool:
    """Return True if the session file's final_decision.opinion is NEUTRAL."""
    try:
        with open(session_path, "r") as fh:
            data = json.load(fh)
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Skipping unreadable file %s: %s", session_path, exc)
        return False

    final = data.get("final_decision") if isinstance(data, dict) else None
    if not isinstance(final, dict):
        # Legacy or malformed — no decision to inspect
        return False

    opinion = final.get("opinion")
    if isinstance(opinion, str) and opinion.upper() == "NEUTRAL":
        return True

    return False


def collect_session_files(data_root: str, symbol: str | None = None) -> list[str]:
    """Collect session JSON paths under <data_root>/sessions/, optionally filtered by symbol.

    Mimics the audit command's batch-scan logic in run.py:_cmd_audit.
    """
    sessions_dir = os.path.join(PROJECT_ROOT, data_root, "sessions")
    if not os.path.isdir(sessions_dir):
        logger.error("Sessions directory not found: %s", sessions_dir)
        sys.exit(1)

    files = [
        os.path.join(sessions_dir, f)
        for f in os.listdir(sessions_dir)
        if f.endswith(".json")
    ]

    if symbol:
        from src.utils.symbol_utils import resolve_symbols
        resolved = resolve_symbols(symbol)
        resolved_set = set(resolved)
        logger.info("Filtering by symbol(s): %s", ", ".join(resolved))
        files = [f for f in files
                 if any(os.path.basename(f).startswith(f"{sym}_") for sym in resolved_set)]

    files.sort()
    if not files:
        logger.warning("No session files found in %s.", sessions_dir)

    return files


def main():
    parser = argparse.ArgumentParser(
        description="Delete NEUTRAL session reports under <data_root>/sessions/"
    )
    parser.add_argument(
        "--symbol", type=str,
        help="Optional: filter by symbol prefix (e.g. BTC, BTC,XAUT). "
             "Accepts comma-separated list. Without --symbol, ALL symbols are processed."
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Scan and report NEUTRAL files without deleting them."
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true",
        help="Enable debug-level logging."
    )
    add_data_path_argument(parser, required=True)

    args = parser.parse_args()
    setup_logger(verbose=args.verbose)

    data_root = args.path
    symbol = args.symbol or None
    dry_run = args.dry_run

    # ── Collect ───────────────────────────────────────────────────────────────
    files = collect_session_files(data_root, symbol)
    logger.info("Scanning %d session file(s) under %s/sessions/ ...", len(files), data_root)

    # ── Identify NEUTRAL ──────────────────────────────────────────────────────
    neutral_files: list[str] = []
    non_neutral_count = 0
    skipped_count = 0

    for filepath in files:
        fname = os.path.basename(filepath)
        try:
            if is_neutral(filepath):
                neutral_files.append(filepath)
                logger.debug("  NEUTRAL  → %s", fname)
            else:
                non_neutral_count += 1
        except Exception:
            skipped_count += 1

    # ── Report ────────────────────────────────────────────────────────────────
    logger.info("")
    logger.info("Scan complete: %d total, %d NEUTRAL, %d non-NEUTRAL, %d skipped",
                len(files), len(neutral_files), non_neutral_count, skipped_count)

    if not neutral_files:
        logger.info("No NEUTRAL sessions to delete.")
        return

    if dry_run:
        logger.info("[DRY RUN] Would delete %d file(s):", len(neutral_files))
        for fp in neutral_files:
            logger.info("  → %s", os.path.basename(fp))
        logger.info("[DRY RUN] No files were actually deleted.")
        return

    # ── Delete ────────────────────────────────────────────────────────────────
    deleted = 0
    for fp in neutral_files:
        try:
            os.remove(fp)
            logger.info("Deleted: %s", os.path.basename(fp))
            deleted += 1
        except OSError as exc:
            logger.error("Failed to delete %s: %s", os.path.basename(fp), exc)

    logger.info("Done. Deleted %d NEUTRAL session file(s).", deleted)


if __name__ == "__main__":
    main()
