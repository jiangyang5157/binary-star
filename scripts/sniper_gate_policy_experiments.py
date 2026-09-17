#!/usr/bin/env python3
"""Policy back-tests for the pre-AI gate / threshold settings.

Re-uses the validated log replay from ``scripts/analyze_sniper_gate.py`` and
scores alternative entry policies on the same 12.5 days:

  * how many wakes a policy admits (LLM cost proxy)
  * the 1-hour ATR-normalised MFE/MAE profile of the admitted candidates
  * the excess signed forward return vs. a same-direction baseline (controls
    for the market drift that otherwise dominates raw forward returns)

Policies are described declaratively so the plan can point at exact rules.
"""

from __future__ import annotations

import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.analyze_sniper_gate import (  # noqa: E402
    NEUTRAL_MULT,
    _cooldown_minutes,
    _tsec,
    load_replay_cfg,
    parse_log,
    replay,
)

ROOT = Path(__file__).resolve().parents[1]

# Direction provenance: signals whose direction is literally sign(cvd) are not
# independent of each other; everything else carries independent information.
CVD_SIGN = {"cvd_momentum", "large_trade", "volatility_surge"}
NEUTRAL_SUBTYPES = {"squeeze"}


def has_independent(active: List[str]) -> bool:
    return any(a not in CVD_SIGN and a not in NEUTRAL_SUBTYPES for a in active)


# ── policies ────────────────────────────────────────────────────────────────

Policy = Dict[str, Any]


def _gate_min(n: int):
    return lambda n_active, act: n_active >= n


def _gate_min_plus_independent(n: int):
    return lambda n_active, act: n_active >= n and has_independent(act)


POLICIES: List[Policy] = [
    {"id": "P0_current", "desc": "现状：threshold=base, gate=≥3, emergency=0.80",
     "threshold_delta": 0.0, "gate": _gate_min(3), "emergency": 0.80},
    {"id": "P1_gate2", "desc": "gate 3→2", "threshold_delta": 0.0, "gate": _gate_min(2),
     "emergency": 0.80},
    {"id": "P2_gate1", "desc": "gate 3→1", "threshold_delta": 0.0, "gate": _gate_min(1),
     "emergency": 0.80},
    {"id": "P3_emerg090", "desc": "emergency 0.80→0.90, gate 保持 3", "threshold_delta": 0.0,
     "gate": _gate_min(3), "emergency": 0.90},
    {"id": "P4_gate2_indep", "desc": "gate = ≥2 且含 1 个非 sign(cvd) 信号", "threshold_delta": 0.0,
     "gate": _gate_min_plus_independent(2), "emergency": 0.80},
    {"id": "P5_gate3_indep", "desc": "gate = ≥3 且含 1 个非 sign(cvd) 信号", "threshold_delta": 0.0,
     "gate": _gate_min_plus_independent(3), "emergency": 0.80},
    {"id": "P6_thr+06", "desc": "threshold +0.06, gate 保持 3", "threshold_delta": 0.06,
     "gate": _gate_min(3), "emergency": 0.80},
    {"id": "P7_thr+12", "desc": "threshold +0.12, gate 保持 3", "threshold_delta": 0.12,
     "gate": _gate_min(3), "emergency": 0.80},
    {"id": "P8_nogate_thr+12", "desc": "去掉 gate, threshold +0.12", "threshold_delta": 0.12,
     "gate": _gate_min(1), "emergency": 0.80},
    {"id": "P9_nogate_thr+20", "desc": "去掉 gate, threshold +0.20", "threshold_delta": 0.20,
     "gate": _gate_min(1), "emergency": 0.80},
]


# ── evaluation ──────────────────────────────────────────────────────────────

def run_policy(rows: List[Dict[str, Any]], wakes: List[Dict[str, Any]],
               resets: List[Dict[str, Any]], base_threshold: float,
               modifiers: Dict[str, float], pol: Policy) -> Dict[str, Any]:
    timeline = [(r["run"], _tsec(r["t"]), 0, r) for r in rows]
    timeline += [(w["run"], _tsec(w["t"]), 1, w) for w in wakes]
    timeline += [(r["run"], _tsec(r["t"]), 2, r) for r in resets]
    timeline.sort(key=lambda x: (x[0], x[1], x[2]))

    threshold = base_threshold + pol["threshold_delta"]
    emergency_thr = pol["emergency"]
    gate: Callable[[int, List[str]], bool] = pol["gate"]
    last_t = last_type = None
    cur_run = None
    fired: List[Dict[str, Any]] = []
    states: List[Dict[str, Any]] = []
    for run, ts, kind, obj in timeline:
        if run != cur_run:
            cur_run = run
            last_t = last_type = None
        if kind == 2:
            last_t = last_type = None
            continue
        if kind == 1:
            last_t, last_type = ts, "NEUTRAL"
            continue
        r = obj
        eff = threshold * modifiers.get(r["regime"], 1.0)
        emergency = r["max_strength"] >= emergency_thr
        should = emergency or r["conf"] >= eff
        cd_base = _cooldown_minutes(r["regime"], last_type) if last_t is not None else 0.0
        cd_active = last_t is not None and (ts - last_t) / 60.0 < cd_base
        engine_fire = should and (not cd_active or emergency)
        passed = engine_fire and gate(r["same_dir"], r["active"])
        st = {**r, "passed": passed, "engine_fire": engine_fire, "eff_threshold": eff,
              "emergency_dyn": emergency, "cd_active": cd_active}
        states.append(st)
        if passed:
            fired.append(st)
            last_t, last_type = ts, "NEUTRAL"
    return {"fired": fired, "states": states}


