# singularity-market MCP Server Design

**Date:** 2026-07-10
**Status:** approved

## Overview

`singularity-market` is a read-only MCP server exposing Binance futures market data to LLM agents. It is the first phase of the [MCP server suitability analysis](../mcp-server-suitability-analysis.md) — Tier 1: Market Data Query Layer.

**Principle:** Zero source code changes. The MCP server imports existing infrastructure (`BinanceFuturesClient`, analyzers, config pipeline) as a consumer. Production paths (sniper, sessions) are untouched. Refactoring source code to call MCP happens in a follow-up phase.

## Tools (8 total)

### Raw Data Tools (7)

Thin wrappers around `BinanceFuturesClient`. Each tool creates a client, calls one method, and closes.

| # | Tool | Parameters | Binance SDK Call | Returns |
|---|------|-----------|-------------------|---------|
| 1 | `fetch_klines` | `symbol: str, interval: str, limit: int` | `client.klines()` | `List[Kline]` — open_time, open, high, low, close, volume |
| 2 | `fetch_order_book` | `symbol: str, limit: int` | `client.depth()` | `OrderBook` — bids, asks, timestamp |
| 3 | `fetch_open_interest` | `symbol: str, period: str, limit: int` | `open_interest_hist()` | `List[OI]` — open_interest, timestamp |
| 4 | `fetch_funding_rate` | `symbol: str, limit: int` | `funding_rate()` | `List[FundingRate]` — funding_rate, timestamp |
| 5 | `fetch_taker_long_short_ratio` | `symbol: str, period: str, limit: int` | `taker_long_short_ratio()` | `List[Ratio]` — long_short_ratio, timestamp |
| 6 | `fetch_long_short_ratio` | `symbol: str, period: str, limit: int` | `long_short_account_ratio()` | `List[Ratio]` — long_short_ratio, timestamp |
| 7 | `fetch_top_long_short_ratio` | `symbol: str, period: str, limit: int` | `top_long_short_account_ratio()` | `List[Ratio]` — long_short_ratio, timestamp |

**Note:** `fetch_liquidations` is intentionally excluded — Binance's public liquidation endpoint is deprecated and `BinanceFuturesClient.fetch_liquidations()` always returns `None`.

### Composite Tool (1)

| # | Tool | Parameters | Returns |
|---|------|-----------|---------|
| 8 | `analyze_market` | `symbol: str` | Regime + Volume Profile + Liquidation Zones + Price Dynamics |

**Internal data flow** (mirrors `SniperScout.scout()` exactly):

```
analyze_market(symbol)
  │
  ├─ 1. Config Resolution (same as SniperScout.__init__)
  │     load_config() → resolve_config(symbol)
  │     load_global_config() → resolve_config(symbol)
  │     merge → MarketObserverConfig.from_dict()
  │
  ├─ 2. Analyzer Init (same parameter mapping as SniperScout)
  │     VolumeProfileAnalyzer(config=vp_cfg)
  │     MarketRegimeAnalyzer(config=rg_cfg)
  │     LiquidationEstimator(...)
  │     MarketDataLoader(exchange_client, obs_config)
  │     MarketMetricsRefiner(obs_config, vp, regime, radar)
  │
  ├─ 3. Data Collection (same as SniperScout.scout())
  │     raw = loader.collect(symbol, datetime.now(UTC))
  │     → fetches macro klines + micro klines + OI + taker ratio + funding rate
  │     → ~10 Binance API calls (identical to sniper pulse)
  │
  ├─ 4. Refinement (same as SniperScout.scout())
  │     metrics, m_df, n_df = refiner.refine(raw)
  │     → ProcessedMarketMetrics with all 5 sub-dicts populated
  │
  └─ 5. Return subset for LLM
        regime + volume_profile + liquidation_zones + price_dynamics
```

**Return structure:**

```python
{
    "symbol": "BTCUSDT",
    "timestamp": "2026-07-10T12:00:00Z",
    "price_dynamics": {
        "current_price": float,
        "atr_macro": float
    },
    "market_regime": {
        "squeeze_factor": float,          # <1.0 = squeeze, >1.0 = expansion
        "trend_intensity": float,         # [-1, 1], signed efficiency ratio
        "wick_skew_regime": float,        # upper vs lower wick asymmetry
        "volume_participation_ratio": float  # current vol / MA vol
    },
    "volume_profile": {
        "poc": float,                     # Point of Control
        "vah": float,                     # Value Area High
        "val": float,                     # Value Area Low
        "volume_span_atr": float,         # VA width in ATR units
        "nearest_hvn_dist_atr": float,    # distance to nearest high-volume node
        "nearest_lvn_dist_atr": float,    # distance to nearest low-volume node
        "anchors_above": [
            {"price": float, "strength": float, "type": "HVN"},           # HVN node
            {"price": float, "vacuum_score": float, "type": "LVN"},       # LVN node
            ...
        ],
        "anchors_below": [
            {"price": float, "strength": float, "type": "HVN"},           # HVN node
            {"price": float, "vacuum_score": float, "type": "LVN"},       # LVN node
            ...
        ],
        "poc_dist_atr": float,              # (price - POC) / atr
        "vah_dist_atr": float,              # (price - VAH) / atr
        "val_dist_atr": float               # (price - VAL) / atr
    },
    "liquidation_zones": {
        "long_liquidation": [{"price": float, "intensity": float}, ...],
        "short_liquidation": [{"price": float, "intensity": float}, ...]
    }
}
```

