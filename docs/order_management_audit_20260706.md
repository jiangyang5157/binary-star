# Order Management Audit Report — 2026-07-06 04:00 UTC
## Executive Summary

- **Dimensions audited:** 8 (D1–D8)
- **Total findings:** 36 (CRITICAL: 1, HIGH: 6, MEDIUM: 14, LOW: 15)
- **OTOCO migration safety:** No new vulnerabilities introduced. Two pre-existing issues (D1-1, D1-2) affect both old and new paths.
- **Key risks:** Naked position windows at cancel-place gaps, restart recovery gaps for unprotected positions, emergency close failure cascades.

---

## CRITICAL

### D4-1: Exit Ladder — Double Failure Leaves Naked Position

- **File:** `src/agent/order_executor.py:746`
- **Severity:** CRITICAL
- **Risk Score:** 95
- **Description:** `_try_exit_ladder` cancels ALL OCO orders BEFORE attempting partial market close. If both partial close and full emergency close fail, function returns `(True, None)` — caller believes position is intact but it's naked (no SL, no TP).
- **Impact:** Position unprotected for up to full pulse interval (2 min). In volatile markets, total loss or liquidation.
- **Recommendation:** Place protective OCO BEFORE cancelling old one, or return `(False, None)` to trigger caller's emergency cascade.

---

## HIGH

### D1-1: Unhandled Exception in `place_oco_order` Bypasses Emergency Close

- **File:** `src/infrastructure/binance/margin_client.py:441`
- **Severity:** HIGH
- **Risk Score:** 82
- **Description:** `place_oco_order` catches only `ClientError` and `ServerError`. Network exceptions (`ConnectionError`, `Timeout`) propagate unhandled past all 5 call sites' emergency close logic. Cancel succeeded → position naked → OCO fails with unhandled exception → emergency close never reached.
- **Recommendation:** Add bare `except Exception` returning `False`, matching `place_otoco_order`'s pattern.

### D1-2: Case 4 OCO Re-alignment Fails Silently With No Recovery

- **File:** `src/agent/order_executor.py:370`
- **Severity:** HIGH
- **Risk Score:** 80
- **Description:** When one OCO leg fills and the other is auto-cancelled, Case 4 detects qty mismatch but can't extract valid TP/SL. Logs critical warning but does NOT emergency close. Every subsequent pulse loops identically — infinite loop until manual intervention. Case 3 never fires because `has_oco=True` from the surviving leg.
- **Recommendation:** Emergency close or force Case 3 by clearing has_oco when both prices unavailable.

### D2-1: Cancel-Then-Place OCO + Emergency Close Double Failure → Naked

- **File:** `src/agent/order_executor.py:513`
- **Severity:** HIGH
- **Risk Score:** 82
- **Description:** `_optimize_same_direction`: cancel succeeds, OCO fails, emergency close also fails → returns `(True, None)` indistinguishable from "no action needed". Position is naked with all protection removed.
- **Recommendation:** Return distinct sentinel (-2) to force immediate Guardian repair priority.

### D3-2: Unprotected Position After Restart Silently Ignored

- **File:** `src/agent/order_executor.py:193`
- **Severity:** HIGH
- **Risk Score:** 80
- **Description:** Has position + no SL + no trade_state → returns without logging WARNING or CRITICAL. Position is naked and bot silently ignores it every pulse. No operator alert. Only resolved when new AI session fires.
- **Recommendation:** Add `logger.warning` in the `has_position=True, has_sl=False` branch. Consider emergency close or at minimum a dashboard-visible alert.

### D6-4: Manual Reverse — Bot De-Protects Then Abandons Position

- **File:** `src/agent/order_executor.py:243`
- **Severity:** HIGH
- **Risk Score:** 80
- **Description:** Direction mismatch triggers `cancel_all_symbol_orders` → removes ANY SL user placed → clears trade_state → position naked. "Bot steps aside" by design, but actively removing user protection escalates risk.
- **Recommendation:** Don't cancel orders on direction mismatch. Leave existing protection intact. Add CRITICAL-level alert.

### D7-3: Restart With Unprotected Position — Naked Indefinitely

- **File:** `src/agent/order_executor.py:194`
- **Severity:** HIGH
- **Risk Score:** 80
- **Description:** Restart with position but no OCO → every pulse hits same path: no trade_state, has_position=True, has_sl=False, return early. NEVER auto-protected until new AI session. Permanent gap.
- **Recommendation:** Attempt to estimate TP/SL from config or mark price and place OCO. If impossible, emergency close or CRITICAL alert.

---

## MEDIUM (14 findings)

| ID | Title | Risk |
|----|-------|------|
| D1-3 | `_try_exit_ladder` emergency close uses stale qty after partial TP | 60 |
| D1-6 | `_optimize_same_direction` cancel failure returns stale TP/SL to caller | 50 |
| D3-1 | Pending OTOCO entry orphaned on process restart | 45 |
| D3-3 | Case 2 direction conflict strips OCO leaving naked position | 48 |
| D3-5 | Case 4 OCO qty mismatch with missing TP/SL falls back to log-only | 50 |
| D4-2 | tp_qty floor rounding + min_order_qty distorts proportional exit | 40 |
| D4-3 | `find_level_and_sync_sl` has OCO-modifying side effects on startup | 35 |
| D4-4 | `_apply_sl_lock` naked window on every trailing SL update | 30 |
| D5-1 | Same-direction dict merge missing direction on restart gap | 35 |
| D5-4 | Cooldown reset after SL hit enables same-pulse re-entry | 30 |
| D6-3 | Manual full close leaves dust amount unprotected | 20 |
| D7-4 | Restart during OTOCO pending — timeout monitoring lost | 25 |
| D8-3 | `cancel_all_symbol_orders` unchecked in critical guardian path | 30 |
| D8-5 | `execute_market_close` failure — position naked until next pulse retry | 25 |

---

## LOW (15 findings — summary)

D1-4 (re-verify gap), D1-5 (emergency close signal lost), D2-2 through D2-9 (pivot/safety verified correct, minor type issues), D3-4 (entry_filled_at timestamp), D4-5 through D4-9 (level memory, SL lock verified correct), D5-2 (qty threshold), D5-3 (stale sl_price), D5-5 (TRADED cooldown on no-trade), D5-6 (OTOCO list ID not stored), D6-1/D6-2 (manual qty change verified), D7-1/D7-2 (clean restart verified), D8-1/D8-2/D8-4 (API resilience verified).

---

## Risk Matrix

| Risk Pattern | Top Finding | Likelihood | Impact | Detectability | Score |
|-------------|------------|-----------|--------|--------------|-------|
| Cancel-place naked gap | D4-1 | 3 | 5 | 5 | 75 |
| Unhandled exception bypasses safety | D1-1 | 2 | 5 | 5 | 50 |
| Silent state corruption w/ no recovery | D1-2 | 3 | 5 | 4 | 60 |
| Restart protection gap | D7-3 | 3 | 5 | 5 | 75 |
| Manual intervention destroys protection | D6-4 | 2 | 5 | 5 | 50 |

## Quick Wins (highest ROI fixes)

1. **D1-1:** Add `except Exception` to `place_oco_order` — 2 lines, saves all 5 call sites
2. **D3-2:** Add `logger.warning` in restart-unprotected branch — 1 line, surfaces hidden risk
3. **D1-2:** Emergency close in Case 4 else branch — 3 lines, breaks infinite loop
4. **D5-4:** Skip cooldown reset on normal close — 2 lines, prevents whipsaw
