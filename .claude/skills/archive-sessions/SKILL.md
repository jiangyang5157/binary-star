---
name: archive-sessions
description: >
  Use when the user wants to archive, move, or organize session report files
  into a version folder (e.g., "archive all BTC sessions to 26.7.8",
  "move my sessions to a new version folder", "organize sessions by version",
  "archive sessions to v26.7.8"). Also trigger when the user mentions moving
  session JSON files under data/prod/sessions/ into a subfolder. Supports
  --symbol filtering (BTC, XAUT, or comma-separated) and --dry-run preview.
---

# Archive Sessions

Move session JSON files from `<data_root>/sessions/` into a versioned archive
folder `<data_root>/<version>/`. Creates the target folder if it doesn't exist;
overwrites on name collision.

## Usage

Run the script directly — no subagents needed:

```bash
python scripts/archive_sessions.py -p <data_root> -v <version> [--symbol SYM] [--dry-run] [--verbose]
```

**Arguments:**

| Arg | Required | Description |
|-----|----------|-------------|
| `-p`, `--path` | yes | Data root directory, e.g. `data/prod` |
| `-v`, `--version` | yes | Version folder name, e.g. `26.7.8` |
| `--symbol` | no | Comma-separated symbol filter, e.g. `BTC` or `BTC,XAUT` |
| `--dry-run` | no | Preview without moving files |
| `--verbose` | no | Debug-level logging |

## Examples

```bash
# Archive all session files to data/prod/26.7.8/
python scripts/archive_sessions.py -p data/prod -v 26.7.8

# Archive only BTC sessions
python scripts/archive_sessions.py -p data/prod -v 26.7.8 --symbol BTC

# Archive BTC and XAUT sessions
python scripts/archive_sessions.py -p data/prod -v 26.7.8 --symbol BTC,XAUT

# Preview what would happen
python scripts/archive_sessions.py -p data/prod -v 26.7.8 --dry-run
```

## Important Rules

1. **Always use `--dry-run` first** — show the user what will be moved before executing the real move
2. **Ask for version if not provided** — the `-v` argument is required; if the user doesn't specify a version, ask
3. **Ask for path if ambiguous** — defaults to `data/prod` when reasonable, but confirm if uncertain
4. **Report results clearly** — the script logs moved/overwritten/failed counts; relay these to the user
