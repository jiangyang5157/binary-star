#!/usr/bin/env python3
"""Compare gate policies over the production log — the evidence for the
source-breadth gate.

Answers one question offline: *if breadth were measured by independent
information source instead of by detector count, which pulses would wake and how
good would they have been?*  It drives the real `SniperTrigger` (real detectors,
real decayed memory, real confluence), so the answer is about the shipped code
rather than a re-implementation.

Why offline and not a "shadow mode" in production: the diagnostic line already
reports `sources=N[...]` every pulse using the same helper, list and dominant
direction as the gate, so the gate's verdict is derivable from a log that is
written anyway.  A second in-production channel recorded the same thing twice.

Quality is the 60-minute forward excursion in the pulse's own direction minus
the unconditional drift for that direction, in ATR.  Significance is computed on
**independent episodes** (entries within an hour collapse into one), because a
clustered signal looks far better than it is — see
docs/sniper_volatility_capture_20261014.md §4.

Read-only.
"""
from __future__ import annotations

import statistics
import sys
from pathlib import Path
from typing import Dict, List, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.sniper_gate_core import load_replay_cfg  # noqa: E402
from scripts.sniper_gate_replay import DEFAULT_LOG, enrich, parse  # noqa: E402
from scripts.sniper_signal_latency import segments, signed_exc  # noqa: E402
from scripts.sniper_stack_probe import (DETECTORS, iter_symbol,  # noqa: E402
                                        pulse_time, run_detectors)
from src.sniper.trigger import MIN_STACK_STRENGTH, SniperTrigger  # noqa: E402

HORIZON_MIN = 60.0


def segment_lookup(pulses, mono) -> Dict[int, Tuple[int, int]]:
    """index -> (segment_lo, segment_hi); windows never cross a restart or gap."""
    out: Dict[int, Tuple[int, int]] = {}
    for lo, hi in segments(pulses, mono):
        for k in range(lo, hi):
            out[k] = (lo, hi)
    return out


def fire_rates(parsed, sym: str) -> None:
    """Per detector: fire count and cluster-corrected forward edge."""
    trigger = SniperTrigger(symbol=sym)
    pulses, mono = parsed["pulses"][sym], parsed["mono"][sym]
    seg = segment_lookup(pulses, mono)
    hits: Dict[str, List[Tuple[float, float]]] = {n: [] for n, _ in DETECTORS}
    total = 0
    for i, pulse, cur, prev in iter_symbol(parsed, sym, trigger):
        total += 1
        now = pulse_time(pulse)
        for card in run_detectors(trigger, cur, prev, now):
            if card.direction.value == "NEUTRAL" or i not in seg:
                continue
            lo, hi = seg[i]
            fw = signed_exc(pulses, mono, i, hi, HORIZON_MIN, card.direction.value)
            if fw is not None:
                hits[card.sub_type].append((fw, mono[i]))
    for name, _ in DETECTORS:
        rows = hits[name]
        if not rows:
            print(f"    {name:22s} fires=0")
            continue
        eps: List[List[float]] = []
        cur_ep: List[Tuple[float, float]] = []
        for fw, m in rows:
            if cur_ep and m - cur_ep[-1][1] <= 3600:
                cur_ep.append((fw, m))
            else:
                if cur_ep:
                    eps.append([x[0] for x in cur_ep])
                cur_ep = [(fw, m)]
        if cur_ep:
            eps.append([x[0] for x in cur_ep])
        means = [statistics.fmean(e) for e in eps]
        se = statistics.stdev(means) / len(means) ** 0.5 if len(means) > 2 else None
        line = (f"    {name:22s} fires={len(rows):5d} ({100*len(rows)/total:5.2f}%)  "
                f"episodes={len(means):3d}  raw={statistics.fmean([r[0] for r in rows]):+.3f}"
                f"  adj={statistics.fmean(means):+.3f}")
        if se:
            line += f" ±{se:.3f} (t={statistics.fmean(means)/se:+.2f})"
        print(line)


def collect(parsed, sym: str) -> List[Tuple[str, int, int, float, float]]:
    """Per pulse: (dominant direction, same-dir count, source count, excess, mono)."""
    trigger = SniperTrigger(symbol=sym)
    pulses, mono = parsed["pulses"][sym], parsed["mono"][sym]
    seg = segment_lookup(pulses, mono)
    rows = []
    for i, pulse, cur, prev in iter_symbol(parsed, sym, trigger):
        if i not in seg:
            continue
        now = pulse_time(pulse)
        cards = run_detectors(trigger, cur, prev, now)
        alive = trigger.memory.ingest(cards, now)
        _conf, dominant, _should = trigger.engine.evaluate(
            alive, trigger._determine_regime(cur))
        dom = dominant.value if hasattr(dominant, "value") else str(dominant)
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


def policy(rows, kind: str, k: int) -> List[Tuple[float, float]]:
    return [(fw, m) for _dom, n, srcs, fw, m in rows
            if (n >= k if kind == "count" else srcs >= k)]


def report(rows: List[Tuple[float, float]], tag: str) -> None:
    if not rows:
        print(f"    {tag:24s} passes=0")
        return
    eps: List[List[float]] = []
    cur: List[Tuple[float, float]] = []
    for fw, m in rows:
        if cur and m - cur[-1][1] <= 3600:
            cur.append((fw, m))
        else:
            if cur:
                eps.append([x[0] for x in cur])
            cur = [(fw, m)]
    if cur:
        eps.append([x[0] for x in cur])
    means = [statistics.fmean(e) for e in eps]
    se = statistics.stdev(means) / len(means) ** 0.5 if len(means) > 2 else None
    line = f"    {tag:24s} passes={len(rows):4d} episodes={len(means):3d} adj={statistics.fmean(means):+.3f}"
    if se:
        line += f" ±{se:.3f} (t={statistics.fmean(means)/se:+.2f})"
    print(line)


def main() -> None:
    parsed = parse(DEFAULT_LOG)
    enrich(parsed, load_replay_cfg())
    for sym in ("XAUTUSDT", "BTCUSDT"):
        print(f"\n===== {sym}  ({len(parsed['pulses'][sym])} pulses)")
        print("  --- detector fire rates")
        fire_rates(parsed, sym)
        print("  --- gate policies")
        rows = collect(parsed, sym)
        report(policy(rows, "count", 3), "count>=3  (current)")
        report(policy(rows, "count", 2), "count>=2")
        report(policy(rows, "source", 2), "sources>=2  (proposed)")


if __name__ == "__main__":
    main()
