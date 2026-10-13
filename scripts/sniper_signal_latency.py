#!/usr/bin/env python3
"""Is the sniper's signal stack *late*?  Measure lead/lag, not hit-rate.

Hit-rate analysis (``sniper_gate_replay.py``) answers "did we wake on the good
moves".  This answers the complementary question the operator actually asks when
watching the log: *by the time the stack fires, how much of the move is already
gone, and how much is left?*

Every metric is expressed in **ATR** and measured on the 2-minute pulse grid the
daemon itself sees (``price=…,atr=…`` on the ``SIGNAL DIAG`` line), so no
external candle data is needed and there is no look-ahead.

Definitions
-----------
``prior``  — favourable move already realised in the N minutes *before* the
             event, in ATR.  For a BULLISH event that is ``(p_now - min(p)) / atr``.
``mfe``    — maximum favourable excursion in the H minutes *after* the event.
``capture``— ``mfe / (prior + mfe)``: the share of the whole move still ahead of
             us at the moment we decided.  0.5 means "half gone already", and a
             purely coincident detector sits near 0.5 while a leading one is
             well above it.

Cross-run safety: a window never crosses a daemon restart or a
``RESUMED AFTER GAP`` hole, because a "60 minutes later" price that belongs to a
different process launch is not a continuation of anything.

Run:
    python3 scripts/sniper_signal_latency.py
    python3 scripts/sniper_signal_latency.py --out docs/x.md
"""
from __future__ import annotations

import argparse
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.sniper_gate_core import load_replay_cfg  # noqa: E402
from scripts.sniper_gate_replay import DEFAULT_LOG, enrich, parse  # noqa: E402

SEG_GAP_S = 6 * 60          # pulse hole that breaks a window
PULSE_MIN = 2.0             # configured pulse interval
BIG_MOVE_ATR = 3.0          # a move this large within 60 min is "a move"
BIG_MOVE_DEDUPE_MIN = 30.0
DET_ACTIVE_MIN = 0.15       # strength floor for "this detector is contributing"


# ═══════════════════════════════════════════════════════════════════════════
# window helpers (all index-based, all segment-clamped)
# ═══════════════════════════════════════════════════════════════════════════

def segments(pulses: Sequence[Any], mono: Sequence[float]) -> List[Tuple[int, int]]:
    """[start, end) index ranges sampled continuously at the 2-min cadence."""
    if not pulses:
        return []
    out, start = [], 0
    for i in range(1, len(pulses)):
        if pulses[i].run != pulses[i - 1].run or mono[i] - mono[i - 1] > SEG_GAP_S:
            out.append((start, i))
            start = i
    out.append((start, len(pulses)))
    return [s for s in out if s[1] - s[0] >= 2]


def _px(p) -> Optional[float]:
    return p.diag.get("price") or None


def _atr(p) -> Optional[float]:
    return p.diag.get("atr") or None


def back_range(pulses, mono, i: int, lo: int, minutes: float) -> int:
    """First index j in [lo, i] with mono[i] - mono[j] <= minutes."""
    lim = mono[i] - minutes * 60.0
    j = i
    while j - 1 >= lo and mono[j - 1] >= lim:
        j -= 1
    return j


def fwd_range(pulses, mono, i: int, hi: int, minutes: float) -> int:
    """Exclusive end index j in (i, hi] with mono[j] - mono[i] <= minutes."""
    lim = mono[i] + minutes * 60.0
    j = i + 1
    while j < hi and mono[j] <= lim:
        j += 1
    return j


def prior_move(pulses, mono, i, lo, minutes, direction):
    """(ATR already travelled in `direction` before i, minutes since the extreme)."""
    p0, atr = _px(pulses[i]), _atr(pulses[i])
    if p0 is None or not atr:
        return None
    j0 = back_range(pulses, mono, i, lo, minutes)
    best, best_j = None, i
    for k in range(j0, i + 1):
        pk = _px(pulses[k])
        if pk is None:
            continue
        if best is None or (pk < best if direction == "BULLISH" else pk > best):
            best, best_j = pk, k
    if best is None or best_j == i:
        return None
    moved = (p0 - best) / atr if direction == "BULLISH" else (best - p0) / atr
    return moved, (mono[i] - mono[best_j]) / 60.0


