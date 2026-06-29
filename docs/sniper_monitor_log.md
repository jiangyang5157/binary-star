# Sniper Monitor Log

> Started: 2026-06-30 03:07 UTC (Session: v26.7.02)
> Symbols: BTCUSDT, XAUTUSDT | Trade: Enabled ($800 manual balance)
> Observing: Order management, TP/SL guardian, OCO lifecycle

---

## 03:07 — Initial State (Session Start)

- **Account Balance**: $1,252.38 USDT
- **BTCUSDT**: no position, no orders, cooldown 37.5 min remaining
- **XAUTUSDT**: no position, no orders, cooldown 37.5 min remaining
- Both symbols clearing trade state (fresh daemon restart from `run_sniper.py`)
- Signal stack active: base threshold 0.35, emergency 0.8, detectors 13
- Active LLM provider: DeepSeek (deepseek-v4-pro)

## 03:07–03:17 — Baseline Pulses (6 pulses observed)

All 6 pulses across both symbols show **zero signal stacking**:
- **CVD**: |cvd| <= 0.1 always → cvd_momentum/divergence/absorption all rejected
- **Volatility**: vii=1.36 (flat), vpr 0.16→0.34 (rising slowly but below 1.5 threshold)
- **Squeeze**: BTC R consistently (sf 0.696–0.728 ≥ 0.750); XAUT sporadic but low
- **Structural**: Price 9–18 ATR from VAH/VAL, no boundary tests
- **Trend**: BTC |trend|=0.12–0.16 (below 0.35), XAUT flat at 0.03–0.05
- **LS Ratio**: BTC 2.44→2.47 (neutral range), XAUT 0.58 (neutral)
- **OI**: No divergence detected, |oi_d| ≈ 0.0001–0.0003

**Assessment**: Typical quiet period. Cooldown from ~37.5 min started at 15:07 UTC.

## 03:15 — Pulse (latest)
- Last heartbeat: `last_pulse_at: 2026-06-29T15:15:35.397Z`
- Zero changes in any state variable

---

## 03:17–03:23 — Continued Quiet Pulses (Pulses 7–10)

All signals rejected across both symbols. Pattern unchanged:
- BTC CVD oscillates -0.039 to -0.061 (flat)
- XAUT CVD -0.157 to -0.174 (moderate but below thresholds)
- VPR slowly rising 0.34→0.44 (BTC) but still far from 1.5 surge threshold
- No structural proximity, no trend pullback, no squeeze
- heartbeat every ~2 min, all clear

---

## 03:23 — Pulse 10: First detector fires (trivial)

- **XAUTUSDT**: `taker_imbalance=F:0.0` — first F signal of the session, but strength is **0.0** (effectively zero, just the detector logic tripped). Not meaningful.
- Everything else all R.
- BTC CVD = -0.061, still flat.
- XAUT CVD deepening: -0.174 → -0.201 (still below thresholds).

---

## 03:23–03:28 — Weak detector flickers (sub-threshold)

- **03:23** XAUT `taker_imbalance` F:0.0 (first F, zero strength)
- **03:26** XAUT `trend_pullback` F:0.04 (negligible)
- **03:28** BTC `squeeze` F:0.07 (first squeeze flicker, still negligible)

These are sub-threshold flickers — the detectors are alive and running, but no signal has meaningful strength. All remain >10× below the 0.35 base trigger threshold.

BTC VPR slowly climbing: 0.28 → 0.51 over ~20 min. Still far from vol_surge threshold (1.5).

---

## 03:53 — ⚡ TRIGGER: BTCUSDT SHORT Session

After ~46 min of silence, signal stack triggered an AI session on BTCUSDT:
- **Opinion**: SHORT | entry=60300 | tp=58884 | sl=61200
- **State**: FLAT → placing LIMIT entry (SELL)
- **Position sizing**: equity=$800, risk=0.8%, max_loss=$6.40
  - delta = |60300 - 61200| = $900
  - qty = $6.40 / $900 = **0.0071 BTC**
- **TP distance**: 60300 → 58884 = -1416 pts (2.35%)
- **SL distance**: 60300 → 61200 = +900 pts (1.49%)
- **R:R**: 1416/900 ≈ 1.57:1

## 03:53+ → 05:12 — LIMIT fill

- **03:53:21** — LIMIT SELL 0.0071 @ 60300 placed (order_id=63971292822)
- **05:12:46** — ✅ **FILLED!** Guardian activated for SHORT position qty=-0.0071
- **05:12:47** — OCO placed (TP=58884, SL=61200, slippage buffer applied)
- **Fill latency**: ~1h19m (price rose from ~59,500 to hit 60,300 entry)
- **Balance**: $1,252.38 → $1,680.51 (includes unrealized PnL from SHORT)

## 06:37 — ⚡ TRIGGER: XAUTUSDT SHORT Session

Second AI session triggered, also SHORT:
- **Opinion**: SHORT | entry=4019.75 | tp=3900.0 | sl=4115.0
- **Qty**: 0.067 XAUT (delta=$95.25, max_loss=$6.40)
- **R:R**: (4019.75-3900)/(4115-4019.75) = 119.75/95.25 ≈ **1.26:1**
- LIMIT SELL 0.067 @ 4019.75 placed, waiting for fill
- **Balance**: still $1,680.51 (XAUT not yet affecting)

## 07:19 — XAUT entry expired (not filled)

- projected_waiting_hours=0.7h (42 min) elapsed
- Price never reached 4019.75 → Guardian cancelled (order_id=133874433)
- Trade state cleared

## 09:13 — XAUT second trigger (BULLISH), but NEUTRAL outcome

- New signal stack: cvd_momentum + taker_imbalance + trend_pullback
- Confluence 0.43, regime=trending, gate=PASS
- AI Binary Star debate concluded: **NEUTRAL** (confidence=0.0%)
- No trade action taken

## BTC position status (as of ~21:26 UTC)

- **Still open**: SHORT 0.0071 @ 60,300 | held ~16h
- **OCO intact**: TP=58,884 / SL=61,200
- **No partial TP triggered** (price within ±1.5×ATR of entry)
- **No trailing migration** yet
- Balance steady at $1,680.51

---

## Key Reference: Config Parameters

### Guardian — Partial TP Levels
| Level | ATR Threshold | TP Ratio | SL Distance (ATR) |
|-------|:-------------:|:--------:|:-----------------:|
| L1    | 1.5×          | 20%      | 0.0 (→ breakeven) |
| L2    | 3.5×          | 20%      | 1.0 (trailing)    |
| L3    | 5.5×          | 20%      | 0.75 (tighten)    |
| Remain| —             | 40%      | via trailing      |

### Entry Qty Formula
```
qty = (equity × risk_per_trade) / |entry - sl|
risk_per_trade = 0.008 (0.8%)
```

### Synthetic OCO Architecture
- Binance Spot Margin (SAPI) → no native OCO
- Two independent LIMIT orders cross-managed by Guardian
- Cancel + re-place gap = **naked risk window** → emergency market close on failure
- Sentinel `_EMERGENCY_CLOSED_SENTINEL = -1` signals force-close to daemon
