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
from scripts.sniper_stack_probe import (BASE, DETECTORS,  # noqa: E402
                                        iter_symbol, pulse_time,
                                        metrics_from_diag)
from src.sniper.trigger import SniperTrigger  # noqa: E402


def fingerprint(symbols=("XAUTUSDT", "BTCUSDT")) -> Dict[str, Any]:
    parsed = parse(DEFAULT_LOG)
    out: Dict[str, Any] = {}
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
    print(json.dumps(fingerprint(), indent=1, sort_keys=True))