def future_exc(pulses, mono, i, hi, minutes, direction):
    """(mfe, mae, minutes_to_mfe) in ATR over the following `minutes`."""
    p0, atr = _px(pulses[i]), _atr(pulses[i])
    if p0 is None or not atr:
        return None
    j1 = fwd_range(pulses, mono, i, hi, minutes)
    sign = 1.0 if direction == "BULLISH" else -1.0
    ex = []
    for k in range(i + 1, j1):
        pk = _px(pulses[k])
        if pk is not None:
            ex.append((sign * (pk - p0) / atr, mono[k] - mono[i]))
    if len(ex) < 5:
        return None
    mfe, t = max(ex, key=lambda z: z[0])
    mae = min(e[0] for e in ex)
    return mfe, mae, t / 60.0


def signed_exc(pulses, mono, i, hi, minutes, direction):
    """Total signed return over the window (drift, not best-case)."""
    p0, atr = _px(pulses[i]), _atr(pulses[i])
    if p0 is None or not atr:
        return None
    j1 = fwd_range(pulses, mono, i, hi, minutes)
    if j1 - i < 5:
        return None
    pk = [_px(pulses[k]) for k in range(i + 1, j1)]
    pk = [x for x in pk if x is not None]
    if len(pk) < 5:
        return None
    sign = 1.0 if direction == "BULLISH" else -1.0
    return sign * (pk[-1] - p0) / atr


def first_touch(pulses, mono, i, hi, minutes, direction, level):
    """Which comes first after the event: +level or -level ATR (in its direction)?"""
    p0, atr = _px(pulses[i]), _atr(pulses[i])
    if p0 is None or not atr:
        return None
    j1 = fwd_range(pulses, mono, i, hi, minutes)
    sign = 1.0 if direction == "BULLISH" else -1.0
    for k in range(i + 1, j1):
        pk = _px(pulses[k])
        if pk is None:
            continue
        e = sign * (pk - p0) / atr
        if e >= level:
            return "fav", (mono[k] - mono[i]) / 60.0
        if e <= -level:
            return "adv", (mono[k] - mono[i]) / 60.0
    return "none", None


def _touch_rate(rows, level):
    c = Counter(r[f"touch{level}"] for r in rows if r.get(f"touch{level}"))
    n = sum(c.values())
    if not n:
        return "—"
    return f"fav {100 * c['fav'] / n:.0f}% / adv {100 * c['adv'] / n:.0f}% / flat {100 * c['none'] / n:.0f}% (n={n})"


def _stat(xs: Sequence[float]) -> Dict[str, Any]:
    if not xs:
        return {"n": 0}
    s = sorted(xs)
    return {"n": len(s), "mean": round(statistics.fmean(s), 2),
            "median": round(statistics.median(s), 2),
            "p25": round(s[int(0.25 * (len(s) - 1))], 2),
            "p75": round(s[int(0.75 * (len(s) - 1))], 2)}


def _tstat(xs: Sequence[float]) -> Optional[Dict[str, float]]:
    """One-sample t-test against zero: is the mean forward drift distinguishable
    from no edge?  Returns mean, standard error and t."""
    n = len(xs)
    if n < 5:
        return None
    mean = statistics.fmean(xs)
    sd = statistics.stdev(xs)
    se = sd / n ** 0.5
    return {"n": n, "mean": round(mean, 2), "se": round(se, 2),
            "t": round(mean / se, 2) if se else None}


def _corr(a: Sequence[float], b: Sequence[float]) -> Optional[float]:
    if len(a) < 10:
        return None
    ma, mb = statistics.fmean(a), statistics.fmean(b)
    num = sum((x - ma) * (y - mb) for x, y in zip(a, b))
    da = sum((x - ma) ** 2 for x in a) ** 0.5
    db = sum((y - mb) ** 2 for y in b) ** 0.5
    return round(num / (da * db), 3) if da and db else None


