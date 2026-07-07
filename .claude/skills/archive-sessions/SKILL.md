---
name: archive-sessions
description: >
  Use when the user wants to archive, move, or organize session report files
  into a version folder (e.g., "archive all XAUT sessions to 26.7.8",
  "move my sessions to a new version folder", "organize sessions by version",
  "archive sessions by project version"). Also trigger when the user mentions
  moving session JSON files under data/prod/sessions/ into a subfolder.
  The -v argument matches against metadata.version_control.project_version
  inside each session JSON, so only sessions from that project version are
  moved. Supports --symbol filtering (XAUT, BTC, or comma-separated) and
  --dry-run preview.
---

# Archive Sessions

Move session JSON files from `<data_root>/sessions/` into `<data_root>/<version>/`,
**filtered by `metadata.version_control.project_version`** inside each session JSON.
Only sessions whose `project_version` matches the `-v` argument are moved.

The version string also serves as the target folder name. Creates the target folder
if it doesn't exist; overwrites on name collision.

## Usage

Run the script directly — no subagents needed:

```bash
python scripts/archive_sessions.py -p <data_root> -v <version> [--symbol SYM] [--dry-run] [--verbose]
```

**Arguments:**

| Arg | Required | Description |
|-----|----------|-------------|
| `-p`, `--path` | yes | Data root directory, e.g. `data/prod` |
| `-v`, `--version` | yes | Project version to match against `metadata.version_control.project_version` in session JSONs, e.g. `26.7.8`. Also used as target folder name. |
| `--symbol` | no | Comma-separated symbol filter, e.g. `XAUT` or `XAUT,BTC` |
| `--dry-run` | no | Preview without moving files |
| `--verbose` | no | Debug-level logging |

## How Version Matching Works

The script opens each session JSON file and reads:

```
metadata → version_control → project_version
```

Only sessions where `project_version` equals the `-v` argument **exactly** are moved.
Sessions with a missing or `null` `project_version` are skipped (logged as `skipped_no_project_version`).

## Examples

```bash
# Archive only sessions whose project_version is exactly match
python scripts/archive_sessions.py -p data/prod -v 26.7.8

# Same, but only XAUT sessions
python scripts/archive_sessions.py -p data/prod -v 26.7.8 --symbol XAUT

# Preview first
python scripts/archive_sessions.py -p data/prod -v 26.7.8 --dry-run
```

## Important Rules

1. **Always use `--dry-run` first** — show the user what will be moved before executing the real move
2. **Ask for version if not provided** — the `-v` argument is required; if the user doesn't specify a version, ask
3. **Ask for path if ambiguous** — defaults to `data/prod` when reasonable, but confirm if uncertain
4. **Report results clearly** — the script logs matched/skipped/moved/overwritten/failed counts; relay these to the user
