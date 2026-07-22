Place an OTOCO (entry + nested TP/SL) order from a session report JSON, independently of the Sniper daemon.

Ask the user for:
- **Session file** (-f, required) — path to a session JSON (e.g., data/prod/sessions/XAUTUSDT_session_20260706_031700.json)
- **Quantity** (-qty) — explicit order quantity in base asset units (e.g., 0.179). Mutually exclusive with -balance.
- **Balance** (-b / --balance) — account equity in USDT to auto-calculate quantity from session risk params. Mutually exclusive with -qty.
- **Dry run** (--dry-run, optional) — run all checks but skip placing the actual order

One of `-qty` or `-balance` must be provided, but not both.

Then run:
```
python scripts/place_otoco.py -f <SESSION_FILE> -qty <QUANTITY> [--dry-run]
python scripts/place_otoco.py -f <SESSION_FILE> -balance <BALANCE> [--dry-run]
```

The script performs these pre-checks before placing the order:
- Direction sanity (entry/SL/TP directional relationship)
- Symbol exists in symbol_config.yaml
- Current price is between SL and TP (direction-aware)
- Warns if active orders exist
- Prints entry distance vs current price

Failed checks exit immediately. Warnings do not block execution.

After a successful OTOCO placement, the Sniper daemon's Guardian will automatically discover and protect the position once filled (partial TP ladder, trailing SL).

**IMPORTANT:** The user is responsible for ensuring the symbol has no existing positions before running this command. The script does not check position state — it only warns about active orders.
