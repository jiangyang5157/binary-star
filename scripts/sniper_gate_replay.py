#!/usr/bin/env python3
"""Replay ``data/prod/sniper.log`` and score the pre-AI gate.

Reusable across analysis rounds (no round-specific logic).  Run:

    python3 scripts/sniper_gate_replay.py                  # summary to stdout
    python3 scripts/sniper_gate_replay.py --out report.md  # + markdown report
    python3 scripts/sniper_gate_replay.py --json out.json

Key design decision — **file-order anchoring**
---------------------------------------------
Every WAKE / ``PRE-AI GATE FAIL`` / ``GATE SHADOW`` / ``COOLDOWN BLOCK`` /
``cooldown reset`` line is attached to the *immediately preceding* ``SIGNAL DIAG``
pulse for the same symbol, and all forward windows and cooldown arithmetic walk
the pulse list in file order.

This matters because a single daemon run can span several days: run 7 of the
2026-09-22 log covers 3.0 days, so "01:30" occurs three times inside one run.
Matching by time-of-day silently produces plausible-but-wrong numbers, and
sorting by time-of-day scrambles the whole cooldown timeline (``%H:%M:%S`` wraps
at midnight).  Wall-clock durations are therefore taken from a monotonic clock
built by unwrapping the midnight boundary.
"""
from __future__ import annotations

import argparse
import glob
import json
import re
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.sniper_gate_core import (  # noqa: E402
    COOLDOWN_BASE,
    NEUTRAL_MULT,
    Pulse,
    Replay,
    _cooldown_minutes,
    _stats,
    _tsec,
    build_fresh_signals,
    detector_table,
    load_replay_cfg,
    parse_diag,
    trigger_type_of,
)

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LOG = ROOT / "data/prod/sniper.log"

LINE_RE = re.compile(r"^(?P<t>\d{2}:\d{2}:\d{2}\.\d{3})\s+\w+\s+\[(?P<tag>[^\]]+?)\s*\]\s+(?P<msg>.*)$")
DIAG_RE = re.compile(r"^\[(?P<sym>[A-Z0-9]+)\]\s+SIGNAL DIAG \| (?P<body>.*)$")
WAKE_RE = re.compile(r"^\[(?P<sym>[A-Z0-9]+)\]\s+WAKE \| dir=(?P<dir>\w+) \| confluence=(?P<conf>[\d.]+) \| "
                     r"fresh=(?P<fresh>\d+) \| memory=(?P<mem>\d+) \| active=\[(?P<active>[^\]]*)\] \| "
                     r"gate=(?P<gate>\w+) \| regime=(?P<regime>\w+)$")
EVAL_RE = re.compile(r"^\[(?P<sym>[A-Z0-9]+)\] evaluating session \| opinion=(?P<op>\w+) \| confidence=(?P<c>[\d.]+)%")
EXEC_RE = re.compile(r"^\[(?P<sym>[A-Z0-9]+)\] ALL GATES PASSED \| executing (?P<side>\w+)")
ACTIVE_RE = re.compile(r"^\[(?P<sym>[A-Z0-9]+)\] active trade \((?P<side>\w+)\)")
LOWCONF_RE = re.compile(r"^\[(?P<sym>[A-Z0-9]+)\] confidence [\d.]+% < threshold")
RESET_RE = re.compile(r"^\[(?P<sym>[A-Z0-9]+)\] cooldown reset")
GATE_FAIL_RE = re.compile(r"^\[(?P<sym>[A-Z0-9]+)\] PRE-AI GATE FAIL \| (?P<reason>.*?) \| conf=(?P<conf>[\d.]+) "
                          r"\| dir=(?P<dir>\w+) \| regime=(?P<regime>\w+) \| fresh=(?P<fresh>\d+)$")
SHADOW_RE = re.compile(r"^\[(?P<sym>[A-Z0-9]+)\] GATE SHADOW \| (?P<what>.*?) \| regime=(?P<regime>\w+) "
                       r"\| dir=(?P<dir>\w+) \| active=(?P<active>\[.*\])$")
