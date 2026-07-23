# Structural Fingerprint — Sniper Noise Gate

## Problem

BTCUSDT repeatedly triggers AI sessions (~6 min intervals) that all conclude NEUTRAL. The signal stack detects genuine directional flow (BULLISH 0.30-0.63), but the AI debate deadlocks on the same structural constraint each time — anchor/shield conflicts that cannot be resolved because the market _structure_ (VAH, POC, HVN positions) has not changed. This wastes ~$0.50-1.50 per session on provider tokens with zero trading value.

**Root cause:** `break_on_strength_ratio: 1.6` and `stacked_break_count: 4` both bypass cooldown without checking whether the underlying structure has changed since the last trigger.

## Design

Add a **Structural Fingerprint** snapshot to `SniperTrigger`. Every time a trigger fires, record the key structural coordinates. Before allowing a cooldown break, compare the current structure against the snapshot. If unchanged, reject the break regardless of signal strength.

### Scope

- Only affects the **cooldown break** path in `_check_cooldown_break()`.
- **Normal cooldown expiration** is unaffected — when cooldown naturally expires, the fingerprint check does not run.
- **Emergency override** (`strength ≥ 0.85`) in `ConfluenceEngine.evaluate()` is unaffected — it bypasses cooldown entirely.
- **First trigger** after daemon restart has no fingerprint → falls through to current behavior.

### Data Structure

```python
@dataclass
class StructuralFingerprint:
    vah: float       # Value Area High
    val: float       # Value Area Low
    poc: float       # Point of Control
    price: float     # Current price at trigger
    atr_macro: float # ATR for normalization
    regime: str      # Market regime at trigger time
    timestamp: datetime
```

Stored as `SniperTrigger._fingerprint: StructuralFingerprint | None`. Per-symbol by design (one `SniperTrigger` instance per symbol).

### Snapshot Timing

Taken in `evaluate()` when `should_trigger` is confirmed — before the AI session runs, so the fingerprint reflects the structure that _caused_ the trigger, not the structure 60s later when the AI finishes.

```python
# In evaluate(), after should_trigger is determined
if should_trigger:
    self._save_fingerprint(current_metrics)
```

### Staleness Check — `_fingerprint_is_stale(metrics) → bool`

Called in `evaluate()` after `_check_cooldown_break()` returns True. If the structure is stale, the break is cancelled:

```python
if cooldown_active:
    cooldown_break = self._check_cooldown_break(fresh_signals)

    # ★ If signals say break but structure says unchanged → cancel break
    if cooldown_break and self._fingerprint_is_stale(metrics):
        cooldown_break = False
```

**Return value semantics:** `True` = current structure matches the saved fingerprint (stale → unchanged → block the break). `False` = structure has diverged (fresh → allow the break through).

If `self._fingerprint` is `None` (first trigger or post-restart), always returns `False` (no comparison possible → allow).

If the check blocks a break, log with per-field deltas, e.g. `"[BTCUSDT] cooldown NOT broken: structure unchanged (vah=0.0atr, price=0.3atr)"`.

### Thresholds

| Field | Threshold | Rationale |
|-------|-----------|-----------|
| vah / val / poc | > 0.5 ATR | Key structural boundary shifted |
| price | > 0.7 ATR | Price drift large enough to change the working context |
| atr_macro | `abs(f_ATR - curr_ATR) / f_ATR > 0.30` | Volatility regime changed — different risk parameters |
| regime | different string | Unlocks different execution rules (e.g. DKE in trending) |

If the snapshot has `atr_macro <= 0` or `volume_profile` is missing fields, the check returns False (not stale) to degrade gracefully.

### Modified Files

Only `src/sniper/trigger.py`:

- Add `StructuralFingerprint` dataclass
- Add `_fingerprint: StructuralFingerprint | None` to `__init__`
- Add `_save_fingerprint(metrics)` method
- Add `_fingerprint_is_stale(metrics) -> bool` method
- Call `_save_fingerprint` in `evaluate()` after trigger confirmation
- Insert fingerprint check before cooldown break in `evaluate()`

~50 lines net addition.

### Boundary Cases

| Scenario | Behavior |
|----------|----------|
| First trigger, no fingerprint | `_fingerprint_is_stale` returns False → not blocked |
| ATR = 0 | Cannot normalize → returns False (not stale) |
| Missing volume_profile fields | Returns False, logged as warning |
| Daemon restart → fingerprint lost | First trigger after restart always allowed |
| Regime changes but structure doesn't | Fingerprint detects regime diff → allows break |
| ATR expands 40% with same VAH/POC | Detected by >30% ATR change → allows break |

## Future Considerations

- **Cooldown-aside path**: Not covered by this design. Cooldown naturally expiring is still the primary gate.
- **Persistent fingerprint**: Explicitly NOT needed. Restart should not block the first trigger.
- **Regime-only change** (e.g. ranging→squeeze with identical VAH/POC/price): This design allows the break because regime differs. This is correct — AI's execution options change.

## Self-Review Checklist

- [x] No "TBD" or incomplete sections
- [x] Architecture matches feature description
- [x] Scope is focused: one mechanism, one file, ~50 lines
- [x] All edge cases addressed
- [x] No ambiguity in thresholds or behavior
