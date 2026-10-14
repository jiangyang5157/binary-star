#!/usr/bin/env python3
"""Shared library for sniper-gate log analysis.

Responsibilities (all *deterministic reconstruction*, no decision logic):

  * parse ``data/prod/sniper.log`` into per-pulse detector state
  * rebuild the 9 detector SignalCards (directions included)
  * replay SignalMemory decay + ConfluenceEngine scoring
  * load the effective gate/threshold config per symbol

Deliberately contains **no timeline / cooldown replay**: that lives in
``sniper_gate_replay.py``, which anchors every event by file order because a run
can span several days (time-of-day is not monotonic).
"""

from __future__ import annotations
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
