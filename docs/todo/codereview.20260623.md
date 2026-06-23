# Singularity Code Review — Remaining Items (2026-06-23)

**34 items fixed across 7 rounds.**

---

## Open Bugs (2)

| # | File | Issue |
|---|------|-------|
| 1 | `order_executor.py:83-84,165` | Emergency market close result unchecked — double exposure risk |
| 2 | `client.py:139-140` | Silent data loss in paginated kline fetch |

---

## Naming (2)

- **`"session"` overloaded**: SessionAgent (LLM role), `session.log` (log file), `execute_session_cycle()` (single inference), `session_config` (config object).
- **`cache_id` still used locally in debate_loop**: renamed `cached_content` → `cache_resource_name` in base_agent, but debate_loop still uses `self.cache_id`. Minor.

---

## Duplication (2)

- **6 copies** of `sys.path.insert(0, project_root)` — intentional bootstrap, cannot consolidate.
- **Full argparse duplicates** — each `run_*.py` has a standalone `main()` that duplicates the subcommand handler in `run.py`.

---

## Observability (1)

- **Add data quality metrics** — Kline/API response mappers default missing fields to `0`, silently masking data issues.

---

## Config System (4)

- **Unify YAML loading** — Three different functions (`load_config`, `load_global_config`, `_load_yaml`) with different error behaviors.
- **Add schema validation** — Missing config keys cause cryptic `KeyError`. Consider Pydantic or `__post_init__`.
- **Fix visual config isolation** — `load_visual_config` ignores its `cfg` parameter, escapes symbol resolution.
- **Eliminate unpacking anti-pattern** — `BinaryStarOrchestrator.__init__` unpacks every `BinaryStarConfig` field onto `self`.

---

## Error Handling (2)

- **Use the exception hierarchy** — `exceptions.py` defines typed exceptions but run scripts catch bare `Exception`.
- **`deep_merge` list behavior** — Replaces lists instead of merging.

---

## Architecture / SRP (10)

- **`BinaryStarOrchestrator.__init__`** — god constructor, 10+ collaborators, only `exchange_client` injectable.
- **`OrderExecutor` is 650+ lines** — split into `EntryExecutor` + `Guardian`.
- **`SniperTrigger._check_type_b` is 88 lines** — five sub-strategies in one method.
- **`BaseAgent._execute_ai_cycle` is 170 lines** — decompose into smaller methods.
- **`AuditController` hardcodes `BinanceFuturesClient()`** — no injection point.
- **`MathTools` is a static-methods-only class** — use module-level functions.
- **`MathTools` methods take 17–22 parameters** — bundle into typed dataclasses.
- **`LiquidationRadar` doesn't use actual liquidation data** — `fetch_liquidations` always returns `None`.
- **`BinanceMarginClient` doesn't implement `AbstractExchangeClient`** — polymorphism gap.
- **`TopographyEngine` hardcodes `BinanceFuturesClient`** — cannot swap exchanges.
- **No centralized prompt template engine** — missing template variables silently render as `{key}`.

---

## Testability (4)

- Most analyzer/agent classes construct dependencies internally (DI is the exception).
- `EvolverSandbox` creates real `BinaryStarOrchestrator` and `AuditController` — no mocking seam.
- `ConfigPatcher.apply_patch()` writes to disk — returns 0/1, no assertion surface.
- `market_observer.py:714-718` — micro chart snapshot passes `atr_macro` instead of `atr_micro`.
