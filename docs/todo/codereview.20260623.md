# Singularity Code Review — Remaining Items (2026-06-23)

**26 items fixed across 4 rounds.** This report contains only what's left.

---

## Open Bugs (7)

### High Severity

| # | File | Line | Issue |
|---|------|------|-------|
| 1 | `order_executor.py` | 83-84,165 | **Emergency market close result unchecked** — if `execute_market_close` fails, code proceeds to place a new entry order, risking double exposure |
| 2 | `margin_client.py` | 195 | **`MARGIN_BUY` hardcoded for sell orders** — `execute_market_close` always sends `sideEffectType="MARGIN_BUY"` regardless of direction. For sells, should be `AUTO_REPAY` |
| 4 | `client.py` | 139-140 | **Silent data loss in paginated kline fetch** — partial results discarded on mid-stream failure |

### Resolved (all other bugs fixed in rounds 1-4)

---

## Naming Issues (5)

- **Triple naming for cache ID**: Same object called `cache_resource_name` (orchestrator), `cached_content` (base_agent), `cache_id` (debate_loop).
- **`"session"` overloaded**: SessionAgent (LLM role), `session.log` (log file), `execute_session_cycle()` (single inference), `session_config` (config object).
- **`strength` vs `vacuum_score`**: HVN nodes carry `"strength"`, LVN nodes carry `"vacuum_score"` — inconsistent keys when nodes are merged.
- **`resolve_all` vs `resolve_config`**: Very similar names, very different behaviors — `resolve_all` is the main entry point.
- **Version numbers in comments**: `v6.12`, `v7.1`, `v8.0` scattered everywhere with no change context.

---

## Duplication (4)

- **6 copies** of `sys.path.insert(0, project_root)` across `run.py` and all `run_*.py`.
- **2 copies** of date-parsing logic (`_parse_date` in `run.py` vs `parse_date` in `run_session.py`).
- **2 copies** of mode-detection logic (simulation/backtest/prod) in `run.py` and `run_session.py`.
- **Full argparse duplicates** — each `run_*.py` has a standalone `main()` that duplicates the subcommand handler in `run.py`.

---

## Observability (3)

- **Remove emoji from log files** — `💤`, `🔫`, `✅` in structured logs break ASCII-only log aggregators.
- **Add data quality metrics** — Kline/API response mappers default missing fields to `0`, silently masking data issues. Log when defaults are triggered.
- **Circuit breaker doesn't break** — `SessionEngine` circuit breaker only alerts; never stops sending requests.

---

## Config System (4)

- **Unify YAML loading** — Three different functions (`load_config`, `load_global_config`, `_load_yaml`) with different error behaviors. Consolidate into one.
- **Add schema validation** — Config values have no runtime type/shape validation. Missing keys cause cryptic `KeyError` deep in the stack. Consider Pydantic or `__post_init__` validation.
- **Fix visual config isolation** — `load_visual_config` ignores its `cfg` parameter and reads from disk independently. Escapes symbol override resolution.
- **Eliminate unpacking anti-pattern** — `BinaryStarOrchestrator.__init__` unpacks every `BinaryStarConfig` field onto `self`. Use `self.bs.field_name` directly.

---

## Error Handling (3)

- **Use the exception hierarchy** — `exceptions.py` defines `AgentInferenceError`, `MalformedJSONError`, etc. but run scripts catch bare `Exception` everywhere.
- **Don't silently return `{}`** — `_load_yaml` returns `{}` on parse failures. Log a warning at minimum.
- **`deep_merge` list behavior** — Replaces lists instead of merging. Future config sections with list values will silently overwrite.

---

## Architecture / SRP (10)

- **`BinaryStarOrchestrator.__init__` is a god constructor** — Constructs 10+ collaborators directly. Only `exchange_client` is injectable.
- **`OrderExecutor` is 650+ lines** — Split into `EntryExecutor` + `Guardian`.
- **`SniperTrigger._check_type_b` is 88 lines** — Five sub-strategies in one method.
- **`BaseAgent._execute_ai_cycle` is 170 lines** — Decompose into smaller methods.
- **`AuditController` hardcodes `BinanceFuturesClient()`** — No injection point.
- **`MathTools` is a static-methods-only class** — Use module-level functions.
- **`MathTools` methods take 17–22 parameters** — Bundle into typed dataclasses.
- **`LiquidationRadar` doesn't use actual liquidation data** — `fetch_liquidations` always returns `None`. Either implement or rename.
- **`BinanceMarginClient` doesn't implement `AbstractExchangeClient`** — Polymorphism gap.
- **`TopographyEngine` hardcodes `BinanceFuturesClient`** — Cannot swap exchanges.
- **No centralized prompt template engine** — Missing template variables silently render as `{key}`.

---

## Testability (4)

- Most analyzer/agent classes construct dependencies internally. DI is the exception.
- `EvolverSandbox` creates real `BinaryStarOrchestrator` and `AuditController` — no mocking seam.
- `ConfigPatcher.apply_patch()` writes to disk — returns 0/1, no assertion surface for tests.
- `market_observer.py:714-718` — Micro chart snapshot passes `atr_macro` instead of `atr_micro`, potentially wrong scaling.

---

## Suggested Fix Order

| Round | Items | Effort |
|-------|-------|--------|
| 5 | Emoji cleanup, `_load_yaml` warning, `strength`→`vacuum_score`, sys.path consolidation | Trivial |
| 6 | Date-parse consolidation, mode-detection consolidation, circuit breaker | Easy |
| 7 | Version number cleanup, exception hierarchy usage, `MathTools` → module functions | Easy–Medium |
| 8+ | God constructors, SRP splits, DI refactors, prompt template engine | Medium–Hard |
| Final | Bugs #1, #2, #4 — require Binance SAPI domain knowledge | Hard |
