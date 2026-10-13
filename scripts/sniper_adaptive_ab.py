#!/usr/bin/env python3
"""A/B the detector stack: legacy absolute thresholds vs adaptive z-scores.

Feeds the production log back through the *real* detectors twice — once with
``signal_stack.adaptive.enabled: false`` and once with ``true`` — and reports,
per detector, how many pulses it would fire on and how good those fires were.

Quality is the 60-minute forward excursion in the detector's own direction, in
ATR, minus the unconditional drift for that direction, and the significance is
computed on **independent episodes** (fires within an hour of each other are one
episode).  Without that correction a clustered detector looks far better than it
is — see docs/sniper_volatility_capture_20261014.md §4.

Caveats, stated because they bound what this can conclude:
  * ``trend_intensity`` and the volume-profile levels are not in the log, so
    ``boundary_test`` is not reproduced and ``volatility_surge``'s direction
    falls back to its CVD branch.
  * ~20 independent episodes over the whole window: this can show that a mode is
    *broken* (dead, or orders of magnitude louder) but not that it is *better*.

Read-only.
"""
from __future__ import annotations

import statistics
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.sniper_gate_core import load_replay_cfg  # noqa: E402
from scripts.sniper_gate_replay import DEFAULT_LOG, enrich, parse  # noqa: E402
from scripts.sniper_signal_latency import future_exc, segments, signed_exc  # noqa: E402
from src.sniper.trigger import SniperTrigger  # noqa: E402

BASE = datetime(2026, 9, 18, tzinfo=timezone.utc)
HORIZON_MIN = 60.0
DETECTORS = [
    ("cvd_momentum", "_detect_cvd_momentum"),
    ("cvd_divergence", "_detect_cvd_divergence"),
    ("cvd_absorption", "_detect_cvd_absorption"),
    ("large_trade", "_detect_large_trade"),
    ("volatility_surge", "_detect_volatility_surge"),
    ("positioning_extreme", "_detect_positioning_extreme"),
]


def _metrics(d: Dict[str, Any]) -> Dict[str, Any]:
    """Rebuild the slice of the scout payload the detectors read."""
    price = d.get("price", 0.0)
    atr = d.get("atr", 0.0)
    return {
        "sentiment_signals": {
            "cvd_intensity_ratio": d.get("cvd", 0.0),
            "avg_trade_size": d.get("avg_trade_size", 0.0),
            "trade_count": d.get("trade_count", 0),
            "ls_ratio_micro": d.get("ls", 1.0),
            "funding_rate": d.get("funding", 0.0),
            "oi_delta_micro": d.get("oi_delta", 0.0),
            "liquidation_clusters": {},
        },
        "price_dynamics": {
            "volatility_intensity_index": d.get("vii", 0.0),
            "current_price": price,
            "atr_macro": atr,
            "atr_micro": atr,
        },
        "market_regime": {
            "volume_participation_ratio": d.get("vpr", 0.0),
            "squeeze_factor": d.get("squeeze_factor") or 1.0,
            "trend_intensity": 0.0,
        },
        "volume_profile": {"vah": price, "val": price, "poc": price},
    }


