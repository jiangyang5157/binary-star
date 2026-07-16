#!/usr/bin/env python3
"""Delete all artifacts (sessions, audits, klines, htmls) for a given project version.

Handles two layouts:
  1. Active:  {data_root}/sessions/  — reads project_version from JSON to filter
  2. Archived: {data_root}/{version}/sessions/  — all sessions in this dir match

Derived artifacts (audits, klines, htmls) are matched by {symbol}_{type}_{timestamp}
pattern in both the top-level and versioned subdirectories.

Usage:
    python scripts/clean_version_artifacts.py -p data/prod -v 26.7.13
    python scripts/clean_version_artifacts.py -p data/prod -v 26.7.13 --dry-run
"""

import argparse, json, os, re, sys, glob as globmod


# ── Filename parsing ──────────────────────────────────────────

SESSION_RE = re.compile(r"(.+)_session_(\d{8}_\d{6})\.json$")


def parse_session_name(fname: str) -> tuple[str, str] | None:
    """Return (symbol, timestamp) or None."""
    m = SESSION_RE.match(fname)
    if not m:
        return None
    return m.group(1), m.group(2)


# ── Session discovery ─────────────────────────────────────────

def find_active_sessions(data_root: str, version: str) -> list[tuple[str, str]]:
    """Scan {data_root}/sessions/ for JSONs whose project_version matches."""
    sessions_dir = os.path.join(data_root, "sessions")
    if not os.path.isdir(sessions_dir):
        return []
    matches = []
    for fname in os.listdir(sessions_dir):
        if not fname.endswith(".json"):
            continue
        fpath = os.path.join(sessions_dir, fname)
        try:
            with open(fpath) as fh:
                pv = json.load(fh).get("metadata", {}).get("version_control", {}).get("project_version")
        except (json.JSONDecodeError, OSError, KeyError):
            continue
        if pv == version:
            matches.append((fpath, fname))
    return matches


def find_archived_sessions(data_root: str, version: str) -> list[tuple[str, str]]:
    """Scan {data_root}/{version}/sessions/ — all JSONs match by directory convention."""
    sessions_dir = os.path.join(data_root, version, "sessions")
    if not os.path.isdir(sessions_dir):
        return []
    matches = []
    for fname in os.listdir(sessions_dir):
        if fname.endswith(".json"):
            matches.append((os.path.join(sessions_dir, fname), fname))
    return matches


# ── Artifact derivation ───────────────────────────────────────

def find_derived_artifacts(data_root: str, version: str, symbol: str, ts: str) -> list[str]:
    """Find audit/klines/html files matching (symbol, timestamp) anywhere under data_root."""
    found = []

    # Directories to search
    search_dirs = [
        data_root,                          # top-level audits/ klines/ html/
        os.path.join(data_root, version),   # versioned audits/ klines/ html/
    ]

    for base in search_dirs:
        # Audit
        ap = os.path.join(base, "audits", f"{symbol}_audit_{ts}.json")
        if os.path.isfile(ap):
            found.append(ap)

        # HTML
        hp = os.path.join(base, "html", f"{symbol}_session_{ts}.html")
        if os.path.isfile(hp):
            found.append(hp)

        # Klines (wildcard timeframe)
        kdir = os.path.join(base, "klines")
        if os.path.isdir(kdir):
            for ext in ("md", "png"):
                for kp in globmod.glob(os.path.join(kdir, f"{symbol}_klines_*_{ts}.{ext}")):
                    found.append(kp)

    return found


# ── Main ──────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Delete all artifacts for a given project version")
    parser.add_argument("-p", "--path", required=True, help="Data root directory (e.g. data/prod)")
    parser.add_argument("-v", "--version", required=True, help="Project version (e.g. 26.7.13)")
    parser.add_argument("--dry-run", action="store_true", help="Preview only, do not delete")
    parser.add_argument("--yes", "-y", action="store_true", help="Skip confirmation prompt")
    args = parser.parse_args()

    data_root = os.path.abspath(args.path)
    version = args.version

    if not os.path.isdir(data_root):
        print(f"ERROR: data root not found: {data_root}")
        sys.exit(1)

    # 1. Find sessions
    active = find_active_sessions(data_root, version)
    archived = find_archived_sessions(data_root, version)
    all_sessions = active + archived

    print(f"Active sessions (in {data_root}/sessions/):   {len(active)}")
    print(f"Archived sessions (in {data_root}/{version}/): {len(archived)}")
    print(f"Total matching sessions:                       {len(all_sessions)}")

    if not all_sessions:
        print("Nothing to clean.")
        return

    # 2. Collect all files to delete
    to_delete: list[str] = []
    for fpath, fname in all_sessions:
        to_delete.append(fpath)
        parsed = parse_session_name(fname)
        if parsed:
            symbol, ts = parsed
            to_delete.extend(find_derived_artifacts(data_root, version, symbol, ts))

    # Dedup
    to_delete = list(dict.fromkeys(to_delete))

    # 3. Categorize
    def count_in(dirname: str) -> int:
        return sum(1 for f in to_delete if f"/{dirname}/" in f)

    n_sessions = count_in("sessions")
    n_audits = count_in("audits")
    n_klines = count_in("klines")
    n_htmls = count_in("html")

    print(f"\n  Sessions: {n_sessions}")
    print(f"  Audits:   {n_audits}")
    print(f"  Klines:   {n_klines}")
    print(f"  HTMLs:    {n_htmls}")
    print(f"  ─────────────────")
    print(f"  Total:    {len(to_delete)}")

    # 4. Dry-run → show and exit
    if args.dry_run:
        print("\n[DRY RUN] — would delete:")
        for f in sorted(to_delete):
            print(f"  {f}")
        print(f"\n[DRY RUN] {len(to_delete)} file(s) would be deleted.")
        return

    # 5. Confirm
    if not args.yes:
        print(f"\n⚠  This will PERMANENTLY DELETE {len(to_delete)} file(s).")
        confirm = input("Type 'yes' to confirm: ")
        if confirm.strip() != "yes":
            print("Aborted.")
            return

    # 6. Delete
    deleted = 0
    errors = 0
    for f in to_delete:
        try:
            os.remove(f)
            deleted += 1
        except OSError as e:
            print(f"  ERROR: {f}: {e}")
            errors += 1

    print(f"\nDeleted {deleted}/{len(to_delete)} file(s)" + (f" ({errors} errors)" if errors else "") + ".")

    # 7. Clean empty version directory
    version_dir = os.path.join(data_root, version)
    if os.path.isdir(version_dir):
        for sub in ("sessions", "audits", "klines"):
            sub_path = os.path.join(version_dir, sub)
            if os.path.isdir(sub_path):
                try:
                    os.rmdir(sub_path)
                except OSError:
                    pass  # not empty, leave it


if __name__ == "__main__":
    main()
