---
name: calculate-qty
description: Use when the user asks to calculate position size, quantity, or qty from a trading session file — whenever they mention "calculate_qty", "size my position", "how much XAUT/BTC to buy", or ask to run the calculate_qty script against a session report/JSON.
---

# Calculate Qty

## Overview

Run `scripts/calculate_qty.py` against a session JSON to compute position size from equity, risk parameters, and the session's tactical entry/SL prices. The script reads risk config from `config/global_config.yaml` and symbol precision from `src/config/symbol_resolver.py`.

## Core Pattern

```bash
./venv/bin/python3 scripts/calculate_qty.py \
  -f data/prod/sessions/<SESSION_FILE>.json \
  -b <balance_usdt>
```

## Session Files

Sessions live under `data/<env>/sessions/` named `<SYMBOL>_session_YYYYMMDD_HHMMSS.json`.

To find the latest for a symbol:
```bash
ls -t data/prod/sessions/<SYMBOL>*_session_*.json | head -1
```

Session files contain `final_decision.tactical_parameters` (entry, stop_loss, take_profit) and `final_decision.opinion` — the script extracts these automatically.

## Required Inputs

| Input | Source |
|-------|--------|
| Session file | `-f <path>` — latest from `data/prod/sessions/` or user-provided |
| Balance (USDT) | `-b <float>` — user must provide; ask if missing |

If the user names a symbol but no specific session file, find the latest for that symbol.

## What Gets Calculated

- **Max loss**: `equity × risk_per_trade` (from `config/global_config.yaml`)
- **Target qty**: `max_loss / |entry − SL|`
- **Final qty**: target rounded to symbol's `precision_qty`, floored to `min_order_qty`
- **Notional**: `final_qty × entry`
- **Leverage**: `notional / equity`

## Presenting Results

Show a clean summary table — not just raw script output. Include: opinion, confidence, entry, SL, delta (pts + %), equity, risk %, max loss, and the final sized qty.

## Common Mistakes

- **Using system python**: Must use `./venv/bin/python3` — the venv has `yaml` and project modules.
- **Wrong session directory**: Prod sessions are in `data/prod/sessions/`, not `data/` root.
- **Forgetting balance**: The script requires `-b` — ask the user if they don't provide it.
