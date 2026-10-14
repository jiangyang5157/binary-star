#!/usr/bin/env python3
"""Fingerprint the detector stack in legacy (non-adaptive) mode.

Purpose: prove that a change did not disturb the *default* behaviour.  The
detector layer has an `adaptive.enabled` switch whose whole promise is that
`false` means "exactly as before" — a promise that is easy to make and, as this
session showed, easy to break by accident (replacing two saturation constants
while converting a branch shifted legacy strengths by 1.5x and no unit test
noticed).

Run it before and after a change:

    python3 scripts/sniper_legacy_fingerprint.py > /tmp/before.json
    ...edit...
    python3 scripts/sniper_legacy_fingerprint.py > /tmp/after.json
    diff /tmp/before.json /tmp/after.json     # empty == untouched

It fingerprints *counts and summed strengths*, not just counts, because a
strength-only change still moves confluence and therefore the gate.

The output begins with an `_input` block (log path, line count, pulses per
symbol).  The daemon appends to this log while running, so a comparison made
across time will show higher counts that look like a behaviour change but are
just a bigger denominator — always check `_input` first, or freeze the log with
`--log` and compare two code versions against one snapshot.

Read-only.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.sniper_gate_replay import DEFAULT_LOG, parse  # noqa: E402
from scripts.sniper_stack_probe import (DETECTORS, iter_symbol,  # noqa: E402
                                        pulse_time)
from src.sniper.trigger import SniperTrigger  # noqa: E402


def fingerprint(symbols=("XAUTUSDT", "BTCUSDT"),
                log_path: str = DEFAULT_LOG) -> Dict[str, Any]:
    log_path = Path(log_path)
    parsed = parse(log_path)
    # Record the input, because the daemon appends to this log while it runs.
    # Without the denominator a comparison across time shows higher counts and
    # looks exactly like a behaviour change — that false alarm is easy to raise
    # and, worse, easy to dismiss.  With it, a diff says which it is.
    out: Dict[str, Any] = {
        "_input": {
            "log": str(log_path),
            "lines": len(log_path.read_text(errors="ignore").splitlines()),
            "pulses": {sym: len(parsed["pulses"][sym]) for sym in symbols},
        }
    }
    for sym in symbols:
        trigger = SniperTrigger(symbol=sym)
        agg = {name: [0, 0.0] for name, _ in DETECTORS}
        for _i, pulse, cur, prev in iter_symbol(parsed, sym, trigger):
            now = pulse_time(pulse)
            for name, meth in DETECTORS:
                try:
                    card = getattr(trigger, meth)(cur, prev, now)
                except Exception:
                    card = None
                if card is not None:
                    agg[name][0] += 1
                    agg[name][1] += card.strength
        out[sym] = {n: [v[0], round(v[1], 3)] for n, v in agg.items()}
    return out


if __name__ == "__main__":
    # Pass a frozen copy of the log for a comparison that spans time, e.g.
    #   cp data/prod/sniper.log /tmp/frozen.log
    #   python3 scripts/sniper_legacy_fingerprint.py --log /tmp/frozen.log
    log_path = DEFAULT_LOG
    if "--log" in sys.argv:
        log_path = sys.argv[sys.argv.index("--log") + 1]
    # sort_keys=False so the _input block stays first: it is what tells you
    # whether a difference is a behaviour change or just a longer log.
    print(json.dumps(fingerprint(log_path=log_path), indent=1))
