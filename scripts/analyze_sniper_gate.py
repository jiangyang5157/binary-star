#!/usr/bin/env python3
"""Replay/analyse data/prod/sniper.log to evaluate the pre-AI gate settings.

Reads the daemon log, rebuilds the per-pulse signal stack from the SIGNAL DIAG
lines, replays SignalMemory + ConfluenceEngine + _run_pre_ai_gate exactly as
src/sniper/trigger.py does, and reports:

  * detector fire-rates / signal strength per symbol
  * logged WAKE events (signal strength, regime, session outcome)
  * counterfactual gate behaviour for min_active_non_trend in {1,2,3}
  * forward price behaviour after single-signal vs stacked pulses

Outputs JSON to stdout (and optionally a file).
"""

from __future__ import annotations

import argparse
import json
import math
import re
import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

ROOT = Path(__file__).resolve().parents[1]

# ── constants mirrored from src/sniper/trigger.py ────────────────────────
MIN_STACK_STRENGTH = 0.15
CVD_SATURATION_FACTOR = 3.0
CVD_ABSORPTION_SATURATION = 1.5
CVD_ABSORPTION_MIN_DENOM = 0.15
LARGE_TRADE_SATURATION = 2.0
FUNDING_SATURATION = 4.0
CVD_NEUTRAL_EPSILON = 0.01

LINE_RE = re.compile(
    r"^(?P<t>\d{2}:\d{2}:\d{2}\.\d{3})\s+(?P<lvl>INF|WRN|ERR|DBG)\s+\[(?P<tag>[^\]]+?)\s*\]\s+(?P<msg>.*)$"
)
DIAG_RE = re.compile(r"^\[(?P<sym>[A-Z0-9]+)\]\s+SIGNAL DIAG \| (?P<body>.*)$")
WAKE_RE = re.compile(
    r"^\[(?P<sym>[A-Z0-9]+)\]\s+WAKE \| dir=(?P<dir>\w+) \| confluence=(?P<conf>[\d.]+) \| "
    r"fresh=(?P<fresh>\d+) \| memory=(?P<mem>\d+) \| active=\[(?P<active>[^\]]*)\] \| "
    r"gate=(?P<gate>\w+) \| regime=(?P<regime>\w+)$"
)
WAKEUP_RE = re.compile(r"🔫 \[(?P<sym>[A-Z0-9]+)\] WAKE UP \| dir=(?P<dir>\w+) \| confluence=(?P<conf>[\d.]+)")
EVAL_RE = re.compile(r"^\[(?P<sym>[A-Z0-9]+)\] evaluating session \| opinion=(?P<op>\w+) \| confidence=(?P<c>[\d.]+)%")
LOWCONF_RE = re.compile(r"^\[(?P<sym>[A-Z0-9]+)\] confidence (?P<c>[\d.]+)% < threshold")
EXEC_RE = re.compile(r"^\[(?P<sym>[A-Z0-9]+)\] ALL GATES PASSED \| executing (?P<side>\w+)")
ACTIVE_RE = re.compile(r"^\[(?P<sym>[A-Z0-9]+)\] active trade \((?P<side>\w+)\) \| skipping AI session")
COOLDOWN_RE = re.compile(r"^\[(?P<sym>[A-Z0-9]+)\] cooldown (?:break|NOT broken|reset)")
RESET_RE = re.compile(r"^\[(?P<sym>[A-Z0-9]+)\] cooldown reset")
ARCHIVE_RE = re.compile(r"pipeline complete \| session archived \| file=(?P<f>\S+)")
SESSION_ID_RE = re.compile(r"(?P<sym>[A-Z0-9]+)_session_(?P<ts>\d{8}_\d{6})")


def _f(x, default=0.0):
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


# ═══════════════════════════════════════════════════════════════════════════
# 1. Parse the log
# ═══════════════════════════════════════════════════════════════════════════

def parse_diag(body: str) -> Dict[str, Any]:
    """Parse the pipe-separated SIGNAL DIAG payload into a flat dict."""
    out: Dict[str, Any] = {"detectors": {}}
    for raw in body.split(" | "):
        chunk = raw.strip()
        if chunk.startswith("cvd="):
            out["cvd"] = _f(chunk[4:])
        elif chunk.startswith("cvd_momentum="):
            out["detectors"]["cvd_momentum"] = _fired(chunk.split("=", 1)[1])
        elif chunk.startswith("cvd_divergence="):
            out["detectors"]["cvd_divergence"] = _fired(chunk.split("=", 1)[1])
        elif chunk.startswith("cvd_absorption="):
            out["detectors"]["cvd_absorption"] = _fired(chunk.split("=", 1)[1])
        elif chunk.startswith("trade_sz="):
            sz, _, n = chunk.partition("/n=")
            out["avg_trade_size"] = _f(sz[len("trade_sz="):])
            out["trade_count"] = int(_f(n, 0))
        elif chunk.startswith("large_trade="):
            out["detectors"]["large_trade"] = _fired(chunk.split("=", 1)[1])
            m = re.search(r"z=(-?[\d.]+)", chunk)
            out["large_trade_z"] = _f(m.group(1)) if m else None
        elif chunk.startswith("vii="):
            vii, _, vpr = chunk.partition(",vpr=")
            out["vii"] = _f(vii[4:])
            out["vpr"] = _f(vpr)
        elif chunk.startswith("vol_surge="):
            out["detectors"]["volatility_surge"] = _fired(chunk.split("=", 1)[1])
        elif chunk.startswith("squeeze="):
            out["detectors"]["squeeze"] = _fired(chunk.split("=", 1)[1])
            m = re.search(r"sf=([\d.]+)", chunk)
            out["squeeze_factor"] = _f(m.group(1)) if m else None
        elif chunk.startswith("price="):
            p, _, a = chunk.partition(",atr=")
            out["price"] = _f(p[6:])
            out["atr"] = _f(a)
        elif chunk.startswith("boundary_test="):
            out["detectors"]["boundary_test"] = _fired(chunk.split("=", 1)[1])
            m = re.search(r"dist_vh=([\d.]+),dist_val=([\d.]+)", chunk)
            if m:
                out["dist_vh"] = _f(m.group(1))
                out["dist_val"] = _f(m.group(2))
        elif chunk.startswith("liq_hunt="):
            out["detectors"]["liquidation_hunt"] = _fired(chunk.split("=", 1)[1])
        elif chunk.startswith("ls="):
            ls, _, rest = chunk.partition(",fund=")
            fund, _, oi = rest.partition(",oi_d=")
            out["ls"] = _f(ls[3:])
            out["funding"] = _f(fund)
            out["oi_delta"] = _f(oi)
        elif chunk.startswith("pos_ext="):
            out["detectors"]["positioning_extreme"] = _fired(chunk.split("=", 1)[1])
    return out


