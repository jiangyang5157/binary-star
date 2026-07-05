Delete orphaned klines images, audit files, and session HTMLs that have no matching session report.

Session reports under `sessions/` are the source of truth. After deleting sessions (e.g. via clean-neutral-sessions), run this to purge their orphaned artifacts.

Ask the user for:
- **Path** (-p, required) — data root directory (e.g., data/prod, data/backtest/v26.7.8_r14)
- **Symbol** (--symbol, optional) — comma-separated symbol list (e.g., BTC, BTC,XAUT). If omitted, all symbols are processed.
- **Dry run** (--dry-run / -n, optional) — scan and report without deleting.

Then run:
```
python scripts/clean_orphan_artifacts.py -p <PATH> [--symbol <SYMBOL>] [--dry-run]
```