def quality(states: List[Dict[str, Any]], horizon: int = 30) -> Dict[str, Any]:
    """1-hour excursion profile of *fired* pulses, windowed over the full pulse
    series (not over the sparse fired subset)."""
    mfe, mae, term = [], [], []
    for i, s in enumerate(states):
        if not s.get("passed") or not s["price"] or not s.get("atr") or s["dir"] == "NEUTRAL":
            continue
        sign = 1.0 if s["dir"] == "BULLISH" else -1.0
        window = []
        for j in range(i + 1, min(i + 1 + horizon, len(states))):
            q = states[j]
            if q["run"] != s["run"] or not q["price"]:
                break
            window.append(sign * (q["price"] - s["price"]) / s["atr"])
        if len(window) < 10:
            continue
        mfe.append(max(window))
        mae.append(min(window))
        term.append(window[-1])
    if not mfe:
        return {"n": 0}
    n = len(mfe)
    return {
        "n": n,
        "mfe_med": round(statistics.median(mfe), 3),
        "mae_med": round(statistics.median(mae), 3),
        "term_med": round(statistics.median(term), 3),
        "ran1atr": round(sum(1 for a, b in zip(mfe, mae) if a >= 1.0 and a > -b) / n, 3),
        "stop1atr": round(sum(1 for a, b in zip(mfe, mae) if b <= -1.0 and -b >= a) / n, 3),
    }


def drift_adjusted(states: List[Dict[str, Any]], horizon: int = 30) -> Optional[float]:
    """Mean (candidate signed fwd return - same-run same-direction baseline)."""
    base: Dict[tuple, List[float]] = defaultdict(list)
    for i, s in enumerate(states):
        j = i + horizon
        if s["dir"] == "NEUTRAL" or not s["price"] or j >= len(states):
            continue
        if states[j]["run"] != s["run"] or not states[j]["price"]:
            continue
        raw = (states[j]["price"] - s["price"]) / s["price"] * 100.0
        signed = raw if s["dir"] == "BULLISH" else -raw
        base[(s["run"], s["dir"])].append(signed)
    excess = []
    for i, s in enumerate(states):
        if not s["passed"] or s["dir"] == "NEUTRAL" or not s["price"]:
            continue
        j = i + horizon
        if j >= len(states) or states[j]["run"] != s["run"] or not states[j]["price"]:
            continue
        raw = (states[j]["price"] - s["price"]) / s["price"] * 100.0
        signed = raw if s["dir"] == "BULLISH" else -raw
        pool = base.get((s["run"], s["dir"]))
        if not pool:
            continue
        excess.append(signed - statistics.fmean(pool))
    return round(statistics.fmean(excess), 3) if excess else None


def main() -> None:
    data = parse_log(ROOT / "data/prod/sniper.log")
    cfg = load_replay_cfg()
    rows = replay(data, cfg)

    out: Dict[str, Any] = {}
    for sym in ("XAUTUSDT", "BTCUSDT"):
        wakes = [w for w in data["wakes"] if w["sym"] == sym]
        resets = [r for r in data.get("resets", []) if r["sym"] == sym]
        base = cfg["base_threshold"][sym]
        mods = {"squeeze": cfg["regime_modifiers"]["squeeze"],
                "chaos": cfg["regime_modifiers"]["chaos"],
                "non_squeeze": cfg["regime_modifiers"]["ranging"]}
        res = []
        for pol in POLICIES:
            r = run_policy(rows[sym], wakes, resets, base, mods, pol)
            fired = r["fired"]
            hist = [w for w in wakes
                    if any(abs(_tsec(f["t"]) - _tsec(w["t"])) <= 3 and f["run"] == w["run"]
                           for f in fired)]
            res.append({
                "policy": pol["id"], "desc": pol["desc"],
                "n_wakes": len(fired), "per_day": round(len(fired) / 12.5, 2),
                "n_bull": sum(1 for f in fired if f["dir"] == "BULLISH"),
                "n_bear": sum(1 for f in fired if f["dir"] == "BEARISH"),
                "historical_wakes_kept": len(hist),
                "historical_wakes_total": len(wakes),
                "quality": quality(r["states"]),
                "excess_fwd_1h_pct": drift_adjusted(r["states"], 30),
            })
        out[sym] = res

    for sym, res in out.items():
        print(f"\n===== {sym}  (base threshold {cfg['base_threshold'][sym]}, "
              f"{len([w for w in data['wakes'] if w['sym'] == sym])} logged wakes) =====")
        hdr = (f"{'policy':18s} {'wakes':>6s} {'/day':>6s} {'kept':>7s} "
               f"{'MFE':>6s} {'MAE':>6s} {'ran1':>5s} {'stop1':>6s} {'excess1h':>9s}")
        print(hdr)
        for r in res:
            q = r["quality"]
            print(f"{r['policy']:18s} {r['n_wakes']:6d} {r['per_day']:6.2f} "
                  f"{r['historical_wakes_kept']:3d}/{r['historical_wakes_total']:<3d} "
                  f"{q.get('mfe_med', float('nan')):6.2f} {q.get('mae_med', float('nan')):6.2f} "
                  f"{q.get('ran1atr', float('nan')):5.0%} {q.get('stop1atr', float('nan')):6.0%} "
                  f"{str(r['excess_fwd_1h_pct']):>9s}")

    Path("/tmp/policy.json").write_text(json.dumps(out, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()