CDBLOCK_RE = re.compile(r"^\[(?P<sym>[A-Z0-9]+)\] COOLDOWN BLOCK \| (?P<reason>.*?) \| conf=(?P<conf>[\d.]+) "
                        r">= thr=(?P<thr>[\d.]+) \| dir=(?P<dir>\w+) \| regime=(?P<regime>\w+)$")


# ═══════════════════════════════════════════════════════════════════════════
# 1. Parse with file-order anchoring
# ═══════════════════════════════════════════════════════════════════════════

def parse(log: Path) -> Dict[str, Any]:
    pulses: Dict[str, List[Pulse]] = defaultdict(list)
    events: List[Dict[str, Any]] = []
    prev_diag: Dict[str, Dict[str, Any]] = {}
    prev_pulse: Dict[str, Optional[Pulse]] = {}
    last_wake: Dict[str, Dict[str, Any]] = {}
    runs: List[Dict[str, Any]] = []
    run_idx = -1

    for line in log.read_text().splitlines():
        m = LINE_RE.match(line)
        if not m:
            continue
        t, msg = m.group("t"), m.group("msg")
        if "SNIPER MONITORING STARTED" in msg:
            run_idx += 1
            runs.append({"idx": run_idx, "start": t, "end": t})
            prev_diag.clear(); prev_pulse.clear(); last_wake.clear()
        elif runs:
            runs[-1]["end"] = t

        dm = DIAG_RE.match(msg)
        if dm:
            sym = dm.group("sym")
            d = parse_diag(dm.group("body"))
            p = Pulse(sym=sym, t=t, run=run_idx, diag=d)
            p.signals = build_fresh_signals(p, prev_diag.get(sym), prev_pulse.get(sym))
            pulses[sym].append(p)
            prev_diag[sym] = d
            prev_pulse[sym] = p
            continue

        def anchor(sym: str) -> int:
            return len(pulses[sym]) - 1

        wm = WAKE_RE.match(msg)
        if wm:
            sym = wm.group("sym")
            rec = {"kind": "wake", "t": t, "run": run_idx, "sym": sym, "pulse_idx": anchor(sym),
                   "dir": wm.group("dir"), "conf": float(wm.group("conf")),
                   "fresh": int(wm.group("fresh")), "mem": int(wm.group("mem")),
                   "active": [s for s in wm.group("active").replace("'", "").split(", ") if s],
                   "regime": wm.group("regime")}
            events.append(rec); last_wake[sym] = rec
            continue
        em = EVAL_RE.match(msg)
        if em:
            r = last_wake.get(em.group("sym"))
            if r: r.update(opinion=em.group("op"), confidence=float(em.group("c")))
            continue
        xm = EXEC_RE.match(msg)
        if xm:
            r = last_wake.get(xm.group("sym"))
            if r: r["executed"] = xm.group("side")
            continue
        am = ACTIVE_RE.match(msg)
        if am:
            r = last_wake.get(am.group("sym"))
            if r: r["skip_active"] = am.group("side")
            continue
        lc = LOWCONF_RE.match(msg)
        if lc:
            r = last_wake.get(lc.group("sym"))
            if r: r["low_conf"] = True
            continue
        rm = RESET_RE.match(msg)
        if rm:
            sym = rm.group("sym")
            events.append({"kind": "reset", "t": t, "run": run_idx, "sym": sym, "pulse_idx": anchor(sym)})
            continue
        gm = GATE_FAIL_RE.match(msg)
        if gm:
            sym = gm.group("sym")
            events.append({"kind": "gate_fail", "t": t, "run": run_idx, "sym": sym, "pulse_idx": anchor(sym),
                           "reason": gm.group("reason"), "conf": float(gm.group("conf")),
                           "dir": gm.group("dir"), "regime": gm.group("regime"),
                           "fresh": int(gm.group("fresh"))})
            continue
        sm = SHADOW_RE.match(msg)
        if sm:
            sym = sm.group("sym")
            events.append({"kind": "shadow", "t": t, "run": run_idx, "sym": sym, "pulse_idx": anchor(sym),
                           "dir": sm.group("dir"), "regime": sm.group("regime"),
                           "active": [s for s in sm.group("active").replace("'", "").strip("[]").split(", ") if s]})
            continue
        cm = CDBLOCK_RE.match(msg)
        if cm:
            sym = cm.group("sym")
            events.append({"kind": "cooldown_block", "t": t, "run": run_idx, "sym": sym, "pulse_idx": anchor(sym),
                           "reason": cm.group("reason"), "conf": float(cm.group("conf")),
                           "thr": float(cm.group("thr")), "dir": cm.group("dir"),
                           "regime": cm.group("regime")})
            continue

    return {"pulses": dict(pulses), "events": events, "runs": runs}