def run(parsed, sym: str, adaptive: bool) -> Dict[str, List[Tuple[float, str, float]]]:
    """Return {detector: [(forward_excess, direction, mono), ...]}."""
    if adaptive:
        import src.sniper.trigger as trig
        real_init = trig.SniperTrigger.__init__

        def patched(self, *a, **kw):
            real_init(self, *a, **kw)
            self._adaptive_on = True
            self.sniper_cfg["signal_stack"]["adaptive"]["enabled"] = True

        trig.SniperTrigger.__init__ = patched
        try:
            t = SniperTrigger(symbol=sym)
        finally:
            trig.SniperTrigger.__init__ = real_init
    else:
        t = SniperTrigger(symbol=sym)

    pulses, mono = parsed["pulses"][sym], parsed["mono"][sym]
    seg = _seg_lookup(pulses, mono)
    out: Dict[str, List[Tuple[float, str, float]]] = {n: [] for n, _ in DETECTORS}
    prev_run = prev_mono = None
    prev_metrics: Optional[Dict[str, Any]] = None   # per segment; detectors need it
    for i, p in enumerate(pulses):
        h, m, s = (int(x) for x in p.t.split(".")[0].split(":"))
        m_sec = h * 3600 + m * 60 + s
        if p.run != prev_run or (prev_mono is not None and (m_sec - prev_mono) % 86400 > 360):
            t.reset_state()
            prev_metrics = None
        prev_run, prev_mono = p.run, m_sec
        now = BASE + timedelta(seconds=m_sec)
        cur = _metrics(p.diag)
        if not cur["price_dynamics"]["current_price"]:
            continue
        t._record_cvd_sample(cur, now)
        t._record_adaptive_samples(cur, now)
        for name, meth in DETECTORS:
            try:
                card = getattr(t, meth)(cur, prev_metrics, now)
            except Exception:
                card = None
            if card is None or card.direction.value == "NEUTRAL":
                continue
            if i not in seg:
                continue
            lo, hi = seg[i]
            fw = signed_exc(pulses, mono, i, hi, HORIZON_MIN, card.direction.value)
            if fw is not None:
                out[name].append((fw, card.direction.value, mono[i]))
        prev_metrics = cur
    return out


def _seg_lookup(pulses, mono) -> Dict[int, Tuple[int, int]]:
    """index -> (segment_lo, segment_hi); windows never cross a restart or gap."""
    out: Dict[int, Tuple[int, int]] = {}
    for lo, hi in segments(pulses, mono):
        for k in range(lo, hi):
            out[k] = (lo, hi)
    return out


def summarise(rows, total_pulses: int, tag: str) -> None:
    fires = len(rows)
    if not fires:
        print(f"  {tag:34s} fires=0")
        return
    episodes: List[List[Tuple[float, float]]] = []
    cur: List[Tuple[float, float]] = []
    for fw, _dir, m in rows:
        if cur and m - cur[-1][1] <= 3600:
            cur.append((fw, m))
        else:
            if cur:
                episodes.append(cur)
            cur = [(fw, m)]
    if cur:
        episodes.append(cur)
    ep_means = [statistics.fmean([x[0] for x in e]) for e in episodes]
    se = statistics.stdev(ep_means) / len(ep_means) ** 0.5 if len(ep_means) > 2 else None
    raw = statistics.fmean([r[0] for r in rows])
    line = (f"  {tag:34s} fires={fires:5d} ({100*fires/total_pulses:5.2f}%)  "
            f"episodes={len(ep_means):3d}  raw={raw:+.3f}  adj={statistics.fmean(ep_means):+.3f}")
    if se:
        line += f" ±{se:.3f} (t={statistics.fmean(ep_means)/se:+.2f})"
    print(line)


def collect_gate(parsed, sym: str, adaptive: bool):
    """Per-pulse (direction, same_dir_count, distinct_sources, forward_excess).

    Mirrors the gate's own definition of a same-direction signal: strength >=
    MIN_STACK_STRENGTH and direction equal to the pulse's dominant direction.
    Dominant direction is taken from the confluence engine so the count matches
    what the real gate would see.
    """
    from src.sniper.trigger import MIN_STACK_STRENGTH, ConfluenceEngine, Direction
    if adaptive:
        import src.sniper.trigger as trig
        real_init = trig.SniperTrigger.__init__

        def patched(self, *a, **kw):
            real_init(self, *a, **kw)
            self._adaptive_on = True
            self.sniper_cfg["signal_stack"]["adaptive"]["enabled"] = True

        trig.SniperTrigger.__init__ = patched
        try:
            t = SniperTrigger(symbol=sym)
        finally:
            trig.SniperTrigger.__init__ = real_init
    else:
        t = SniperTrigger(symbol=sym)

    pulses, mono = parsed["pulses"][sym], parsed["mono"][sym]
    seg = _seg_lookup(pulses, mono)
    rows = []
    prev_run = prev_mono = None
    prev_metrics = None
    for i, p in enumerate(pulses):
        h, m, sec = (int(x) for x in p.t.split(".")[0].split(":"))
        m_sec = h * 3600 + m * 60 + sec
        if p.run != prev_run or (prev_mono is not None and (m_sec - prev_mono) % 86400 > 360):
            t.reset_state(); prev_metrics = None
        prev_run, prev_mono = p.run, m_sec
        now = BASE + timedelta(seconds=m_sec)
        cur = _metrics(p.diag)
        if not cur["price_dynamics"]["current_price"] or i not in seg:
            continue
        t._record_cvd_sample(cur, now)
        t._record_adaptive_samples(cur, now)
        cards = []
        for _name, meth in DETECTORS:
            try:
                c = getattr(t, meth)(cur, prev_metrics, now)
            except Exception:
                c = None
            if c is not None:
                cards.append(c)
        prev_metrics = cur
        # decayed memory, as the real engine sees it
        alive = t.memory.ingest(cards, now)
        conf, dom, _should = t.engine.evaluate(alive, t._determine_regime(cur))
        dom = dom.value if hasattr(dom, "value") else str(dom)
        if dom == "NEUTRAL":
            continue
        same = [c for c in alive
                if getattr(c.direction, "value", c.direction) == dom
                and c.strength >= MIN_STACK_STRENGTH]
        srcs = {c.source for c in same}
        lo, hi = seg[i]
        fw = signed_exc(pulses, mono, i, hi, HORIZON_MIN, dom)
        if fw is None:
            continue
        rows.append((dom, len(same), len(srcs), fw, mono[i]))
    return rows


