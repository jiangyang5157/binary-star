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

Read-only.  Note: it calls `_record_adaptive_samples` defensively so it can also
be run against a checkout that predates the adaptive layer.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.sniper_adaptive_ab import DETECTORS, _metrics  # noqa: E402
from scripts.sniper_gate_replay import DEFAULT_LOG, parse  # noqa: E402
from src.sniper.trigger import SniperTrigger  # noqa: E402

BASE = datetime(2026, 9, 18, tzinfo=timezone.utc)


def fingerprint(symbols=("XAUTUSDT", "BTCUSDT")) -> Dict[str, Any]:
    parsed = parse(DEFAULT_LOG)
    out: Dict[str, Any] = {}
    for sym in symbols:
        trigger = SniperTrigger(symbol=sym)
        record = getattr(trigger, "_record_adaptive_samples", None)
        pulses = parsed["pulses"][sym]
        agg = {name: [0, 0.0] for name, _ in DETECTORS}
        prev_run = prev_mono = None
        prev = None
        for pulse in pulses:
            h, m, sec = (int(x) for x in pulse.t.split(".")[0].split(":"))
            mono = h * 3600 + m * 60 + sec
            if pulse.run != prev_run or (prev_mono is not None
                                         and (mono - prev_mono) % 86400 > 360):
                trigger.reset_state()
                prev = None
            prev_run, prev_mono = pulse.run, mono
            now = BASE + timedelta(seconds=mono)
            cur = _metrics(pulse.diag)
            if not cur["price_dynamics"]["current_price"]:
                continue
            trigger._record_cvd_sample(cur, now)
            if record:
                record(cur, now)
            for name, meth in DETECTORS:
                try:
                    card = getattr(trigger, meth)(cur, prev, now)
                except Exception:
                    card = None
                if card is not None:
                    agg[name][0] += 1
                    agg[name][1] += card.strength
            prev = cur
        out[sym] = {n: [v[0], round(v[1], 3)] for n, v in agg.items()}
    return out


if __name__ == "__main__":
    print(json.dumps(fingerprint(), indent=1, sort_keys=True))