# ═══════════════════════════════════════════════════════════════════════════
# 2. Monotonic clock + enrichment
# ═══════════════════════════════════════════════════════════════════════════

def monotonic(pulses: List[Pulse]) -> List[float]:
    """Seconds since each run started, unwrapping the midnight boundary."""
    out: List[float] = []
    prev_run = None
    prev_t = 0.0
    for p in pulses:
        t = _tsec(p.t)
        if p.run != prev_run:
            out.append(0.0)
        else:
            out.append(out[-1] + ((t - prev_t) % 86400.0))
        prev_run, prev_t = p.run, t
    return out


def enrich(parsed: Dict[str, Any], cfg: Dict[str, Any]) -> None:
    for sym, plist in parsed["pulses"].items():
        rp = Replay(cfg, sym)
        seen = None
        for p in plist:
            if seen != p.run:
                rp = Replay(cfg, sym); seen = p.run
            all_sig = rp.ingest(p.signals, _tsec(p.t))
            conf, dom = rp.evaluate(all_sig)
            p.confluence, p.direction = conf, dom
            p.same_dir = len([s for s in all_sig
                              if s["direction"] == dom and s["strength"] >= 0.15])
            p.max_strength = max((s["strength"] for s in all_sig
                                  if s["direction"] != "NEUTRAL"), default=0.0)
            p.regime = rp.regime_of(p.diag)
        parsed.setdefault("mono", {})[sym] = monotonic(plist)


