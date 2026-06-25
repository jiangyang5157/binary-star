Start the Sniper monitoring daemon in observe-only mode (no AI, no trades).

If the user has **not specified symbols**, ask them which symbols they want to monitor (e.g., BTC, XAUT, ETH). Symbols use prefix format — the quote currency is appended from global_config.yaml (default: USDT). Do not proceed until symbols are confirmed.

Once symbols are confirmed, run:
```
python run.py sniper -p data/prod --symbol <SYMBOLS>
```

This mode only logs signal evaluations and trigger state — zero LLM cost, zero trade execution. Safe for indefinite monitoring.

If the user wants AI reasoning on trigger, suggest they add `--llm`. If they want live trading, suggest `--trade` (implies `--llm`). Both require explicit confirmation before enabling.
