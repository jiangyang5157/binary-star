#!/usr/bin/env python3
"""Validate candidate threshold recalibrations BEFORE changing any config.

For each proposed change we take the pulses that would *newly* fire and measure
their forward excursion on the daemon's own 2-minute grid, then subtract the
unconditional drift for the same direction (the "go-long-anyway" baseline).  A
change only earns its place if the excess is non-negative.

Read-only: nothing here is imported by production code.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.sniper_gate_replay import DEFAULT_LOG, enrich, parse  # noqa: E402
from scripts.sniper_signal_latency import (  # noqa: E402
    future_exc, segments, signed_exc,
)

HORIZON_MIN = 60.0


def _diag(p) -> Dict[str, Any]:
    return p.diag


def _float(d, k, default=None):
    v = d.get(k)
    return default if v is None else v


def collect(parsed, sym, predicate):
    """Indices where `predicate(pulse, prev_pulse)` holds (segment-safe)."""
    pulses, mono = parsed["pulses"][sym], parsed["mono"][sym]
    hits: List[Tuple[int, str]] = []
    for lo, hi in segments(pulses, mono):
        for i in range(lo, hi):
            direction = predicate(pulses[i], pulses[i - 1] if i > lo else None)
            if direction:
                hits.append((i, direction))
    return hits


def evaluate(parsed, sym, hits, tag):
    pulses, mono = parsed["pulses"][sym], parsed["mono"][sym]
    seg_of = {}
    for lo, hi in segments(pulses, mono):
        for i in range(lo, hi):
            seg_of[i] = (lo, hi)

    def horizon(i, direction):
        lo, hi = seg_of[i]
        fx = future_exc(pulses, mono, i, hi, HORIZON_MIN, direction)
        fw = signed_exc(pulses, mono, i, hi, HORIZON_MIN, direction)
        return fx, fw

    mfe, mae, fwd = [], [], []
    for i, d in hits:
        fx, fw = horizon(i, d)
        if fx and fw is not None:
            mfe.append(fx[0]); mae.append(fx[1]); fwd.append(fw)

    # baseline: every pulse in the same segments, same direction
    base = []
    for lo, hi in segments(pulses, mono):
        for i in range(lo, hi):
            for d in ("BULLISH", "BEARISH"):
                fw = signed_exc(pulses, mono, i, hi, HORIZON_MIN, d)
                if fw is not None:
                    base.append((d, fw))
    from statistics import fmean
    import statistics as st
    res = {}
    if fwd:
        b = fmean([f for d, f in base if any(d == dd for _, dd in hits)]) if base else 0.0
        res = {
            "n": len(fwd),
            "mfe": round(fmean(mfe), 2),
            "mae": round(fmean(mae), 2),
            "fwd": round(fmean(fwd), 3),
            "baseline": round(b, 3),
            "excess": round(fmean(fwd) - b, 3),
            "se": round(st.stdev(fwd) / len(fwd) ** 0.5, 3) if len(fwd) > 1 else None,
        }
    print(f"  {tag:38s} n={res.get('n', 0):5d}  mfe={res.get('mfe')}  mae={res.get('mae')}  "
          f"fwd={res.get('fwd')}  baseline={res.get('baseline')}  "
          f"excess={res.get('excess')}  se={res.get('se')}")
    return res


def main() -> None:
    parsed = parse(DEFAULT_LOG)
    enrich(parsed, load_replay_cfg_safe())
    print("候选改动的质量验证（60 分钟、ATR、已去同向基线漂移）\n")

    for sym in ("XAUTUSDT", "BTCUSDT"):
        print(f"===== {sym}")
        ls_limit = 1.05 if sym == "XAUTUSDT" else 1.60
        fund_thr = 0.0005

        # P1a: positioning_extreme long/short ratio extreme (BEARISH when long-heavy)
        evaluate(parsed, sym, collect(parsed, sym,
                 lambda p, q: "BEARISH" if _float(_diag(p), "ls", 0) > ls_limit else None),
                 f"pos_ext P1a  ls>{ls_limit} (现状 1.5/2.0 → 0 次)")

        # P1a at the CURRENT threshold, as a control (expected: 0 hits)
        evaluate(parsed, sym, collect(parsed, sym,
                 lambda p, q: "BEARISH" if _float(_diag(p), "ls", 0) > (1.5 if sym == "XAUTUSDT" else 2.0) else None),
                 "  [对照] 现状阈值")

        # P2: funding extreme (BULLISH when funding negative, BEARISH when positive)
        evaluate(parsed, sym, collect(parsed, sym,
                 lambda p, q: ("BEARISH" if _float(_diag(p), "funding", 0) > fund_thr
                               else "BULLISH" if _float(_diag(p), "funding", 0) < -fund_thr else None)),
                 f"pos_ext P2   |fund|>{fund_thr} (期望 0 次)")

        # vol_surge: joint condition WITHOUT the growth gate
        def vs_no_growth(p, q):
            vii = _float(_diag(p), "vii", 0); vpr = _float(_diag(p), "vpr", 0)
            if not (vii > 1.25 and vpr > 1.5):
                return None
            cvd = _float(_diag(p), "cvd", 0.0)
            if abs(cvd) > 0.05:
                return "BULLISH" if cvd > 0 else "BEARISH"
            return None  # NEUTRAL contributes nothing to confluence
        evaluate(parsed, sym, collect(parsed, sym, vs_no_growth),
                 "vol_surge 去掉增长条件 (vii>1.25 & vpr>1.5)")

        # vol_surge WITH the growth gate (current behaviour, control)
        def vs_growth(p, q):
            d = vs_no_growth(p, q)
            if not d or q is None:
                return None
            vp = _float(_diag(q), "vii", 0)
            return d if _float(_diag(p), "vii", 0) > vp * 1.03 else None
        evaluate(parsed, sym, collect(parsed, sym, vs_growth),
                 "  [对照] 现状（含增长条件）")
        print()

    # P3: OI divergence (currently the only live path for BTC)
    for sym in ("XAUTUSDT", "BTCUSDT"):
        def oi_div(p, q):
            if q is None:
                return None
            oi = _float(_diag(p), "oi_delta", 0.0)
            dprice = _float(_diag(p), "price", 0) - _float(_diag(q), "price", 0)
            if abs(oi) <= 0.01 or dprice == 0:
                return None
            if (oi > 0 > dprice) or (oi < 0 < dprice):
                return "BEARISH" if dprice > 0 else "BULLISH"
            return None
        evaluate(parsed, sym, collect(parsed, sym, oi_div), "pos_ext P3  OI 背离 (现状活跃路径)")


def load_replay_cfg_safe():
    from scripts.sniper_gate_core import load_replay_cfg
    return load_replay_cfg()


if __name__ == "__main__":
    main()