# ═══════════════════════════════════════════════════════════════════════════
# analyses
# ═══════════════════════════════════════════════════════════════════════════

LOOKBACK_MIN = 120.0        # for the (uncensored) time-to-swing-start metric


def wake_latency(parsed, sym, prior_min=30.0, fut_min=60.0):
    pulses, mono = parsed["pulses"][sym], parsed["mono"][sym]
    segs = segments(pulses, mono)
    lo_of = {}
    hi_of = {}
    for lo, hi in segs:
        for i in range(lo, hi):
            lo_of[i], hi_of[i] = lo, hi
    rows = []
    for ev in parsed["events"]:
        if ev["kind"] != "wake" or ev["sym"] != sym:
            continue
        i = ev["pulse_idx"]
        if i not in lo_of or _px(pulses[i]) is None:
            continue
        pm = prior_move(pulses, mono, i, lo_of[i], prior_min, ev["dir"])
        pm60 = prior_move(pulses, mono, i, lo_of[i], 60.0, ev["dir"])
        # swing-start delay uses a much longer window so the estimate is not
        # censored at the window edge (a 30-min window saturates immediately).
        pm_long = prior_move(pulses, mono, i, lo_of[i], LOOKBACK_MIN, ev["dir"])
        fx = future_exc(pulses, mono, i, hi_of[i], fut_min, ev["dir"])
        if not fx:
            continue
        mfe, mae, t_mfe = fx
        prior, _ = pm if pm else (0.0, 0.0)
        rows.append({"t": ev["t"], "run": ev["run"], "dir": ev["dir"],
                     "conf": ev["conf"], "regime": ev["regime"],
                     "prior": round(prior, 2),
                     "prior60": round(pm60[0], 2) if pm60 else 0.0,
                     "prior_long": round(pm_long[0], 2) if pm_long else 0.0,
                     "delay": round(pm_long[1], 1) if pm_long else 0.0,
                     "mfe": round(mfe, 2), "mae": round(mae, 2),
                     "t_mfe": round(t_mfe, 1),
                     "same_dir": pulses[i].same_dir,
                     "capture": round(mfe / (prior + mfe), 2) if prior + mfe > 0 else None,
                     "fwd": signed_exc(pulses, mono, i, hi_of[i], fut_min, ev["dir"]),
                     "touch0.5": first_touch(pulses, mono, i, hi_of[i], fut_min, ev["dir"], 0.5)[0],
                     "touch1.0": first_touch(pulses, mono, i, hi_of[i], fut_min, ev["dir"], 1.0)[0],
                     "executed": ev.get("executed"), "opinion": ev.get("opinion")})
    return rows, segs


def detector_lag(parsed, sym, prior_min=30.0, fut_min=60.0):
    """For every detector activation, the move behind it and the move ahead."""
    pulses, mono = parsed["pulses"][sym], parsed["mono"][sym]
    out: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for lo, hi in segments(pulses, mono):
        last_active: Dict[str, float] = {}
        for i in range(lo, hi):
            p = pulses[i]
            for s in p.signals:
                d, st = s["sub_type"], s["strength"]
                if st < DET_ACTIVE_MIN or s["direction"] == "NEUTRAL":
                    continue
                # an "activation" is the first pulse after >=30 min of silence
                prev = last_active.get(d)
                if prev is not None and mono[i] - prev < 30 * 60:
                    last_active[d] = mono[i]
                    continue
                last_active[d] = mono[i]
                pm = prior_move(pulses, mono, i, lo, prior_min, s["direction"])
                fx = future_exc(pulses, mono, i, hi, fut_min, s["direction"])
                if not fx:
                    continue
                mfe, mae, _ = fx
                prior, delay = pm if pm else (0.0, 0.0)
                out[d].append({"prior": prior, "delay": delay, "mfe": mfe, "mae": mae,
                               "dir": s["direction"], "strength": st,
                               "touch0.5": first_touch(pulses, mono, i, hi, fut_min, s["direction"], 0.5)[0],
                               "touch1.0": first_touch(pulses, mono, i, hi, fut_min, s["direction"], 1.0)[0],
                               "fwd": signed_exc(pulses, mono, i, hi, fut_min, s["direction"])})
    return out


