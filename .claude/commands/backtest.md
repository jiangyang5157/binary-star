Run a historical backtest session using sniper-sampled time points.

Ask the user for:
- **Symbol** (required, e.g., BTC, XAUT)
- **Start date** (default: T-15d = 15 days ago)
- **End date** (default: T-1d = yesterday)
- **Samples** (default: 14)
- **Data prefix** (default: derived from the current version branch, e.g., v26.6.26_r14)

Then run:
```
python run.py session --start <START> --end <END> --samples <N> --symbol <SYMBOL> -p data/backtest/<PREFIX>
```

Results are archived as JSON in `<PREFIX>/sessions/`.
