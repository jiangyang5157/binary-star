# Risk Assessment Framework

## Risk Scoring

Each finding is scored on three axes, each 1-5:

### Likelihood (L)
| Score | Description |
|-------|-------------|
| 1 | Requires multiple simultaneous failures (API down + specific price + specific timing) |
| 2 | Requires rare condition (e.g., manual intervention + specific market state) |
| 3 | Occasional (e.g., happens during specific regime or once per week) |
| 4 | Common (e.g., every daemon restart, every pivot) |
| 5 | Continuous (e.g., present on every pulse, every code path) |

### Impact (I)
| Score | Description |
|-------|-------------|
| 1 | Cosmetic (log message, minor inefficiency) |
| 2 | Minor (dust position, unnecessary API call) |
| 3 | Moderate (wrong OCO params, recoverable on next pulse) |
| 4 | Serious (naked position for one pulse, potential loss up to 1 ATR) |
| 5 | Critical (position loss, systemic failure, unbounded downside) |

### Detectability (D)
| Score | Description |
|-------|-------------|
| 1 | Impossible to miss (daemon crash, loud log, dashboard alert) |
| 2 | Likely noticed (error log, heartbeat anomaly) |
| 3 | Might notice (warning log, subtle state inconsistency) |
| 4 | Hard to detect (no log, silent wrong behavior) |
| 5 | Invisible (no indication until financial loss discovered) |

### Risk Score = L × I × D
- **CRITICAL**: > 60 — fix immediately
- **HIGH**: 30–60 — fix in next release
- **MEDIUM**: 15–29 — track, fix when nearby
- **LOW**: < 15 — document, accept risk

---

## Pre-Identified Risk Patterns

These are patterns to look for during audit. Each finding should be scored against the matrix above.

### Pattern A: Naked Position Window
**Description**: Between cancel and re-place of OCO, position has no protection.
**Typical scores**: L=3 (every OCO migration), I=4 (1 ATR risk), D=4 (no log during gap) → Risk=48 (HIGH)
**Mitigation**: Minimize API calls between cancel and place. Consider using OCO replace instead of cancel+place.

### Pattern B: Silent API Failure Propagation
**Description**: API returns error value (0, None, []) that downstream code treats as valid.
**Example**: `get_ticker_price` returns 0 → SL breach check triggers false emergency close.
**Typical scores**: L=2 (API failures rare), I=5 (unnecessary position close), D=4 (no indication price was 0) → Risk=40 (HIGH)

### Pattern C: State Drift Without Correction
**Description**: Daemon's trade_state diverges from exchange reality, no auto-correction.
**Example**: Direction sanity check logs but doesn't fix wrong-side OCO.
**Typical scores**: L=2 (manual intervention), I=5 (wrong-side orders could execute unexpectedly), D=5 (silent until fill) → Risk=50 (HIGH)

### Pattern D: Restart Blindness
**Description**: On daemon restart, certain states are not reconstructed, leaving gaps.
**Example**: Pending entry order not tracked after restart.
**Typical scores**: L=2 (restarts infrequent), I=3 (entry order fills unprotected), D=5 (no tracking → no protection) → Risk=30 (HIGH)

### Pattern E: Emergency Close Failure Cascade
**Description**: Emergency close fails → retry next pulse → position naked for N pulses.
**Example**: Network blip during emergency close, executor returns with trade_state intact for retry.
**Typical scores**: L=1 (API must fail twice), I=5 (unprotected), D=4 (log exists but operator may not see) → Risk=20 (MEDIUM)

### Pattern F: Incorrect Rounding Direction
**Description**: Price rounding that moves SL in the wrong direction (away from safety).
**Example**: Banker's rounding on SL instead of floor/ceil toward safety.
**Typical scores**: L=4 (every OCO placement), I=1 (at most 0.5 tick), D=5 (invisible) → Risk=20 (MEDIUM)

### Pattern G: Qty Precision Truncation
**Description**: Qty rounding could silently increase position size beyond risk limits.
**Example**: `round(qty, p_qty)` may round up for .5 values.
**Typical scores**: L=2, I=2 (tiny increase), D=5 (invisible) → Risk=20 (MEDIUM)

### Pattern H: Missing Min-Notional Check
**Description**: After partial TP, remaining qty may be below exchange minimum.
**Example**: 0.5 → L1(0.1) → L2(0.08) → L3(0.064) → remaining 0.256. If min is 0.001, OK. But for low-price assets?
**Typical scores**: L=1 (only extreme partial fills), I=3 (order rejection, position stuck), D=3 (error log) → Risk=9 (LOW)

---

## Maximum Loss Scenarios

### Scenario: Naked Position During Crash
1. OCO being migrated (cancel succeeded, place pending)
2. Exchange flash crash: price drops 5% in 100ms
3. Position has no SL on exchange → full 5% loss taken
4. With SL: would have exited at ~1-2% loss (slippage)
5. Excess loss: ~3-4% of position value

### Scenario: Wrong-Side OCO After Manual Flip
1. User manually flips LONG → SHORT
2. OCO still on exchange for LONG exit (SELL LIMIT + SELL SL)
3. SELL SL at 68000: for SHORT position, this is a TAKE-PROFIT (buy at 70000, sell at 68000 = loss)
4. SELL LIMIT at 75000: for SHORT position, this would close at a bigger loss
5. Neither order protects the SHORT from adverse moves

### Scenario: False Emergency Close From Ticker=0
1. `get_ticker_price` returns 0 during API degradation
2. LONG SL breach check: `0 <= 73000` → True → emergency close
3. Position closed at market, possibly at a loss
4. API recovers, daemon sees flat position, waits for next AI trigger
5. Unnecessary realized loss + missed opportunity
