Delete all artifacts (sessions, audits, klines, htmls) for a given project version.

Ask the user for:
- **Path** (-p, required) — data root directory (e.g., data/prod, data/backtest/v26.7.8_r14)
- **Version** (-v, required) — project version (e.g., 26.7.13)

Always run with **--dry-run first** to preview what will be deleted. Then ask the user to confirm before running without --dry-run.

```bash
# Preview first
python scripts/clean_version_artifacts.py -p <PATH> -v <VERSION> --dry-run

# Execute (requires typing 'yes' to confirm)
python scripts/clean_version_artifacts.py -p <PATH> -v <VERSION>
```

The script:
1. Scans `{path}/sessions/` for active session JSONs whose `metadata.version_control.project_version` matches
2. Also scans `{path}/{version}/sessions/` for archived sessions
3. Derives matching audits, klines (all timeframes), and HTMLs by {symbol}_{type}_{timestamp} naming pattern
4. Shows a summary and asks for confirmation before deleting