def _fired(tail: str) -> Optional[float]:
    """'F:0.55(growth)' -> 0.55 ; 'R:...' -> None"""
    if tail.startswith("F:"):
        m = re.match(r"F:([\d.]+)", tail)
        return _f(m.group(1)) if m else 0.0
    return None


@dataclass
class Pulse:
    sym: str
    t: str
    run: int
    diag: Dict[str, Any]
    signals: List[Dict[str, Any]] = field(default_factory=list)  # fresh SignalCards
    confluence: Optional[float] = None
    direction: Optional[str] = None
    regime: Optional[str] = None
    same_dir_active: int = 0
    should_trigger_core: Optional[bool] = None  # confluence >= threshold or emergency
    gate: Optional[str] = None


def parse_log(path: Path) -> Dict[str, Any]:
    runs: List[Dict[str, Any]] = []
    pulses: Dict[str, List[Pulse]] = defaultdict(list)
    wakes: List[Dict[str, Any]] = []
    sessions: List[Dict[str, Any]] = []
    archives: List[Dict[str, Any]] = []
    cooldown_events: List[Dict[str, Any]] = []
    run_idx = -1
    prev_diag: Dict[str, Dict[str, Any]] = {}
    prev_pulse: Dict[str, Pulse] = {}
    last_wake: Dict[str, Dict[str, Any]] = {}
    resets: List[Dict[str, Any]] = []

    for line in path.read_text().splitlines():
        m = LINE_RE.match(line)
        if not m:
            continue
        t, tag, msg = m.group("t"), m.group("tag").strip(), m.group("msg")

        if "SNIPER MONITORING STARTED" in msg:
            run_idx += 1
            runs.append({"idx": run_idx, "start": t, "end": t})
            prev_diag.clear()
            prev_pulse.clear()
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

        wm = WAKE_RE.match(msg)
        if wm:
            rec = {
                "t": t, "run": run_idx, "sym": wm.group("sym"), "dir": wm.group("dir"),
                "confluence": _f(wm.group("conf")), "fresh": int(wm.group("fresh")),
                "memory": int(wm.group("mem")),
                "active": [s for s in wm.group("active").replace("'", "").split(", ") if s],
                "gate": wm.group("gate"), "regime": wm.group("regime"),
            }
            wakes.append(rec)
            last_wake[rec["sym"]] = rec
            continue

        um = WAKEUP_RE.search(msg)
        if um:
            rec = last_wake.get(um.group("sym"))
            if rec is not None:
                rec["daemon_dir"] = um.group("dir")
                rec["daemon_confluence"] = _f(um.group("conf"))
            continue

        em = EVAL_RE.match(msg)
        if em:
            rec = last_wake.get(em.group("sym"))
            entry = {"t": t, "run": run_idx, "sym": em.group("sym"),
                     "opinion": em.group("op"), "confidence": _f(em.group("c")),
                     "confluence": rec["confluence"] if rec else None,
                     "regime": rec["regime"] if rec else None,
                     "n_active": len(rec["active"]) if rec else None,
                     "active": rec["active"] if rec else None}
            sessions.append(entry)
            if rec is not None:
                rec["opinion"] = em.group("op")
                rec["confidence"] = _f(em.group("c"))
            continue

        lm = LOWCONF_RE.match(msg)
        if lm:
            rec = last_wake.get(lm.group("sym"))
            if rec is not None:
                rec["low_conf_skip"] = True
            continue

        xm = EXEC_RE.match(msg)
        if xm:
            rec = last_wake.get(xm.group("sym"))
            if rec is not None:
                rec["executed"] = xm.group("side")
            continue

        am2 = ACTIVE_RE.match(msg)
        if am2:
            rec = last_wake.get(am2.group("sym"))
            if rec is not None:
                rec["skip_active"] = am2.group("side")
            continue

        rm = RESET_RE.match(msg)
        if rm:
            resets.append({"t": t, "run": run_idx, "sym": rm.group("sym")})
            continue

        if COOLDOWN_RE.match(msg):
            cooldown_events.append({"t": t, "run": run_idx, "msg": msg})
            continue

        am = ARCHIVE_RE.search(msg)
        if am:
            sm = SESSION_ID_RE.search(am.group("f"))
            archives.append({"t": t, "run": run_idx, "file": am.group("f"),
                             "sym": sm.group("sym") if sm else None,
                             "session_utc": sm.group("ts") if sm else None})
            continue

    return {"runs": runs, "pulses": dict(pulses), "wakes": wakes,
            "sessions": sessions, "archives": archives, "cooldown": cooldown_events,
            "resets": resets}