def lead_lag(parsed, sym, horizon=30.0):
    """Does the score describe the past or predict the future?

    ``corr(conf, past)`` high and ``corr(conf, future)`` no better than the
    price-momentum baseline ``corr(past, future)`` means the stack is a
    rear-view mirror.  ``edge`` is the part of the future correlation that is
    not explained by the past move.
    """
    pulses, mono = parsed["pulses"][sym], parsed["mono"][sym]
    conf, past, fut = [], [], []
    for lo, hi in segments(pulses, mono):
        for i in range(lo, hi):
            if pulses[i].confluence is None or _px(pulses[i]) is None:
                continue
            p0, atr = _px(pulses[i]), _atr(pulses[i])
            if not atr:
                continue
            j0 = back_range(pulses, mono, i, lo, horizon)
            j1 = fwd_range(pulses, mono, i, hi, horizon)
            if i - j0 < 5 or j1 - i < 5:
                continue
            prev = [_px(pulses[k]) for k in range(j0, i) if _px(pulses[k]) is not None]
            nxt = [_px(pulses[k]) for k in range(i + 1, j1) if _px(pulses[k]) is not None]
            if len(prev) < 5 or len(nxt) < 5:
                continue
            conf.append(pulses[i].confluence)
            past.append(abs(p0 - prev[0]) / atr)
            fut.append(max(abs(x - p0) for x in nxt) / atr)
    c_past, c_fut, base = _corr(conf, past), _corr(conf, fut), _corr(past, fut)
    return {"n": len(conf), "corr_conf_past": c_past, "corr_conf_future": c_fut,
            "baseline_past_future": base,
            "edge": round(c_fut - base, 3) if (c_fut is not None and base is not None) else None}