def gate_policy(rows, kind: str, k: int, min_gap_min: float = 0.0):
    """Filter rows by a gate policy, returning the surviving forward excesses."""
    keep = []
    last_ok = None
    for dom, n, srcs, fw, m in rows:
        ok = (n >= k) if kind == "count" else (srcs >= k)
        if ok:
            if min_gap_min and last_ok is not None and (m - last_ok) < min_gap_min * 60:
                continue
            keep.append((fw, m))
            last_ok = m
    return keep


def _report(keep, total, tag):
    if not keep:
        print(f"    {tag:28s} passes=0"); return
    eps = []; cur = []
    for fw, m in keep:
        if cur and m - cur[-1][1] <= 3600: cur.append((fw, m))
        else:
            if cur: eps.append(cur)
            cur = [(fw, m)]
    if cur: eps.append(cur)
    em = [statistics.fmean([x[0] for x in e]) for e in eps]
    se = statistics.stdev(em)/len(em)**0.5 if len(em) > 2 else None
    line = (f"    {tag:28s} passes={len(keep):4d} episodes={len(em):3d} "
            f"adj={statistics.fmean(em):+.3f}")
    if se: line += f" ±{se:.3f} (t={statistics.fmean(em)/se:+.2f})"
    print(line)


def main() -> None:
    parsed = parse(DEFAULT_LOG)
    enrich(parsed, load_replay_cfg())
    print("\n\n########## GATE POLICY COMPARISON ##########")
    for sym in ("XAUTUSDT", "BTCUSDT"):
        print(f"\n===== {sym}")
        for adaptive in (False, True):
            mode = "adaptive" if adaptive else "legacy"
            rows = collect_gate(parsed, sym, adaptive)
            print(f"  --- {mode}  (comparable pulses={len(rows)})")
            _report(gate_policy(rows, "count", 3), len(rows), "count>=3 (current)")
            _report(gate_policy(rows, "count", 2), len(rows), "count>=2")
            _report(gate_policy(rows, "source", 2), len(rows), "sources>=2")
            _report(gate_policy(rows, "count", 2, 30), len(rows), "count>=2 + 30min gap")
            _report(gate_policy(rows, "source", 2, 30), len(rows), "sources>=2 + 30min gap")

    for sym in ("XAUTUSDT", "BTCUSDT"):
        n = len(parsed["pulses"][sym])
        print(f"\n===== {sym}  ({n} pulses)")
        for adaptive in (False, True):
            mode = "ADAPTIVE (z-score)" if adaptive else "LEGACY (absolute)"
            print(f"  --- {mode}")
            res = run(parsed, sym, adaptive)
            for name, _ in DETECTORS:
                summarise(res[name], n, name)


if __name__ == "__main__":
    main()
