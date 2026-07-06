#!/usr/bin/env python3
"""
Archive Session Reports to Version Folder
------------------------------------------
Move session JSON files from <data_root>/sessions/ into <data_root>/<version>/,
filtered by metadata.version_control.project_version matching the version argument.
Creates the target folder if it doesn't exist; overwrites on name collision.

Usage:
    python scripts/archive_sessions.py -p data/prod -v v26.6.26
    python scripts/archive_sessions.py -p data/prod -v v26.6.26 --symbol BTC
    python scripts/archive_sessions.py -p data/prod -v v26.6.26 --symbol BTC,XAUT
    python scripts/archive_sessions.py -p data/prod -v v26.6.26 --dry-run
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
import shutil

from src.utils.pipeline_utils import add_data_path_argument

logger = logging.getLogger(__name__)


def setup_logger(verbose: bool = False):
    """Configure minimal console logging for the archive script."""
    level = logging.DEBUG if verbose else logging.INFO
    fmt = "%(asctime)s [%(levelname)s] %(message)s"
    logging.basicConfig(level=level, format=fmt)


def collect_session_files(data_root: str, version: str, symbol: str | None = None) -> list[str]:
    """Collect session JSON paths under <data_root>/sessions/ where metadata.version_control.project_version
    matches the given version string.  Optionally further filtered by symbol prefix."""
    sessions_dir = os.path.join(PROJECT_ROOT, data_root, "sessions")
    if not os.path.isdir(sessions_dir):
        logger.error("sessions directory not found | dir=%s", sessions_dir)
        sys.exit(1)

    candidates = [
        os.path.join(sessions_dir, f)
        for f in os.listdir(sessions_dir)
        if f.endswith(".json")
    ]

    # Filter by version_control.project_version inside the session JSON
    files: list[str] = []
    skipped_no_meta = 0
    skipped_version_mismatch = 0
    for fp in candidates:
        try:
            with open(fp, "r") as fh:
                data = json.load(fh)
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("skipping unreadable file | file=%s | error=%s", os.path.basename(fp), exc)
            continue

        pv = data.get("metadata", {}).get("version_control", {}).get("project_version")
        if pv is None:
            skipped_no_meta += 1
            continue
        if str(pv) != version:
            skipped_version_mismatch += 1
            continue
        files.append(fp)

    if skipped_no_meta or skipped_version_mismatch:
        logger.info(
            "version filter | matched=%d | skipped_no_project_version=%d | skipped_version_mismatch=%d",
            len(files), skipped_no_meta, skipped_version_mismatch,
        )

    if symbol:
        from src.utils.symbol_utils import resolve_symbols
        resolved = resolve_symbols(symbol)
        resolved_set = set(resolved)
        logger.info("filtering by symbol(s): %s", ", ".join(resolved))
        files = [f for f in files
                 if any(os.path.basename(f).startswith(f"{sym}_") for sym in resolved_set)]

    files.sort()
    if not files:
        logger.warning("no matching session files found | dir=%s | version=%s", sessions_dir, version)

    return files


def main():
    parser = argparse.ArgumentParser(
        description="Move session reports to a versioned archive folder"
    )
    add_data_path_argument(parser, required=True)
    parser.add_argument(
        "-v", "--version",
        type=str, required=True,
        help="Project version to match against metadata.version_control.project_version "
             "in each session JSON (e.g. v26.6.26).  Only sessions whose project_version "
             "matches will be moved.  Also used as the target folder name: <data_root>/<version>/."
    )
    parser.add_argument(
        "--symbol", type=str,
        help="Optional: filter by symbol prefix (e.g. BTC, BTC,XAUT). "
             "Accepts comma-separated list. Without --symbol, ALL symbols are processed."
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Scan and report files that would be moved without actually moving them."
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

    # ── Resolve paths ──────────────────────────────────────────────────────────
    sessions_dir = os.path.join(PROJECT_ROOT, data_root, "sessions")
    target_dir = os.path.join(PROJECT_ROOT, data_root, version)

    # ── Collect ────────────────────────────────────────────────────────────────
    files = collect_session_files(data_root, version, symbol)
    logger.info("scanning %d session files | source=%s", len(files), sessions_dir)

    if not files:
        logger.info("nothing to archive")
        return

    # ── Prepare target ─────────────────────────────────────────────────────────
    if not dry_run:
        os.makedirs(target_dir, exist_ok=True)
        logger.info("target directory | dir=%s", target_dir)

    # ── Move ───────────────────────────────────────────────────────────────────
    moved = 0
    overwritten = 0
    failed = 0

    for src in files:
        fname = os.path.basename(src)
        dst = os.path.join(target_dir, fname)

        exists = os.path.exists(dst)

        if dry_run:
            tag = "[OVERWRITE]" if exists else "[CREATE]"
            logger.info("%s → %s", tag, fname)
            if exists:
                overwritten += 1
            else:
                moved += 1
            continue

        try:
            shutil.move(src, dst)
            if exists:
                overwritten += 1
                logger.debug("overwritten | file=%s", fname)
            else:
                moved += 1
                logger.debug("moved | file=%s", fname)
        except OSError as exc:
            failed += 1
            logger.error("move failed | file=%s | error=%s", fname, exc)

    # ── Report ─────────────────────────────────────────────────────────────────
    total = len(files)
    action = "would move" if dry_run else "moved"

    logger.info("")
    logger.info("archive complete | total=%d | %s=%d | overwritten=%d%s",
                total, action, moved, overwritten,
                f" | failed={failed}" if failed else "")

    if dry_run:
        logger.info("[DRY RUN] no files were actually moved")


if __name__ == "__main__":
    main()