def big_moves(parsed, sym, fut_min=60.0, thr=BIG_MOVE_ATR):
    """Large swings, whether we woke, and how late the first detector was."""
    pulses, mono = parsed["pulses"][sym], parsed["mono"][sym]
    events = []
    for lo, hi in segments(pulses, mono):
        last = None
        for i in range(lo, hi):
            p0, atr = _px(pulses[i]), _atr(pulses[i])
            if p0 is None or not atr:
                continue
            j1 = fwd_range(pulses, mono, i, hi, fut_min)
            if j1 - i < 10:
                continue
            win = [(k, _px(pulses[k])) for k in range(i, j1)]
            win = [(k, x) for k, x in win if x is not None]
            if len(win) < 10:
                continue
            hi_px = max(x for _, x in win)
            lo_px = min(x for _, x in win)
            up, down = (hi_px - p0) / atr, (p0 - lo_px) / atr
            direction = "BULLISH" if up >= down else "BEARISH"
            size = max(up, down)
            if size < thr:
                continue
            if last is not None and mono[i] - last < BIG_MOVE_DEDUPE_MIN * 60:
                continue
            last = mono[i]
            events.append({"i": i, "lo": lo, "hi": hi, "dir": direction,
                           "size": round(size, 2), "mono": mono[i]})
    # attach our reaction
    wakes = [ev for ev in parsed["events"] if ev["kind"] == "wake" and ev["sym"] == sym]
    blocks = [ev for ev in parsed["events"]
              if ev["kind"] in ("gate_fail", "cooldown_block", "shadow") and ev["sym"] == sym]
    for e in events:
        t0 = e["mono"]
        near = [w for w in wakes if w["pulse_idx"] >= e["lo"] and w["pulse_idx"] < e["hi"]
                and -10 * 60 <= mono[w["pulse_idx"]] - t0 <= 60 * 60]
        e["wake"] = bool(near)
        e["wake_dir_match"] = any(w["dir"] == e["dir"] for w in near)
        best_conf, best_k = 0.0, e["i"]
        for k in range(e["i"], e["hi"]):
            if not 0 <= mono[k] - t0 <= fut_min * 60:
                continue
            c = pulses[k].confluence or 0.0
            if c > best_conf:
                best_conf, best_k = c, k
        e["max_conf"] = round(best_conf, 2)
        # would we have made money entering at the most promising pulse?
        fx = future_exc(pulses, mono, best_k, e["hi"], fut_min, e["dir"])
        if fx:
            mfe, mae, _ = fx
            pm = prior_move(pulses, mono, best_k, e["lo"], LOOKBACK_MIN, e["dir"])
            e["entry_prior"] = round(pm[0], 2) if pm else 0.0
            e["entry_delay"] = round(pm[1], 1) if pm else 0.0
            e["entry_mfe"], e["entry_mae"] = round(mfe, 2), round(mae, 2)
            e["entry_touch"] = first_touch(pulses, mono, best_k, e["hi"], fut_min, e["dir"], 0.5)[0]
            e["entry_fwd"] = round(signed_exc(pulses, mono, best_k, e["hi"], fut_min, e["dir"]) or 0.0, 2)
        # what stopped us at the most promising pulse of the move?
        hit = [b for b in blocks if abs(b["pulse_idx"] - best_k) <= 1
               and 0 <= mono[b["pulse_idx"]] - t0 <= fut_min * 60]
        e["blocked"] = sorted({b["kind"] for b in hit})
        e["block_reason"] = next((b.get("reason") for b in hit), None)
        e["same_dir"] = pulses[best_k].same_dir
        # first same-direction detector activation at/after the move start
        lag, first_det = None, None
        for k in range(e["i"], e["hi"]):
            if mono[k] - t0 > fut_min * 60:
                break
            act = [s for s in pulses[k].signals
                   if s["direction"] == e["dir"] and s["strength"] >= DET_ACTIVE_MIN]
            if act:
                lag = (mono[k] - t0) / 60.0
                first_det = act[0]["sub_type"]
                break
        e["det_lag"] = round(lag, 1) if lag is not None else None
        e["first_det"] = first_det
    return events


def scorecard(parsed, sym, cfg, dets):
    """Per-detector: how often it fires, how clock-bound, and how skilled.

    ``boundary x`` is the fire rate in the first 2 minutes of a 15-minute candle
    divided by the rate elsewhere.  A detector near 1.0 samples the market; a
    detector far above 1.0 is partly sampling the candle clock.
    """
    pulses = parsed["pulses"][sym]
    fires = Counter(s["sub_type"] for p in pulses for s in p.signals)
    edge, mid = Counter(), Counter()
    ne = nm = 0
    for p in pulses:
        h, m, sec = (int(x) for x in p.t.split(".")[0].split(":"))
        is_edge = ((h * 3600 + m * 60 + sec) % 900) // 60 <= 1
        ne += is_edge
        nm += not is_edge
        for s in p.signals:
            (edge if is_edge else mid)[s["sub_type"]] += 1
    out = {}
    for d, n in fires.items():
        if n < 5:
            continue
        re_, rm = edge[d] / max(ne, 1), mid[d] / max(nm, 1)
        rows = dets.get(d, [])
        fav = sum(1 for r in rows if r["touch0.5"] == "fav")
        adv = sum(1 for r in rows if r["touch0.5"] == "adv")
        n_dec = fav + adv
        # binomial standard error of fav%, in percentage points
        se = 100 * (0.25 / n_dec) ** 0.5 if n_dec else None
        out[d] = {
            "weight": cfg["weights"].get(d, 0.0),
            "fires": n,
            "share": round(100 * edge[d] / n),
            "boundary_x": round(re_ / rm, 1) if rm else None,
            "decided": n_dec,
            "fav_pct": round(100 * fav / n_dec) if n_dec else None,
            "fav_se": round(se, 1) if se else None,
            "touch": _touch_rate(rows, 0.5),
            "capture": _stat([r["mfe"] / (r["prior"] + r["mfe"])
                              for r in rows if r["prior"] + r["mfe"] > 0]),
            "delay": _stat([r["delay"] for r in rows]),
            "fwd": _stat([r["fwd"] for r in rows if r["fwd"] is not None]),
        }
    return out


