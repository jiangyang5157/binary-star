#!/usr/bin/env python3
"""
Clean Session Reports by Version
--------------------------------
Delete all session reports under <data_root>/sessions/ whose
metadata.version_control.project_version matches the given version.

Usage:
    python scripts/clean_version_sessions.py -p data/prod -v 26.7.04
    python scripts/clean_version_sessions.py -p data/backtest -v 26.6.29 --symbol BTC
    python scripts/clean_version_sessions.py -p data/backtest -v 26.6.29 --symbol BTC,XAUT
    python scripts/clean_version_sessions.py -p data/prod -v 26.7.04 --dry-run
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


def extract_version(session_path: str) -> str | None:
    """Return the project_version from session metadata, or None if unreadable."""
    try:
        with open(session_path, "r") as fh:
            data = json.load(fh)
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("skipping unreadable file | file=%s | error=%s", session_path, exc)
        return None

    if not isinstance(data, dict):
        return None

    metadata = data.get("metadata")
    if not isinstance(metadata, dict):
        return None

    version_control = metadata.get("version_control")
    if not isinstance(version_control, dict):
        return None

    return version_control.get("project_version") or None


def collect_session_files(data_root: str, symbol: str | None = None) -> list[str]:
    """Collect session JSON paths under <data_root>/sessions/, optionally filtered by symbol.

    Mimics the audit command's batch-scan logic in run.py:_cmd_audit.
    """
    sessions_dir = os.path.join(PROJECT_ROOT, data_root, "sessions")
    if not os.path.isdir(sessions_dir):
        logger.error("sessions directory not found | dir=%s", sessions_dir)
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
        logger.info("filtering by symbol(s): %s", ", ".join(resolved))
        files = [f for f in files
                 if any(os.path.basename(f).startswith(f"{sym}_") for sym in resolved_set)]

    files.sort()
    if not files:
        logger.warning("no session files found | dir=%s", sessions_dir)

    return files


def main():
    parser = argparse.ArgumentParser(
        description="Delete session reports matching a specific version under <data_root>/sessions/"
    )
    add_data_path_argument(parser, required=True)
    parser.add_argument(
        "-v", "--version",
        type=str, required=True,
        help="Project version to match, e.g. 26.7.04.  Sessions with this "
             "metadata.version_control.project_version will be deleted."
    )
    parser.add_argument(
        "--symbol", type=str,
        help="Optional: filter by symbol prefix (e.g. BTC, BTC,XAUT). "
             "Accepts comma-separated list. Without --symbol, ALL symbols are processed."
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Scan and report matching files without deleting them."
    )
    parser.add_argument(
        "--verbose", action="store_true",
        help="Enable debug-level logging."
    )

    args = parser.parse_args()
    setup_logger(verbose=args.verbose)

    data_root = args.path
    version = args.version
    symbol = args.symbol or None
    dry_run = args.dry_run

    # ── Collect ───────────────────────────────────────────────────────────────
    files = collect_session_files(data_root, symbol)
    logger.info("scanning %d session files | dir=%s/sessions/", len(files), data_root)

    # ── Identify version matches ─────────────────────────────────────────────
    matched_files: list[str] = []
    version_dist: dict[str, int] = {}
    skipped_count = 0

    for filepath in files:
        fname = os.path.basename(filepath)
        try:
            file_version = extract_version(filepath)
        except Exception:
            skipped_count += 1
            continue

        # Track version distribution for reporting
        label = file_version or "(none)"
        version_dist[label] = version_dist.get(label, 0) + 1

        if file_version == version:
            matched_files.append(filepath)
            logger.debug("MATCH v%s → %s", version, fname)

    # ── Report ────────────────────────────────────────────────────────────────
    logger.info("")
    logger.info("scan complete | total=%d | matched=v%s=%d",
                len(files), version, len(matched_files))
    logger.info("version distribution: %s",
                ", ".join(f"v{k}={c}" for k, c in sorted(version_dist.items())))

    if not matched_files:
        logger.info("no sessions matching version %s to delete", version)
        return

    if dry_run:
        logger.info("[DRY RUN] would delete %d file(s)", len(matched_files))
        for fp in matched_files:
            logger.info("→ %s", os.path.basename(fp))
        logger.info("[DRY RUN] no files were actually deleted")
        return

    # ── Delete ────────────────────────────────────────────────────────────────
    deleted = 0
    for fp in matched_files:
        try:
            os.remove(fp)
            logger.info("deleted | file=%s", os.path.basename(fp))
            deleted += 1
        except OSError as exc:
            logger.error("delete failed | file=%s | error=%s", os.path.basename(fp), exc)

    logger.info("deleted %d session file(s) matching version %s", deleted, version)


if __name__ == "__main__":
    main()