# ═══════════════════════════════════════════════════════════════════════════
# 2. Rebuild fresh signals (directions) — mirrors detector direction logic
# ═══════════════════════════════════════════════════════════════════════════

def build_fresh_signals(p: Pulse, prev_d: Optional[Dict[str, Any]],
                        prev_p: Optional[Pulse]) -> List[Dict[str, Any]]:
    d = p.diag
    det = d["detectors"]
    cvd = d.get("cvd", 0.0)
    out: List[Dict[str, Any]] = []
    price = d.get("price")
    prev_price = prev_d.get("price") if prev_d else None
    price_delta = (price - prev_price) if (price is not None and prev_price is not None) else None
    prev_cvd = prev_d.get("cvd") if prev_d else None
    cvd_delta = (cvd - prev_cvd) if prev_cvd is not None else None

    if det.get("cvd_momentum") is not None:
        out.append({"sub_type": "cvd_momentum", "strength": det["cvd_momentum"],
                    "direction": "BULLISH" if cvd > 0 else "BEARISH"})
    if det.get("cvd_divergence") is not None:
        # BEARISH when price rose, BULLISH when price fell
        if price_delta is not None and price_delta != 0:
            out.append({"sub_type": "cvd_divergence", "strength": det["cvd_divergence"],
                        "direction": "BEARISH" if price_delta > 0 else "BULLISH"})
    if det.get("cvd_absorption") is not None:
        out.append({"sub_type": "cvd_absorption", "strength": det["cvd_absorption"],
                    "direction": "BEARISH" if cvd > 0 else "BULLISH"})
    if det.get("large_trade") is not None:
        if abs(cvd) <= CVD_NEUTRAL_EPSILON:
            direction = "NEUTRAL"
        else:
            direction = "BULLISH" if cvd > 0 else "BEARISH"
        out.append({"sub_type": "large_trade", "strength": det["large_trade"], "direction": direction})
    if det.get("volatility_surge") is not None:
        direction = "BULLISH" if cvd > 0 else "BEARISH" if abs(cvd) > 0.05 else "NEUTRAL"
        out.append({"sub_type": "volatility_surge", "strength": det["volatility_surge"],
                    "direction": direction})
    if det.get("squeeze") is not None:
        out.append({"sub_type": "squeeze", "strength": det["squeeze"], "direction": "NEUTRAL"})
    if det.get("boundary_test") is not None:
        dvh, dval = d.get("dist_vh"), d.get("dist_val")
        direction = "BULLISH" if (dvh is not None and dval is not None and dvh < dval) else "BEARISH"
        out.append({"sub_type": "boundary_test", "strength": det["boundary_test"], "direction": direction})
    if det.get("liquidation_hunt") is not None:
        direction = "BULLISH" if (price_delta is not None and price_delta > 0) else "BEARISH"
        out.append({"sub_type": "liquidation_hunt", "strength": det["liquidation_hunt"],
                    "direction": direction})
    if det.get("positioning_extreme") is not None:
        out.append({"sub_type": "positioning_extreme", "strength": det["positioning_extreme"],
                    "direction": _pos_ext_direction(d)})
    return out


def _pos_ext_direction(d: Dict[str, Any]) -> str:
    """Best-effort direction for positioning_extreme from logged (rounded) inputs."""
    ls = d.get("ls", 1.0)
    s = d["detectors"]["positioning_extreme"]
    # Path 1a: ls > long_short_imbalance_ratio -> BEARISH
    if ls > 1.5:
        return "BEARISH"
    # Path 1b: ls < short_heavy_imbalance_ratio (0.6) -> BULLISH
    cand_short = min((1.0 - ls) / ((1.0 - 0.6) * 2), 1.0)
    cand_long = min((ls - 1.0) / (1.5 * 2), 1.0)
    if ls < 1.0 and abs(cand_short - s) <= 0.08:
        return "BULLISH"
    if ls > 1.0 and abs(cand_long - s) <= 0.08:
        return "BEARISH"
    funding = d.get("funding", 0.0)
    if abs(funding) > 5e-4:
        return "BEARISH" if funding > 0 else "BULLISH"
    return "BULLISH" if ls < 1.0 else "BEARISH"


# ═══════════════════════════════════════════════════════════════════════════
# 3. Replay memory / confluence / gate
# ═══════════════════════════════════════════════════════════════════════════

def _tsec(t: str) -> float:
    h, m, s = t.split(":")
    return int(h) * 3600 + int(m) * 60 + float(s)


