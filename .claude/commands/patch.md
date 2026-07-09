Apply an evolution proposal to configuration files.

Ask the user for:
- **File** (-f, required) — path to the validated evolution proposal JSON (e.g., `data/prod/26.7.8/xaut/proposals/proposal_20260709.json`)
- **Symbol** (--symbol, optional) — trading pair prefix (e.g., XAUT, BTC). If provided, patches `symbol_config.yaml` overrides first, then falls back to `strategy_config.yaml`. Without --symbol, patches `strategy_config.yaml` directly.

Then run:
```
python run.py patch -f <FILE> [--symbol <SYMBOL>]
```

The patcher writes config changes atomically and can also apply prompt refinements to `config/prompts/*.md` files. Run `patch` after `evolution` produces a proposal.