def _verdict(d, s):
    """Only the mechanically-established failure is labelled.

    ``fav%`` is deliberately *not* turned into a verdict: at n = 15-50 the
    binomial standard error is 6-13 points, so nothing here can separate 45%
    from 50%.  The reader gets the number and its error bar instead.
    """
    if s["boundary_x"] and s["boundary_x"] >= 5:
        return "clock artifact"
    return ""


# ═══════════════════════════════════════════════════════════════════════════
# report
# ═══════════════════════════════════════════════════════════════════════════

def analyse(log: Path) -> Dict[str, Any]:
    parsed = parse(log)
    cfg = load_replay_cfg()
    enrich(parsed, cfg)
    rep: Dict[str, Any] = {"log": str(log), "symbols": {}}
    for sym in parsed["pulses"]:
        wakes, segs = wake_latency(parsed, sym)
        dets = detector_lag(parsed, sym)
        rep["symbols"][sym] = {
            "pulses": len(parsed["pulses"][sym]),
            "segments": len(segs),
            "wakes": wakes,
            "wake_stats": {
                "prior": _stat([w["prior"] for w in wakes]),
                "prior60": _stat([w["prior60"] for w in wakes]),
                "mfe": _stat([w["mfe"] for w in wakes]),
                "mae": _stat([w["mae"] for w in wakes]),
                "capture": _stat([w["capture"] for w in wakes if w["capture"] is not None]),
                "delay": _stat([w["delay"] for w in wakes]),
                "same_dir": _stat([w["same_dir"] for w in wakes]),
                "fwd": _stat([w["fwd"] for w in wakes if w["fwd"] is not None]),
                "fwd_t": _tstat([w["fwd"] for w in wakes if w["fwd"] is not None]),
            },
            "lead_lag": lead_lag(parsed, sym),
            "detectors": {d: {"act": len(v),
                              "prior": _stat([x["prior"] for x in v]),
                              "mfe": _stat([x["mfe"] for x in v]),
                              "mae": _stat([x["mae"] for x in v]),
                              "delay": _stat([x["delay"] for x in v]),
                              "capture": _stat([x["mfe"] / (x["prior"] + x["mfe"])
                                                for x in v if x["prior"] + x["mfe"] > 0]),
                              "touch": _touch_rate(v, 0.5),
                              "touch1": _touch_rate(v, 1.0),
                              "fwd": _stat([x["fwd"] for x in v if x["fwd"] is not None])}
                          for d, v in dets.items()},
            "big_moves": big_moves(parsed, sym),
            "scorecard": scorecard(parsed, sym, cfg, dets),
        }
    return rep


def _fmt(st: Dict[str, Any], key: str = "median") -> str:
    return "—" if not st or not st.get("n") else f"{st[key]:+.2f}"