class Replay:
    def __init__(self, cfg: Dict[str, Any], symbol: str):
        self.weights = cfg["weights"]
        self.decay = cfg["decay"]
        self.modifiers = cfg["regime_modifiers"]
        self.base_threshold = cfg["base_threshold"][symbol]
        self.emergency = cfg.get("emergency_threshold", 0.80)
        self.regime_cfg = cfg["regime_params"][symbol]
        self.memory: Dict[str, Dict[str, Any]] = {}

    def _decay_hl(self, sub: str) -> float:
        return float(self.decay.get(sub, 15))

    def ingest(self, fresh: List[Dict[str, Any]], now: float) -> List[Dict[str, Any]]:
        """Mirror SignalMemory.ingest — mutates stored strengths with decay."""
        for key in list(self.memory):
            card = self.memory[key]
            elapsed = (now - card["t"]) / 60.0
            if elapsed <= 0:
                d_strength = card["strength"]
            else:
                d_strength = card["strength"] * (0.5 ** (elapsed / max(self._decay_hl(key), 1.0)))
            if d_strength > 0.05:
                card["strength"] = d_strength
            else:
                del self.memory[key]
        fresh_keys = set()
        for ns in fresh:
            fresh_keys.add(ns["sub_type"])
            self.memory[ns["sub_type"]] = {"direction": ns["direction"], "strength": ns["strength"],
                                           "t": now}
        alive = [dict(direction=c["direction"], strength=c["strength"], sub_type=k)
                 for k, c in self.memory.items()]
        return [dict(s) for s in fresh] + [a for a in alive if a["sub_type"] not in fresh_keys]

    def regime_of(self, d: Dict[str, Any]) -> str:
        vii = d.get("vii", 0) or 0
        sf = d.get("squeeze_factor")
        if sf is None:  # squeeze detector fired -> not logged; treat as >= regime threshold
            sf = self.regime_cfg["squeeze_threshold"]
        if vii > self.regime_cfg["volatility_extreme_ratio"]:
            return "chaos"
        if sf < self.regime_cfg["squeeze_threshold"]:
            return "squeeze"
        return "non_squeeze"  # trending/ranging unresolved from the log

    def evaluate(self, all_signals: List[Dict[str, Any]]):
        bull = self._dir_score(all_signals, "BULLISH")
        bear = self._dir_score(all_signals, "BEARISH")
        if bull > bear:
            dom, raw = "BULLISH", bull
        elif bear > bull:
            dom, raw = "BEARISH", bear
        else:
            return 0.0, "NEUTRAL"
        return raw * (1.0 - bull * bear), dom

    def _dir_score(self, signals, direction) -> float:
        product = 1.0
        any_ = False
        for s in signals:
            if s["direction"] == direction and s["strength"] >= MIN_STACK_STRENGTH:
                any_ = True
                product *= (1.0 - s["strength"] * self.weights.get(s["sub_type"], 0.0))
        return (1.0 - product) if any_ else 0.0


