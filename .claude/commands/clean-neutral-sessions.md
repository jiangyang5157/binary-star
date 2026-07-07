Delete NEUTRAL session reports — sessions where the Binary Star debate converged on no trade.

Ask the user for:
- **Path** (-p, required) — data root directory (e.g., data/prod, data/backtest/v226.7.8_r14)
- **Symbol** (--symbol, optional) — comma-separated symbol list (e.g., XAUT,BTC). If omitted, all symbols are processed.
- **Dry run** (--dry-run, optional) — scan and report without deleting.

Then run:
```
python scripts/clean_neutral_sessions.py -p <PATH> [--symbol <SYMBOL>] [--dry-run]
```
