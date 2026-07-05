Run a forensic audit on trading sessions.

Ask the user for:
- **Path** (-p, required) — data root directory (e.g., data/prod, data/backtest/v26.7.8_r14)
- **File** (--file, optional) — a single session JSON file to audit. If omitted, audits all sessions under the path.

Then run:
```
python run.py audit -p <PATH> [--file <FILE>]
```

The audit cross-references AI decisions against actual market outcomes, checks RR-ratio compliance, and flags structural violations in the Binary Star debate log.