def write_md(rep: Dict[str, Any], path: Path) -> None:
    L: List[str] = []
    A = L.append
    A("# Sniper signal latency — is the stack late?\n")
    A("Generated by `scripts/sniper_signal_latency.py`.\n")
    A("All figures are ATR-normalised and measured on the daemon's own 2-minute "
      "pulse grid. `prior` = move already realised before the event, `mfe` = best "
      "move after it, `capture` = mfe/(prior+mfe).\n")
    for sym, s in rep["symbols"].items():
        A(f"\n## {sym}\n")
        A(f"{s['pulses']} pulses in {s['segments']} continuous segments, "
          f"{len(s['wakes'])} wakes.\n")
        ws = s["wake_stats"]
        A("| wakes | prior(30m) | mfe(60m) | mae(60m) | capture | min to swing start | same-dir active |")
        A("|---|---|---|---|---|---|---|")
        A(f"| {ws['capture'].get('n', 0)} | {_fmt(ws['prior'])} | {_fmt(ws['mfe'])} | "
          f"{_fmt(ws['mae'])} | {_fmt(ws['capture'])} | {_fmt(ws['delay'])} | "
          f"{_fmt(ws['same_dir'])} |\n")
        ft = ws.get("fwd_t") or {}
        A(f"Forward drift over the 60m after a wake: **{ft.get('mean')} ATR** "
          f"(se {ft.get('se')}, t = {ft.get('t')}, n = {ft.get('n')}). "
          f"|t| < 2 means the sample cannot distinguish this from no edge.\n")
        A(f"First touch after a wake (60m): ±0.5 ATR — "
          f"{_touch_rate(s['wakes'], 0.5)}; ±1.0 ATR — {_touch_rate(s['wakes'], 1.0)}.\n")
        ll = s["lead_lag"]
        A(f"Lead/lag ({ll['n']} pulses): corr(conf, past 30m move) = "
          f"**{ll['corr_conf_past']}**, corr(conf, future 30m move) = "
          f"**{ll['corr_conf_future']}**, price-momentum baseline "
          f"corr(past, future) = **{ll['baseline_past_future']}**, edge = "
          f"**{ll['edge']}**.\n")
        A("| detector | act | prior(30m) | mfe(60m) | mae(60m) | capture | fwd drift | min to start | first touch ±0.5 |")
        A("|---|---|---|---|---|---|---|---|---|")
        for d, st in sorted(s["detectors"].items(),
                            key=lambda kv: -kv[1]["capture"].get("median", 0)):
            A(f"| {d} | {st['act']} | {_fmt(st['prior'])} | {_fmt(st['mfe'])} | "
              f"{_fmt(st['mae'])} | {_fmt(st['capture'])} | {_fmt(st['fwd'])} | "
              f"{_fmt(st['delay'])} | {st['touch']} |")
        A("")
        A("### Detector scorecard\n")
        A("`boundary x` = fire rate in the first 2 min of a 15-min candle ÷ rate elsewhere. "
          "`decided` = activations that reached ±0.5 ATR within 60 min; `fav%` = share of "
          "those that went the detector's way (50% = coin flip).\n")
        A("| detector | weight | fires | fires at candle start | boundary x | decided | fav% | capture | fwd drift | verdict |")
        A("|---|---|---|---|---|---|---|---|---|---|")
        for d, sc in sorted(s["scorecard"].items(), key=lambda kv: -kv[1]["weight"]):
            A(f"| {d} | {sc['weight']} | {sc['fires']} | {sc['share']}% | "
              f"{sc['boundary_x']}x | {sc['decided']} | "
              f"{(str(sc['fav_pct']) + '±' + str(sc['fav_se'])) if sc['fav_pct'] is not None else '—'}% | "
              f"{_fmt(sc['capture'])} | {_fmt(sc['fwd'])} | {_verdict(d, sc)} |")
        A("")
        bm = s["big_moves"]
        A(f"\nBig moves (>= {BIG_MOVE_ATR} ATR within 60m): **{len(bm)}**, of which a wake "
          f"happened nearby: **{sum(1 for b in bm if b['wake'])}**, same-direction wake: "
          f"**{sum(1 for b in bm if b['wake_dir_match'])}**.\n")
        if bm:
            A("| move dir | size | wake | max conf | same-dir active | first detector | why blocked |")
            A("|---|---|---|---|---|---|---|")
            for b in bm:
                A(f"| {b['dir']} | {b['size']} | {'yes' if b['wake'] else '**no**'} | "
                  f"{b['max_conf']} | {b['same_dir']} | "
                  f"{b['first_det'] or '—'} @{b['det_lag'] if b['det_lag'] is not None else '—'}m | "
                  f"{'/'.join(b['blocked']) or '—'} |")
    path.write_text("\n".join(L) + "\n")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--log", type=Path, default=DEFAULT_LOG)
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()

    rep = analyse(args.log)
    for sym, s in rep["symbols"].items():
        ws = s["wake_stats"]
        ll = s["lead_lag"]
        print(f"\n═══ {sym} — {s['pulses']} pulses / {len(s['wakes'])} wakes / {s['segments']} segments")
        print(f"  wakes      prior30={_fmt(ws['prior'])} prior60={_fmt(ws['prior60'])} "
              f"mfe60={_fmt(ws['mfe'])} mae60={_fmt(ws['mae'])} capture={_fmt(ws['capture'])} "
              f"delay_to_swing_start={_fmt(ws['delay'])}m same_dir_active={_fmt(ws['same_dir'])}")
        ft = ws.get("fwd_t") or {}
        print(f"  edge       forward drift 60m: mean={ft.get('mean')} ATR "
              f"se={ft.get('se')} t={ft.get('t')} (n={ft.get('n')})  "
              f"[t>2 = real edge, |t|<1 = indistinguishable from no edge]")
        print(f"  lead/lag   conf~past={ll['corr_conf_past']} conf~future={ll['corr_conf_future']} "
              f"baseline(past~future)={ll['baseline_past_future']} edge={ll['edge']} n={ll['n']}")
        print(f"  first touch after wake (60m): ±0.5 ATR -> {_touch_rate(s['wakes'], 0.5)}")
        print(f"                                ±1.0 ATR -> {_touch_rate(s['wakes'], 1.0)}")
        print("  detectors  (sorted by capture: 0.5 = coincident, >0.5 = leading)")
        for d, st in sorted(s["detectors"].items(), key=lambda kv: -kv[1]["capture"].get("median", 0)):
            print(f"    {d:22s} act={st['act']:4d} prior30={_fmt(st['prior']):>7s} "
                  f"mfe60={_fmt(st['mfe']):>7s} capture={_fmt(st['capture']):>6s} "
                  f"delay={_fmt(st['delay']):>6s}m fwd={_fmt(st['fwd']):>7s} "
                  f"touch0.5[{st['touch']}]")
        print("  scorecard  (weight | fires | fires at candle start | boundary x | decided | fav% | verdict)")
        for d, sc in sorted(s["scorecard"].items(), key=lambda kv: -kv[1]["weight"]):
            print(f"    {d:22s} w={sc['weight']:.2f} fires={sc['fires']:5d} "
                  f"@candle_start={sc['share']:3d}% boundary={str(sc['boundary_x']):>5s}x "
                  f"decided={sc['decided']:4d} fav={str(sc['fav_pct']):>4s}±{str(sc['fav_se']):<4s}%  {_verdict(d, sc)}")
        bm = s["big_moves"]
        hit = sum(1 for b in bm if b["wake"])
        same = sum(1 for b in bm if b["wake_dir_match"])
        lags = [b["det_lag"] for b in bm if b["det_lag"] is not None]
        never = sum(1 for b in bm if b["det_lag"] is None)
        print(f"  big moves  n={len(bm)} wake={hit} same_dir_wake={same} "
              f"detector_lag_median={_fmt(_stat(lags))}m never_detected={never}")
        for b in bm:
            print(f"    {b['dir']:8s} {b['size']:5.2f} ATR  wake={'Y' if b['wake'] else 'n'}"
                  f"{'*' if b['wake_dir_match'] else ' '} maxconf={b['max_conf']:.2f} "
                  f"same_dir={b['same_dir']} det={b['first_det'] or '—'}@{b['det_lag'] if b['det_lag'] is not None else '—'}"
                  f" blocked={'/'.join(b['blocked']) or '—'}"
                  f" | entry@maxconf: prior={b.get('entry_prior','—')} "
                  f"mfe60={b.get('entry_mfe','—')} mae60={b.get('entry_mae','—')} "
                  f"touch={b.get('entry_touch','—')} fwd={b.get('entry_fwd','—')}")
    if args.out:
        write_md(rep, args.out)
        print(f"\nwrote {args.out}")


if __name__ == "__main__":
    main()
