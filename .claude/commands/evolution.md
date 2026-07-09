Run AI meta-evolution on audit reports to optimize strategy config and prompts.

Ask the user for:
- **Path** (-p, required) — data root containing an `audits/` subdirectory (e.g., `data/prod/26.7.8/xaut`)
- **Symbol** (--symbol, required) — trading pair prefix (e.g., XAUT, BTC)
- **Samples** (--samples, required) — number of most recent audit reports to ingest (e.g., 5 for XAUT, 8 for BTC)

Then run:
```
python run.py evolution -p <PATH> --symbol <SYMBOL> --samples <N>
```

The Evolution Engine ingests forensic audit results, runs the AI Evolver agent to identify systematic logic failures, and generates a mutation proposal (config patches or prompt refinements). Output is a proposal JSON under `<data_root>/proposals/`.
