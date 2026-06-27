Calculate position size from a trading session file.

Ask the user for:
- **Session file** (-f, required) — path to a session JSON (e.g., data/prod/sessions/XAUT_session_20250628_120000.json). If the user gives only a symbol, find the latest session file for that symbol under `data/prod/sessions/`.
- **Balance in USDT** (-b, required) — the account equity to size against.

Then run:
```
./venv/bin/python3 scripts/calculate_qty.py -f <SESSION_FILE> -b <BALANCE>
```

Present results as a clean summary table: opinion, confidence, entry, SL, delta (pts + %), equity, risk %, max loss, and final sized qty.
