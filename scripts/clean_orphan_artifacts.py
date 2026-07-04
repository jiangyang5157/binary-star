#!/usr/bin/env python3
"""
Clean Orphan Artifacts
----------------------
Delete klines images, audit files, and session HTML files that have no
corresponding session report under <data_root>/sessions/.

Session reports are the source of truth. After deleting sessions (e.g. via
clean-neutral-sessions), run this to purge their orphaned artifacts.

Usage:
    python scripts/clean_orphan_artifacts.py -p data/prod
    python scripts/clean_orphan_artifacts.py -p data/prod --symbol BTC
    python scripts/clean_orphan_artifacts.py -p data/prod --dry-run
"""

import os
import sys
import re

# ── Path Setup ────────────────────────────────────────────────────────────────
TOOLS_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(TOOLS_DIR, ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import argparse
import logging

from src.utils.pipeline_utils import add_data_path_argument

logger = logging.getLogger(__name__)


def setup_logger(verbose: bool = False):
    """Configure minimal console logging for the cleanup script."""
    level = logging.DEBUG if verbose else logging.INFO
    fmt = "%(asctime)s [%(levelname)s] %(message)s"
    logging.basicConfig(level=level, format=fmt)


# Regex to extract (symbol, date, time) from any artifact filename.
# All artifact types share a trailing  YYYYMMDD_HHMMSS  before the extension.
#     session:  BTCUSDT_session_20260703_084400.json
#     klines:   BTCUSDT_klines_15m_20260703_084400.png
#     audit:    BTCUSDT_audit_20260703_084400.json
#     html:     BTCUSDT_session_20260703_084400.html
ARTIFACT_RE = re.compile(r'^([A-Z0-9]+)_.*_(\d{8})_(\d{6})\.(json|png|html|md)$')


def extract_key(filename: str) -> str | None:
    """Extract session key ``SYMBOL_YYYYMMDD_HHMMSS`` from an artifact filename."""
    m = ARTIFACT_RE.match(filename)
    if m:
        return f"{m.group(1)}_{m.group(2)}_{m.group(3)}"
    return None


def resolve_symbols(symbol_arg: str) -> list[str]:
    """Resolve a comma-separated symbol string to a list of symbols.

    Tries src.utils.symbol_utils.resolve_symbols when available, otherwise
    returns the raw comma-split tokens.
    """
    try:
        from src.utils.symbol_utils import resolve_symbols as _resolve
        resolved = _resolve(symbol_arg)
        logger.debug("resolved symbols: %s", resolved)
        return resolved
    except ImportError:
        logger.debug("symbol_utils not available, using raw symbol tokens")
        return [s.strip() for s in symbol_arg.split(",") if s.strip()]


def collect_session_keys(
    data_root: str, symbols: list[str] | None = None
) -> set[str]:
    """Build a set of session keys from session report filenames.

    When *symbols* is provided, only sessions matching those symbols are included.
    """
    sessions_dir = os.path.join(PROJECT_ROOT, data_root, "sessions")
    if not os.path.isdir(sessions_dir):
        logger.error("sessions directory not found | dir=%s", sessions_dir)
        sys.exit(1)

    keys: set[str] = set()
    for f in os.listdir(sessions_dir):
        if not f.endswith(".json"):
            continue
        key = extract_key(f)
        if key is None:
            continue
        if symbols and not any(key.startswith(f"{sym}_") for sym in symbols):
            continue
        keys.add(key)

    if not keys:
        logger.warning("no session keys extracted | dir=%s", sessions_dir)

    return keys


def clean_directory(
    subdir_name: str,
    session_keys: set[str],
    symbols: list[str] | None,
    data_root: str,
    dry_run: bool,
) -> tuple[int, int]:
    """Delete orphaned files in ``<data_root>/<subdir_name>/``.

    A file is an orphan when its extracted key is not in *session_keys*.
    When *symbols* is set, files outside those symbols are skipped entirely.

    Returns ``(total_files_inspected, deleted_count)``.
    """
    directory = os.path.join(PROJECT_ROOT, data_root, subdir_name)
    if not os.path.isdir(directory):
        logger.info("directory not found, skipping | dir=%s", directory)
        return 0, 0

    files = sorted(os.listdir(directory))
    inspected = 0
    deleted = 0

    for fname in files:
        key = extract_key(fname)
        if key is None:
            # File doesn't match the expected pattern — skip it
            continue
        if symbols and not any(key.startswith(f"{sym}_") for sym in symbols):
            continue  # outside our symbol filter — leave untouched

        inspected += 1

        if key in session_keys:
            continue  # has a matching session — keep it

        # Orphan → delete (or report in dry-run mode)
        filepath = os.path.join(directory, fname)
        deleted += 1  # count even during dry-run for accurate reporting
        if dry_run:
            logger.info("[DRY RUN] would delete | file=%s/%s", subdir_name, fname)
        else:
            try:
                os.remove(filepath)
                logger.info("deleted | file=%s/%s", subdir_name, fname)
            except OSError as exc:
                logger.error("delete failed | file=%s/%s | error=%s",
                             subdir_name, fname, exc)
                deleted -= 1  # reverse count on failure

    return inspected, deleted


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Delete orphaned klines, audits, and HTMLs that have no "
            "matching session report in <data_root>/sessions/."
        )
    )
    parser.add_argument(
        "--symbol", type=str,
        help="Optional: filter by symbol (e.g. BTC, BTC,XAUT). "
             "Accepts comma-separated list. Without --symbol, ALL symbols are processed."
    )
    parser.add_argument(
        "--dry-run", "-n", action="store_true",
        help="Scan and report orphaned files without deleting them."
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true",
        help="Enable debug-level logging."
    )
    add_data_path_argument(parser, required=True)

    args = parser.parse_args()
    setup_logger(verbose=args.verbose)

    data_root = args.path
    symbols = resolve_symbols(args.symbol) if args.symbol else None
    dry_run = args.dry_run

    # ── Build session key set ────────────────────────────────────────────────
    session_keys = collect_session_keys(data_root, symbols)
    logger.info("found %d session(s) | dir=%s/sessions/", len(session_keys), data_root)

    if not session_keys:
        logger.warning("no sessions found — nothing to compare against")
        return

    # ── Clean artifact directories ──────────────────────────────────────────
    directories = [
        ("klines", "klines images"),
        ("audits", "audit files"),
        ("html", "session HTMLs"),
    ]

    total_inspected = 0
    total_orphans = 0

    for subdir, label in directories:
        inspected, deleted = clean_directory(
            subdir, session_keys, symbols, data_root, dry_run
        )
        tag = " [DRY RUN — would delete]" if dry_run else ""
        logger.info("  %s: %d inspected, %d orphan(s)%s",
                    label, inspected, deleted, tag)
        total_inspected += inspected
        total_orphans += deleted

    logger.info(
        "%s | %d orphan(s) found across %d inspected artifact(s) in %d directory(s)",
        "dry run — no files deleted" if dry_run else "clean complete",
        total_orphans,
        total_inspected,
        len(directories),
    )


if __name__ == "__main__":
    main()
