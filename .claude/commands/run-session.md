Run a live Binary Star analysis cycle for a single symbol.

Ask the user for:
- **Symbol** (--symbol, required) — trading pair prefix (e.g., BTC, XAUT)
- **Path** (-p, optional) — data root directory (defaults to `data/prod`)

Then run:
```
python run.py session -p <PATH> --symbol <SYMBOL>
```

The Binary Star debate runs planner vs critic rounds with math fact-checking, producing a session JSON under `<data_root>/sessions/`. Use `--write_status` to enable progress polling.