## Config Strategy

**100% from existing YAML configs.** The MCP server reads `config/strategy_config.yaml`, `config/global_config.yaml`, and `config/symbol_config.yaml` through the same pipeline as `SniperScout`:

```python
strategy_cfg = resolve_config(load_config(), symbol)
global_cfg   = resolve_config(load_global_config(), symbol)
full_cfg     = {**strategy_cfg, **global_cfg}
obs_config   = MarketObserverConfig.from_dict(full_cfg)
```

- `load_config()` is `@lru_cache`'d — same process reads file once
- Per-symbol overrides (e.g. BTC's `trend_intensity_min_expansion: 0.12`) apply automatically via `resolve_config()`
- YAML changes take effect on MCP server restart

**No indicator values are hardcoded.** Every parameter (BB period, ATR period, volume thresholds, liquidation radar settings, etc.) flows from config → `MarketObserverConfig` → analyzers.

## Symbol Format

Full Binance trading pair: `"BTCUSDT"`, `"XAUTUSDT"`, `"ETHUSDT"`.

No short-code resolution (e.g. `"BTC"` → `"BTCUSDT"`). This matches existing system behavior — short-code resolution is handled at higher layers (session runner, sniper config), not at the exchange client level.

## Directory Structure

```
mcp_servers/
  singularity_market/
    __init__.py
    server.py              # FastMCP app, registers 8 tools
    tools/
      __init__.py
      raw_data.py          # Tools 1-7: thin BinanceFuturesClient wrappers
      market_analysis.py   # Tool 8: analyze_market composite
```

## Dependency Map

```
mcp_servers/singularity_market/
  │
  ├─ src/infrastructure/binance/client.py        → BinanceFuturesClient
  ├─ src/analyzer/market_observer.py             → MarketObserverConfig, MarketDataLoader, MarketMetricsRefiner
  ├─ src/analyzer/volume_profile.py              → VolumeProfileAnalyzer, VolumeProfileConfig
  ├─ src/analyzer/market_regime.py               → MarketRegimeAnalyzer, MarketRegimeConfig
  ├─ src/analyzer/liquidation_estimator.py       → LiquidationEstimator
  ├─ src/config/symbol_resolver.py               → resolve_config
  └─ src/utils/pipeline_utils.py                 → load_config, load_global_config
```

No new abstractions. Every import is from existing `src/` modules.

## Key Implementation Details

### Client lifecycle

Each tool call creates and closes its own `BinanceFuturesClient`:

```python
@mcp.tool()
async def fetch_klines(symbol: str, interval: str, limit: int) -> list[dict]:
    client = BinanceFuturesClient()
    try:
        klines = client.fetch_historical_klines(symbol, interval, limit)
        return [_kline_to_dict(k) for k in klines]
    finally:
        client.close()
```

`analyze_market` follows the same pattern — one client for all internal fetches.

### `analyze_market` init overhead

Config loading + analyzer initialization runs on every `analyze_market` call. This is intentional:
- `load_config()` / `load_global_config()` are `@lru_cache`'d — file read on first call only
- Per-symbol `resolve_config()` is cheap — dict merge
- Analyzer construction is lightweight — no network I/O, just dataclass instantiation
- Cost is negligible compared to the ~10 Binance API calls that follow

### Data subset for LLM

`MarketMetricsRefiner.refine()` returns a full `ProcessedMarketMetrics` with 5 sub-dicts. `analyze_market` returns a subset:

| Sub-dict | Returned? | Reason |
|----------|-----------|--------|
| `price_dynamics` | Partial — `current_price`, `atr_macro` only | Context for price levels |
| `market_regime` | Full | Core analysis |
| `structural_anchors` | Merged into `volume_profile` (poc_dist_atr, vah_dist_atr, val_dist_atr) | Consolidates fair-value info |
| `volume_profile` | Full (minus `profile_data` 300-bin array) | Structural levels |
| `sentiment_signals` | Partial — `liquidation_clusters` only | Other sentiment fields (CVD, funding rate) available via raw data tools |

## `.mcp.json`

```json
{
  "mcpServers": {
    "singularity-market": {
      "command": "python",
      "args": ["mcp_servers/singularity_market/server.py"],
      "cwd": "/Users/yangjiang/workspace/crypto"
    }
  }
}
```

## What This Phase Does NOT Do

- **Does not modify any source code** in `src/`. MCP server is a new consumer.
- **Does not refactor** sniper/session paths to call MCP. That is a follow-up phase.
- **Does not include Tier 2+ tools** (sessions, sniper state, audits). Those are separate MCP tools or servers.
- **Does not handle authenticated endpoints.** All 8 tools use public Binance API.