def replay(data: Dict[str, Any], cfg: Dict[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for sym, plist in data["pulses"].items():
        rp = Replay(cfg, sym)
        rows = []
        run_seen = None
        for p in plist:
            if run_seen != p.run:
                rp = Replay(cfg, sym)  # daemon restart resets memory
                run_seen = p.run
            now = _tsec(p.t)
            all_sig = rp.ingest(p.signals, now)
            conf, dom = rp.evaluate(all_sig)
            regime = rp.regime_of(p.diag)
            same_dir = [s for s in all_sig
                        if s["direction"] == dom and s["strength"] >= MIN_STACK_STRENGTH]
            modifier = 1.0 if regime == "non_squeeze" else rp.modifiers[regime]
            threshold = rp.base_threshold * modifier
            # logged strengths are rounded to 2dp -> require a hair above the
            # threshold so a logged "0.80" that was really 0.781 is not counted
            emergency = any(s["strength"] >= rp.emergency + 0.005 and s["direction"] != "NEUTRAL"
                            for s in all_sig)
            max_strength = max((s["strength"] for s in all_sig if s["direction"] != "NEUTRAL"),
                               default=0.0)
            should = emergency or (conf >= threshold)
            p.confluence, p.direction, p.regime = conf, dom, regime
            p.same_dir_active = len(same_dir)
            p.should_trigger_core = should
            p.gate = None if not should else ("PASS" if len(same_dir) >= 3 else "FAIL3")
            rows.append({
                "t": p.t, "run": p.run, "conf": conf, "dir": dom, "regime": regime,
                "threshold": threshold, "should": should, "same_dir": len(same_dir),
                "emergency": emergency, "max_strength": round(max_strength, 4),
                "fresh": [s["sub_type"] for s in p.signals],
                "fresh_dir": {s["sub_type"]: s["direction"] for s in p.signals},
                "active": sorted(s["sub_type"] for s in same_dir),
                "price": p.diag.get("price"), "atr": p.diag.get("atr"),
                "cvd": p.diag.get("cvd"),
                "vii": p.diag.get("vii"), "sf": p.diag.get("squeeze_factor"),
            })
        out[sym] = rows
    return out


# ═══════════════════════════════════════════════════════════════════════════
# 4. Cooldown-aware counterfactual
# ═══════════════════════════════════════════════════════════════════════════

COOLDOWN_BASE = {"trending": 20, "ranging": 40, "squeeze": 20, "chaos": 60}
NEUTRAL_MULT = 0.8


def trigger_type_of(w: Dict[str, Any]) -> str:
    """Mirror run_sniper.py: TRADED for any directional opinion, NEUTRAL for a
    NEUTRAL opinion, ACTIVE_POSITION when a live trade blocks the session,
    FAILED when the session errored (no opinion recorded)."""
    if w.get("executed"):
        return "TRADED"
    if w.get("skip_active"):
        return "ACTIVE_POSITION"
    if w.get("opinion") in ("BULLISH", "BEARISH"):
        return "TRADED"
    if w.get("opinion") == "NEUTRAL":
        return "NEUTRAL"
    return "FAILED"


def _cooldown_minutes(regime: str, ttype: str) -> float:
    base = COOLDOWN_BASE["ranging"]
    if regime == "squeeze":
        base = COOLDOWN_BASE["squeeze"]
    elif regime == "chaos":
        base = COOLDOWN_BASE["chaos"]
    if ttype in ("NEUTRAL", "OBSERVE_ONLY"):
        base *= NEUTRAL_MULT
    elif ttype == "FAILED":
        base = 3
    return base


def counterfactual(data: Dict[str, Any], rows: Dict[str, List[Dict[str, Any]]]) -> Dict[str, Any]:
    """Replay the full pre-AI pipeline per gate setting.

    Ground truth: every logged WAKE starts a cooldown with the trigger_type the
    daemon actually used.  Counterfactual wakes admitted by a looser gate are
    assumed to end NEUTRAL (the dominant logged outcome) so their cooldown is
    0.8x the regime base — this yields an upper bound on extra wake volume.
    """
    out: Dict[str, Any] = {}
    for sym, rr in rows.items():
        wakes = [w for w in data["wakes"] if w["sym"] == sym]
        resets = [r for r in data.get("resets", []) if r["sym"] == sym]
        base_timeline = [(r["run"], _tsec(r["t"]), 0, r) for r in rr]
        base_timeline += [(w["run"], _tsec(w["t"]), 1, w) for w in wakes]
        base_timeline += [(r["run"], _tsec(r["t"]), 2, r) for r in resets]
        base_timeline.sort(key=lambda x: (x[0], x[1], x[2]))

        # k=3 run doubles as the model validation and provides per-pulse state
        per_pulse_k3: List[Dict[str, Any]] = []
        sims: Dict[int, List[Dict[str, Any]]] = {}
        for k in (1, 2, 3):
            last_t = last_type = None
            cur_run = None
            fired: List[Dict[str, Any]] = []
            states: List[Dict[str, Any]] = []
            for run, ts, kind, obj in base_timeline:
                if run != cur_run:
                    cur_run = run
                    last_t = last_type = None
                if kind == 2:
                    last_t = last_type = None
                    continue
                if kind == 1:
                    last_t, last_type = ts, trigger_type_of(obj)
                    continue
                r = obj
                cd_base = _cooldown_minutes(r["regime"], last_type) if last_t is not None else 0.0
                cd_active = last_t is not None and (ts - last_t) / 60.0 < cd_base
                engine_fire = r["should"] and (not cd_active or r["emergency"])
                passed = engine_fire and r["same_dir"] >= k
                gate_blocked = engine_fire and r["same_dir"] < k
                st = {**r, "cd_active": cd_active, "cd_base": cd_base,
                      "engine_fire": engine_fire, "gate_blocked": gate_blocked}
                states.append(st)
                if passed:
                    fired.append({"t": r["t"], "run": r["run"], "dir": r["dir"], "conf": r["conf"],
                                  "same_dir": r["same_dir"], "regime": r["regime"],
                                  "emergency": r["emergency"], "prices": r["price"], "atr": r.get("atr")})
                    last_t, last_type = ts, "NEUTRAL"  # counterfactual outcome assumption
            for st in states:
                st["passed"] = any(f["t"] == st["t"] and f["run"] == st["run"] for f in fired)
            sims[k] = {"fired": fired, "states": states}
            if k == 3:
                per_pulse_k3 = states

        fired3 = sims[3]["fired"]
        matched, missed = 0, []
        for w in wakes:
            wt = _tsec(w["t"])
            if any(abs(_tsec(f["t"]) - wt) <= 3 and f["run"] == w["run"] for f in fired3):
                matched += 1
            else:
                near = [p for p in per_pulse_k3 if abs(_tsec(p["t"]) - wt) <= 3 and p["run"] == w["run"]]
                if near:
                    n = near[0]
                    why = ("not_should" if not n["should"] else
                           "cooldown" if (n["cd_active"] and not n["emergency"]) else
                           "gate" if n["same_dir"] < 3 else "unknown")
                else:
                    why = "no_pulse"
                missed.append({"t": w["t"], "dir": w["dir"], "regime": w["regime"], "why": why})

        summaries = {}
        for k in (1, 2, 3):
            st = sims[k]["states"]
            blocked = [p for p in st if p["gate_blocked"]]
            summaries[f"k{k}"] = {
                "n_wakes": len(sims[k]["fired"]),
                "n_wakes_per_day": round(len(sims[k]["fired"]) / 12.5, 2),
                "n_wakes_bullish": sum(1 for f in sims[k]["fired"] if f["dir"] == "BULLISH"),
                "n_wakes_bearish": sum(1 for f in sims[k]["fired"] if f["dir"] == "BEARISH"),
                "n_wakes_squeeze": sum(1 for f in sims[k]["fired"] if f["regime"] == "squeeze"),
                "n_wakes_emergency": sum(1 for f in sims[k]["fired"] if f["emergency"]),
                "n_gate_blocked": len(blocked),
                "blocked_same_dir1": sum(1 for p in blocked if p["same_dir"] == 1),
                "blocked_same_dir2": sum(1 for p in blocked if p["same_dir"] == 2),
                "blocked_conf_median": round(statistics.median([p["conf"] for p in blocked]), 3) if blocked else None,
                "blocked_dir": dict(Counter(p["dir"] for p in blocked)),
                "blocked_regime": dict(Counter(p["regime"] for p in blocked)),
            }
        out[sym] = {
            "n_pulses": len(per_pulse_k3),
            "n_confluence_met": sum(1 for p in per_pulse_k3 if p["should"]),
            "n_emergency": sum(1 for p in per_pulse_k3 if p["emergency"]),
            "n_cooldown_blocked": sum(1 for p in per_pulse_k3 if p["should"] and p["cd_active"] and not p["emergency"]),
            "n_logged_wakes": len(wakes),
            "k3_reproduces_wakes": matched,
            "k3_missed_wakes": missed,
            "summaries": summaries,
            "per_pulse": per_pulse_k3,
        }
    return out


# ═══════════════════════════════════════════════════════════════════════════
# 5. Forward-return study
# ═══════════════════════════════════════════════════════════════════════════

def signed_fwd(per_pulse: List[Dict[str, Any]], horizon: int) -> Dict[str, List[float]]:
    """Signed forward return (%) by group over `horizon` pulses (~2 min each)."""
    groups: Dict[str, List[float]] = defaultdict(list)
    for i, p in enumerate(per_pulse):
        if p["dir"] == "NEUTRAL" or not p["price"]:
            continue
        j = i + horizon
        if j >= len(per_pulse) or per_pulse[j]["run"] != p["run"] or not per_pulse[j]["price"]:
            continue
        raw = (per_pulse[j]["price"] - p["price"]) / p["price"] * 100.0
        signed = raw if p["dir"] == "BULLISH" else -raw
        buckets = []
        if p["passed"]:
            buckets.append("passed_gate")
        elif p["gate_blocked"]:
            buckets.append(f"gate_blocked_sd{p['same_dir']}")
        if p["engine_fire"] and p["same_dir"] == 1:
            buckets.append("single_signal_fire")
        if p["engine_fire"] and p["same_dir"] >= 3:
            buckets.append("stacked3plus_fire")
        for b in buckets:
            groups[b].append(signed)
    return groups


def excursion_study(per_pulse: List[Dict[str, Any]], horizon: int = 30) -> Dict[str, Any]:
    """For every engine-fire candidate compute the signed MFE/MAE over the next
    `horizon` pulses (~2 min each) in ATR units, plus the terminal move."""
    out = []
    for i, p in enumerate(per_pulse):
        if not p["engine_fire"] or p["dir"] == "NEUTRAL" or not p["price"] or not p.get("atr"):
            continue
        sign = 1.0 if p["dir"] == "BULLISH" else -1.0
        window = []
        for j in range(i + 1, min(i + 1 + horizon, len(per_pulse))):
            q = per_pulse[j]
            if q["run"] != p["run"] or not q["price"]:
                break
            window.append(sign * (q["price"] - p["price"]) / p["atr"])
        if len(window) < 10:
            continue
        out.append({**p, "mfe_atr": max(window), "mae_atr": min(window),
                    "term_atr": window[-1], "n_atr": p["atr"]})
    return out


def excursion_groups(exc: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    groups: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for e in exc:
        d = e["dir"][:4]
        if e["passed"]:
            groups["pass_gate"].append(e)
            groups[f"pass_gate_{d}"].append(e)
        elif e["gate_blocked"]:
            groups[f"gate_blocked_sd{e['same_dir']}"].append(e)
            groups[f"blocked_sd{e['same_dir']}_{d}"].append(e)
        groups["all_candidates"].append(e)
    res = {}
    for g, items in groups.items():
        res[g] = {
            "n": len(items),
            "mfe_atr_median": round(statistics.median([x["mfe_atr"] for x in items]), 3),
            "mae_atr_median": round(statistics.median([x["mae_atr"] for x in items]), 3),
            "term_atr_mean": round(statistics.fmean([x["term_atr"] for x in items]), 3),
            "term_atr_median": round(statistics.median([x["term_atr"] for x in items]), 3),
            # a candidate is a genuine "missed move" if it ran +1 ATR before -1 ATR
            "would_have_run_1atr": round(
                sum(1 for x in items if x["mfe_atr"] >= 1.0 and x["mfe_atr"] > -x["mae_atr"]) / len(items), 3),
            "would_have_stopped_1atr": round(
                sum(1 for x in items if x["mae_atr"] <= -1.0 and -x["mae_atr"] >= x["mfe_atr"]) / len(items), 3),
            "chop": round(sum(1 for x in items if x["mfe_atr"] < 1.0 and x["mae_atr"] > -1.0) / len(items), 3),
        }
    return res


# ═══════════════════════════════════════════════════════════════════════════
# 6. Config assembly
# ═══════════════════════════════════════════════════════════════════════════

def load_replay_cfg() -> Dict[str, Any]:
    from src.config.symbol_resolver import resolve_config  # type: ignore

    g = yaml.safe_load((ROOT / "config/global_config.yaml").read_text())
    s = yaml.safe_load((ROOT / "config/strategy_config.yaml").read_text())
    base = g["sniper"]["signal_stack"]
    out = {"weights": base["weights"], "decay": base["decay"],
           "regime_modifiers": base["regime_modifiers"],
           "emergency_threshold": base.get("emergency_threshold", 0.80),
           "base_threshold": {}, "regime_params": {}}
    base_thr = {"XAUTUSDT": 0.34, "BTCUSDT": 0.36}
    for sym in ("XAUTUSDT", "BTCUSDT"):
        sg = resolve_config(g, sym)
        ss = resolve_config(s, sym)
        out["base_threshold"][sym] = sg["sniper"]["signal_stack"]["trigger_threshold"]
        rp = ss["regime_parameters"]
        out["regime_params"][sym] = {
            "volatility_extreme_ratio": rp["volatility"]["volatility_extreme_ratio"],
            "squeeze_threshold": rp["volatility"]["squeeze_threshold"],
            "trend_intensity_strong": rp["trend"]["trend_intensity_strong"],
        }
        out.setdefault("gate", {})[sym] = sg["sniper"]["signal_stack"]["gate"]
    return out


# ═══════════════════════════════════════════════════════════════════════════
# 7. Reporting
# ═══════════════════════════════════════════════════════════════════════════

def _stats(xs):
    if not xs:
        return None
    xs = sorted(xs)
    return {"n": len(xs), "mean": round(statistics.fmean(xs), 3),
            "median": round(statistics.median(xs), 3),
            "p25": round(xs[int(0.25 * (len(xs) - 1))], 3),
            "p75": round(xs[int(0.75 * (len(xs) - 1))], 3),
            "pos_rate": round(sum(1 for x in xs if x > 0) / len(xs), 3)}


def detector_table(data, sym):
    rows = []
    fire = Counter()
    strengths = defaultdict(list)
    pulses = data["pulses"][sym]
    for p in pulses:
        for s in p.signals:
            fire[s["sub_type"]] += 1
            strengths[s["sub_type"]].append(s["strength"])
    for k, v in fire.most_common():
        st = sorted(strengths[k])
        rows.append({"detector": k, "pulses": v, "rate": round(v / len(pulses), 4),
                     "median_strength": round(statistics.median(st), 3),
                     "p90_strength": round(st[int(0.9 * (len(st) - 1))], 3)})
    return rows


def build_report(data, cfg, cf, val) -> Dict[str, Any]:
    rep: Dict[str, Any] = {
        "meta": {
            "runs": len(data["runs"]),
            "run_start": data["runs"][0]["start"] if data["runs"] else None,
            "run_end": data["runs"][-1]["end"] if data["runs"] else None,
            "pulses": {k: len(v) for k, v in data["pulses"].items()},
            "wakes": len(data["wakes"]),
            "sessions": len(data["sessions"]),
            "effective_gate": cfg.get("gate"),
            "base_threshold": cfg["base_threshold"],
        },
        "replay_validation": {
            "n_wakes": len(val),
            "confluence_match": sum(1 for v in val if v.get("conf_ok")),
            "direction_match": sum(1 for v in val if v.get("dir_ok")),
            "fresh_set_match": sum(1 for v in val if v.get("fresh_ok")),
        },
        "symbols": {},
    }
    for sym in ("XAUTUSDT", "BTCUSDT"):
        rr = cf[sym]["per_pulse"]
        wakes = [w for w in data["wakes"] if w["sym"] == sym]
        wake_rows = []
        for w in wakes:
            wake_rows.append({
                "t": w["t"], "run": w["run"], "dir": w["dir"],
                "confluence": w["confluence"], "regime": w["regime"],
                "fresh": w["fresh"], "memory": w["memory"], "active": w["active"],
                "opinion": w.get("opinion"), "confidence": w.get("confidence"),
                "executed": w.get("executed"), "skip_active": w.get("skip_active"),
                "low_conf_skip": w.get("low_conf_skip"),
                "trigger_type": trigger_type_of(w),
            })
        rep["symbols"][sym] = {
            "n_pulses": cf[sym]["n_pulses"],
            "n_confluence_met": cf[sym]["n_confluence_met"],
            "n_emergency": cf[sym]["n_emergency"],
            "n_cooldown_blocked": cf[sym]["n_cooldown_blocked"],
            "n_logged_wakes": cf[sym]["n_logged_wakes"],
            "k3_reproduces_wakes": cf[sym]["k3_reproduces_wakes"],
            "k3_missed_wakes": cf[sym]["k3_missed_wakes"],
            "regimes": dict(Counter(r["regime"] for r in rr)),
            "fresh_count_hist": dict(sorted(Counter(len(p["fresh"]) for p in rr).items())),
            "detectors": detector_table(data, sym),
            "gate_summaries": cf[sym]["summaries"],
            "wakes": wake_rows,
            "fwd": {f"{h}pulses": {k: _stats(v) for k, v in signed_fwd(rr, h).items()}
                    for h in (5, 15, 30, 60)},
            "excursions_1h_atr": excursion_groups(excursion_study(rr, 30)),
        }
    return rep


def write_markdown(rep, path: Path):
    L = []
    a = L.append
    m = rep["meta"]
    a("# Sniper signal / gate analysis — `data/prod/sniper.log`")
    a("")
    a(f"- daemon runs in log: **{m['runs']}**")
    a(f"- pulses: {m['pulses']}")
    a(f"- logged WAKEs: **{m['wakes']}**, sessions: {m['sessions']}")
    a(f"- effective gate config: `{json.dumps(m['effective_gate'], ensure_ascii=False)}`")
    a(f"- base trigger thresholds: {m['base_threshold']}")
    rv = rep["replay_validation"]
    a(f"- replay validation: confluence {rv['confluence_match']}/{rv['n_wakes']}, "
      f"direction {rv['direction_match']}/{rv['n_wakes']}, fresh-set {rv['fresh_set_match']}/{rv['n_wakes']}")
    a("")
    for sym, d in rep["symbols"].items():
        a(f"## {sym}")
        a("")
        a(f"- pulses: {d['n_pulses']}  regimes: {d['regimes']}")
        a(f"- fresh-signal count per pulse: {d['fresh_count_hist']}")
        a(f"- pulses meeting confluence threshold: **{d['n_confluence_met']}** "
          f"(emergency-bypass: {d['n_emergency']}, cooldown-blocked: {d['n_cooldown_blocked']})")
        a(f"- logged wakes: {d['n_logged_wakes']}; k=3 replay reproduces {d['k3_reproduces_wakes']} "
          f"(missed: {d['k3_missed_wakes']})")
        a("")
        a("### detector fire-rate / strength")
        a("")
        a("| detector | fire pulses | rate | median strength | p90 strength |")
        a("|---|---|---|---|---|")
        for r in d["detectors"]:
            a(f"| {r['detector']} | {r['pulses']} | {r['rate']:.1%} | {r['median_strength']:.2f} | {r['p90_strength']:.2f} |")
        a("")
        a("### gate counterfactual (non-trend regimes; cooldown modelled from logged wakes)")
        a("")
        a("| min_active_non_trend | wakes | wakes/day | blocked | blocked w/ 1 signal | blocked w/ 2 signals | median conf of blocked |")
        a("|---|---|---|---|---|---|---|")
        for k in ("k1", "k2", "k3"):
            s = d["gate_summaries"][k]
            a(f"| {k[1:]} | {s['n_wakes']} | {s['n_wakes_per_day']} | {s['n_gate_blocked']} | "
              f"{s['blocked_same_dir1']} | {s['blocked_same_dir2']} | {s['blocked_conf_median']} |")
        a("")
        a("### wakes")
        a("")
        a("| t | run | dir | conf | regime | fresh | mem | active | opinion | trigger_type |")
        a("|---|---|---|---|---|---|---|---|---|---|")
        for w in d["wakes"]:
            a(f"| {w['t']} | {w['run']} | {w['dir']} | {w['confluence']:.2f} | {w['regime']} | "
              f"{w['fresh']} | {w['memory']} | {', '.join(w['active'])} | "
              f"{w['opinion'] or '-'} | {w['trigger_type']} |")
        a("")
        a("### signed forward return by group (% move in signal direction)")
        a("")
        a("| horizon | group | n | mean | median | p25 | p75 | pos-rate |")
        a("|---|---|---|---|---|---|---|---|")
        for h, groups in d["fwd"].items():
            for g, st in sorted(groups.items()):
                if not st:
                    continue
                a(f"| {h} | {g} | {st['n']} | {st['mean']} | {st['median']} | {st['p25']} | {st['p75']} | {st['pos_rate']:.0%} |")
        a("")
        a("### 1h ATR-normalised excursions (engine-fire candidates)")
        a("")
        a("| group | n | MFE med (ATR) | MAE med (ATR) | terminal med (ATR) | ran +1ATR first | stopped -1ATR first | chop |")
        a("|---|---|---|---|---|---|---|---|")
        for g, st in sorted(d["excursions_1h_atr"].items()):
            a(f"| {g} | {st['n']} | {st['mfe_atr_median']:+.2f} | {st['mae_atr_median']:+.2f} | "
              f"{st['term_atr_median']:+.2f} | {st['would_have_run_1atr']:.0%} | "
              f"{st['would_have_stopped_1atr']:.0%} | {st['chop']:.0%} |")
        a("")
    path.write_text("\n".join(L))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--log", default=str(ROOT / "data/prod/sniper.log"))
    ap.add_argument("--out", default=None)
    ap.add_argument("--json", default=None)
    args = ap.parse_args()

    data = parse_log(Path(args.log))
    cfg = load_replay_cfg()
    rows = replay(data, cfg)
    cf = counterfactual(data, rows)

    val = []
    for w in data["wakes"]:
        wt = _tsec(w["t"])
        cands = [r for r in rows[w["sym"]] if r["run"] == w["run"] and abs(_tsec(r["t"]) - wt) <= 3.0]
        if not cands:
            val.append({"t": w["t"], "sym": w["sym"], "match": False})
            continue
        r = min(cands, key=lambda x: abs(_tsec(x["t"]) - wt))
        val.append({
            "t": w["t"], "pulse_t": r["t"], "sym": w["sym"], "match": True,
            "log_conf": w["confluence"], "replay_conf": round(r["conf"], 4),
            "conf_ok": abs(r["conf"] - w["confluence"]) <= 0.011,
            "log_dir": w["dir"], "replay_dir": r["dir"], "dir_ok": r["dir"] == w["dir"],
            "log_regime": w["regime"], "replay_regime": r["regime"],
            "log_fresh": w["fresh"], "replay_fresh": len(r["fresh"]),
            "fresh_ok": w["fresh"] == len(r["fresh"]),
            "log_active": w["active"], "replay_active": r["active"],
            "same_dir_replay": r["same_dir"],
        })

    rep = build_report(data, cfg, cf, val)
    if args.json:
        slim = {k: v for k, v in rep.items()}
        Path(args.json).write_text(json.dumps(slim, indent=1, ensure_ascii=False, default=str))
    if args.out:
        write_markdown(rep, Path(args.out))
    print(json.dumps({k: v for k, v in rep.items() if k != "symbols"}, indent=1, ensure_ascii=False, default=str))
    for sym, d in rep["symbols"].items():
        print(f"\n== {sym} ==")
        print(" pulses", d["n_pulses"], "regimes", d["regimes"])
        print(" confluence-met", d["n_confluence_met"], "emergency", d["n_emergency"],
              "cooldown-blocked", d["n_cooldown_blocked"])
        print(" fresh-hist", d["fresh_count_hist"])
        print(" k3 reproduces wakes", d["k3_reproduces_wakes"], "of", d["n_logged_wakes"],
              "missed", d["k3_missed_wakes"])
        for k, s in d["gate_summaries"].items():
            print(f"  {k}: wakes={s['n_wakes']} ({s['n_wakes_per_day']}/day, "
                  f"bull={s['n_wakes_bullish']} bear={s['n_wakes_bearish']} "
                  f"squeeze={s['n_wakes_squeeze']} emerg={s['n_wakes_emergency']}) "
                  f"gate_blocked={s['n_gate_blocked']} (sd1={s['blocked_same_dir1']} sd2={s['blocked_same_dir2']}) "
                  f"median_conf={s['blocked_conf_median']} dirs={s['blocked_dir']} regimes={s['blocked_regime']}")
        for h, groups in d["fwd"].items():
            for g, st in sorted(groups.items()):
                print(f"  fwd {h:4s} {g:22s} n={st['n']:4d} mean={st['mean']:+.3f}% "
                      f"med={st['median']:+.3f}% pos={st['pos_rate']:.0%}")
        print("  -- 1h ATR-normalised excursions (engine-fire candidates) --")
        for g, st in sorted(d["excursions_1h_atr"].items()):
            print(f"  {g:22s} n={st['n']:4d} MFE_med={st['mfe_atr_median']:+.2f}ATR "
                  f"MAE_med={st['mae_atr_median']:+.2f}ATR term_med={st['term_atr_median']:+.2f}ATR "
                  f"ran1ATR={st['would_have_run_1atr']:.0%} stop1ATR={st['would_have_stopped_1atr']:.0%} "
                  f"chop={st['chop']:.0%}")


if __name__ == "__main__":
    main()