def fwd(pulses: List[Pulse], idx: int, direction: str, horizon: int) -> Optional[Dict[str, float]]:
    p = pulses[idx]
    atr = p.diag.get("atr")
    if not p.diag.get("price") or not atr:
        return None
    sign = 1.0 if direction == "BULLISH" else -1.0
    w = []
    for j in range(idx + 1, min(idx + 1 + horizon, len(pulses))):
        q = pulses[j]
        if q.run != p.run or not q.diag.get("price"):
            break
        w.append(sign * (q.diag["price"] - p.diag["price"]) / atr)
    if len(w) < max(10, horizon // 3):
        return None
    return {"mfe": max(w), "mae": min(w), "term": w[-1]}


# ═══════════════════════════════════════════════════════════════════════════
# 3. Cooldown replay + gate counterfactual (ordinal, monotonic)
# ═══════════════════════════════════════════════════════════════════════════

def counterfactual(parsed: Dict[str, Any], k_values: Tuple[int, ...] = (1, 2, 3)) -> Dict[str, Any]:
    """Replay cooldown from ground-truth wakes, then evaluate the count gate at k.

    Regime caveat: the log exposes only squeeze/chaos deterministically, so every
    remaining pulse is assumed *ranging* (threshold 1.0x, gate min_active_non_trend).
    That treats genuinely-trending pulses as non-trend, which makes the "extra
    wakes" figures an **upper bound**.  Real gate decisions are validated
    separately against the ``PRE-AI GATE FAIL`` lines.
    """
    out: Dict[str, Any] = {}
    for sym, plist in parsed["pulses"].items():
        mono = parsed["mono"][sym]
        ev: Dict[Tuple[int, str], List[Dict[str, Any]]] = defaultdict(list)
        for e in parsed["events"]:
            if e["sym"] == sym:
                ev[(e["run"], e["kind"])].append(e)
        by_idx: Dict[int, List[Dict[str, Any]]] = defaultdict(list)
        for e in parsed["events"]:
            if e["sym"] == sym and e["pulse_idx"] >= 0:
                by_idx[e["pulse_idx"]].append(e)
        wakes = [e for e in parsed["events"] if e["kind"] == "wake" and e["sym"] == sym]
        cfg = parsed["_cfg"]
        base = cfg["base_threshold"][sym]
        mods = {"squeeze": cfg["regime_modifiers"]["squeeze"],
                "chaos": cfg["regime_modifiers"]["chaos"],
                "non_squeeze": cfg["regime_modifiers"]["ranging"]}

        sims: Dict[int, Dict[str, Any]] = {}
        for k in k_values:
            last_i: Optional[int] = None
            last_type: Optional[str] = None
            fired: List[Dict[str, Any]] = []
            states: List[Dict[str, Any]] = []
            for i, p in enumerate(plist):
                for e in by_idx.get(i, []):
                    if e["kind"] == "reset":
                        last_i, last_type = None, None
                if last_i is not None and plist[last_i].run != p.run:
                    last_i, last_type = None, None

                cd_base = (_cooldown_minutes(p.regime, last_type)
                           if last_i is not None else 0.0)
                cd_active = (last_i is not None
                             and (mono[i] - mono[last_i]) / 60.0 < cd_base)
                emergency = getattr(p, "_emergency", False)
                should = p.confluence >= base * mods.get(p.regime, 1.0)
                engine_fire = should and (not cd_active or emergency)
                passed = engine_fire and p.same_dir >= k
                states.append({"i": i, "t": p.t, "run": p.run, "dir": p.direction,
                               "conf": p.confluence, "same_dir": p.same_dir, "regime": p.regime,
                               "should": should, "cd_active": cd_active,
                               "engine_fire": engine_fire, "passed": passed,
                               "gate_blocked": engine_fire and p.same_dir < k})
                if passed:
                    fired.append(states[-1])
                    last_i, last_type = i, "NEUTRAL"
                for e in by_idx.get(i, []):
                    if e["kind"] == "wake":
                        last_i, last_type = i, trigger_type_of(e)
            sims[k] = {"fired": fired, "states": states}

        spans = [max(mono[i] for i in range(len(plist)) if plist[i].run == r["idx"]) / 86400.0
                 for r in parsed["runs"] if any(p.run == r["idx"] for p in plist)]
        days = sum(spans)

        summaries = {}
        for k in k_values:
            st = sims[k]["states"]
            blocked = [s for s in st if s["gate_blocked"]]
            summaries[f"k{k}"] = {
                "n_wakes": len(sims[k]["fired"]),
                "n_wakes_per_day": round(len(sims[k]["fired"]) / days, 2) if days else None,
                "n_gate_blocked": len(blocked),
                "blocked_same_dir1": sum(1 for s in blocked if s["same_dir"] == 1),
                "blocked_same_dir2": sum(1 for s in blocked if s["same_dir"] == 2),
                "blocked_squeeze": sum(1 for s in blocked if s["regime"] == "squeeze"),
                "blocked_dir": dict(Counter(s["dir"] for s in blocked)),
            }
        out[sym] = {"days": round(days, 2), "summaries": summaries,
                    "states_k3": sims[3]["states"], "wakes_logged": len(wakes),
                    "reliable": sym == "XAUTUSDT",
                    "caveat": ("trending cannot be identified from the log, so non_squeeze "
                               "pulses are treated as ranging (min_active_non_trend). "
                               "For symbols whose activity is mostly trending (BTC) this "
                               "under-counts wakes badly — use the logged wake count instead.")}
    return out


# ═══════════════════════════════════════════════════════════════════════════
# 4. Validation against the real gate decisions in the log
# ═══════════════════════════════════════════════════════════════════════════

def validate(parsed: Dict[str, Any]) -> Dict[str, Any]:
    pulses, ev = parsed["pulses"], parsed["events"]
    res: Dict[str, Any] = {}
    gf = [e for e in ev if e["kind"] == "gate_fail"]
    if gf:
        dc, dg = [], []
        for e in gf:
            p = pulses[e["sym"]][e["pulse_idx"]]
            dc.append(abs(p.confluence - e["conf"]))
            got = re.search(r"got (\d+)", e["reason"])
            if got:
                dg.append(p.same_dir - int(got.group(1)))
        res["gate_fail"] = {
            "n": len(gf),
            "conf_within_0.011": sum(1 for x in dc if x <= 0.011),
            "conf_median_delta": round(statistics.median(dc), 4),
            "same_dir_exact": sum(1 for x in dg if x == 0), "same_dir_n": len(dg),
        }
    wakes = [e for e in ev if e["kind"] == "wake"]
    if wakes:
        dc = [abs(pulses[e["sym"]][e["pulse_idx"]].confluence - e["conf"]) for e in wakes]
        res["wake"] = {"n": len(wakes), "conf_within_0.011": sum(1 for x in dc if x <= 0.011),
                       "conf_median_delta": round(statistics.median(dc), 4)}
    cd = [e for e in ev if e["kind"] == "cooldown_block"]
    if cd:
        dc = [abs(pulses[e["sym"]][e["pulse_idx"]].confluence - e["conf"]) for e in cd]
        res["cooldown_block"] = {"n": len(cd), "conf_within_0.011": sum(1 for x in dc if x <= 0.011)}
    return res


# ═══════════════════════════════════════════════════════════════════════════
# 5. Forward-excursion tables for logged decision points
# ═══════════════════════════════════════════════════════════════════════════

def group_excursions(parsed: Dict[str, Any], events: List[Dict[str, Any]], horizon: int = 30) -> Dict[str, Any]:
    buckets: Dict[str, List[Dict[str, float]]] = defaultdict(list)
    for e in events:
        if "dir" not in e or e["dir"] == "NEUTRAL":
            continue
        plist = parsed["pulses"][e["sym"]]
        f = fwd(plist, e["pulse_idx"], e["dir"], horizon)
        if not f:
            continue
        key = e["kind"]
        if e["kind"] in ("wake", "shadow"):
            key += f"_{e['sym']}_{e.get('regime', '?')}"
        buckets[key].append(f)
    return {k: {"n": len(v),
                "mfe_med": round(statistics.median([x["mfe"] for x in v]), 2),
                "mae_med": round(statistics.median([x["mae"] for x in v]), 2),
                "term_med": round(statistics.median([x["term"] for x in v]), 2),
                "mfe_sum": round(sum(x["mfe"] for x in v), 1),
                "ran1atr": round(sum(1 for x in v if x["mfe"] >= 1) / len(v), 2)}
            for k, v in sorted(buckets.items())}


# ═══════════════════════════════════════════════════════════════════════════
# 6. Reports
# ═══════════════════════════════════════════════════════════════════════════

def build(log: Path) -> Dict[str, Any]:
    parsed = parse(log)
    cfg = load_replay_cfg()
    parsed["_cfg"] = cfg
    enrich(parsed, cfg)
    cf = counterfactual(parsed)
    val = validate(parsed)
    ev = parsed["events"]
    rep: Dict[str, Any] = {
        "log": str(log),
        "runs": parsed["runs"],
        "pulses": {k: len(v) for k, v in parsed["pulses"].items()},
        "event_counts": dict(Counter(e["kind"] for e in ev)),
        "validation": val,
        "counterfactual": {k: {kk: vv for kk, vv in v.items() if kk != "states_k3"}
                           for k, v in cf.items()},
        "excursions": group_excursions(parsed, ev, 30),
        "detectors": {sym: detector_table({"pulses": parsed["pulses"]}, sym)
                      for sym in parsed["pulses"]},
    }
    return rep


def write_md(rep: Dict[str, Any], path: Path) -> None:
    L: List[str] = []
    a = L.append
    a(f"# Sniper gate replay — `{rep['log']}`")
    a("")
    a(f"- runs: **{len(rep['runs'])}**")
    a(f"- pulses: {rep['pulses']}")
    a(f"- events: `{json.dumps(rep['event_counts'], ensure_ascii=False)}`")
    a("")
    a("## Validation against the real gate decisions")
    a("")
    a("| check | n | reproduced |")
    a("|---|---|---|")
    for k, v in rep["validation"].items():
        if k == "gate_fail":
            a(f"| `PRE-AI GATE FAIL` conf (±0.011) | {v['n']} | {v['conf_within_0.011']} (median Δ {v['conf_median_delta']}) |")
            a(f"| `PRE-AI GATE FAIL` same_dir | {v['same_dir_n']} | {v['same_dir_exact']} exact |")
        else:
            a(f"| {k} conf (±0.011) | {v['n']} | {v['conf_within_0.011']} |")
    a("")
    a("## Gate counterfactual (ordinal timeline; non_squeeze assumed ranging)")
    a("")
    a("> ⚠️ Caveat: `trending` cannot be derived from the log, so non-squeeze pulses are")
    a("> treated as `ranging` and gated by `min_active_non_trend`. For a symbol that is mostly")
    a("> trending (BTC) this under-counts wakes badly — **use the logged wake count instead**.")
    a("> The k=3 row also doubles as a self-check: it should approximate the logged wakes.")
    a("")
    a("| symbol | span (days) | k | wakes | wakes/day | gate-blocked | blocked sd=1 | blocked sd=2 | logged wakes |")
    a("|---|---|---|---|---|---|---|---|---|")
    for sym, v in rep["counterfactual"].items():
        for k, s in v["summaries"].items():
            a(f"| {sym} | {v['days']} | {k[1:]} | {s['n_wakes']} | {s['n_wakes_per_day']} | "
              f"{s['n_gate_blocked']} | {s['blocked_same_dir1']} | {s['blocked_same_dir2']} | "
              f"{v['wakes_logged']} |")
    a("")
    a("## 1h forward excursions by decision point (ATR, signed by signal direction)")
    a("")
    a("| group | n | MFE med | MAE med | terminal med | MFE sum | reached +1ATR |")
    a("|---|---|---|---|---|---|---|")
    for g, s in rep["excursions"].items():
        a(f"| {g} | {s['n']} | {s['mfe_med']:+.2f} | {s['mae_med']:+.2f} | {s['term_med']:+.2f} | "
          f"{s['mfe_sum']:+.1f} | {s['ran1atr']:.0%} |")
    a("")
    a("## Detector fire rates")
    a("")
    for sym, rows in rep["detectors"].items():
        a(f"### {sym}")
        a("")
        a("| detector | pulses | rate | median strength | p90 |")
        a("|---|---|---|---|---|")
        for r in rows:
            a(f"| {r['detector']} | {r['pulses']} | {r['rate']:.1%} | {r['median_strength']:.2f} | {r['p90_strength']:.2f} |")
        a("")
    path.write_text("\n".join(L))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--log", default=str(DEFAULT_LOG))
    ap.add_argument("--out", default=None, help="write a markdown report here")
    ap.add_argument("--json", default=None, help="write the raw JSON report here")
    args = ap.parse_args()

    rep = build(Path(args.log))
    if args.out:
        write_md(rep, Path(args.out))
        print(f"markdown -> {args.out}")
    if args.json:
        Path(args.json).write_text(json.dumps(rep, indent=1, ensure_ascii=False, default=str))
        print(f"json     -> {args.json}")
    print(json.dumps({"runs": len(rep["runs"]), "pulses": rep["pulses"],
                      "events": rep["event_counts"], "validation": rep["validation"]},
                     indent=1, ensure_ascii=False))
    print("\ncounterfactual:")
    for sym, v in rep["counterfactual"].items():
        print(f"  {sym} ({v['days']}d):")
        for k, s in v["summaries"].items():
            print(f"    {k}: wakes={s['n_wakes']} ({s['n_wakes_per_day']}/day) "
                  f"gate_blocked={s['n_gate_blocked']} (sd1={s['blocked_same_dir1']}, sd2={s['blocked_same_dir2']})")


if __name__ == "__main__":
    main()
