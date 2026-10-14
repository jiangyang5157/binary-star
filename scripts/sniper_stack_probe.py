#!/usr/bin/env python3
"""Shared plumbing for offline detector analysis.

Lives here rather than inside one analysis script so that unrelated tools can
depend on it without depending on each other — the legacy fingerprint used to
import from the adaptive A/B harness, which meant retiring that harness would
have broken a tool that had nothing to do with adaptive thresholds.

`run_detectors` drives the *real* detector methods over metrics rebuilt from the
production log's SIGNAL DIAG line, so offline results reflect the shipped code
rather than a re-implementation of it.

Read-only.
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.sniper.trigger import SniperTrigger  # noqa: E402

# The six detectors that can be reconstructed from the log.  squeeze is NEUTRAL,
# boundary_test needs volume-profile levels the log does not carry, and
# liquidation_hunt needs clusters, so none of the three can be replayed.
DETECTORS = [
    ("cvd_momentum", "_detect_cvd_momentum"),
    ("cvd_divergence", "_detect_cvd_divergence"),
    ("cvd_absorption", "_detect_cvd_absorption"),
    ("large_trade", "_detect_large_trade"),
    ("volatility_surge", "_detect_volatility_surge"),
    ("positioning_extreme", "_detect_positioning_extreme"),
]

BASE = datetime(2026, 9, 18, tzinfo=timezone.utc)


def metrics_from_diag(d: Dict[str, Any]) -> Dict[str, Any]:
    """Rebuild the slice of the scout payload the detectors read.

    Field names differ from the detector vocabulary: the log writes `vol_surge`,
    `liq_hunt`, `pos_ext`, and `ls`/`oi_d` for ls_ratio_micro/oi_delta_micro.
    """
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


def pulse_time(pulse) -> datetime:
    h, m, sec = (int(x) for x in pulse.t.split(".")[0].split(":"))
    return BASE + timedelta(seconds=h * 3600 + m * 60 + sec)


def pulse_seconds(pulse) -> int:
    h, m, sec = (int(x) for x in pulse.t.split(".")[0].split(":"))
    return h * 3600 + m * 60 + sec


def iter_symbol(parsed, sym: str, trigger: Optional[SniperTrigger] = None):
    """Yield (index, pulse, metrics, prev_metrics) with state resets honoured.

    A daemon restart or a >6-minute gap resets detector state, so the replay must
    do the same or the cvd_divergence reference and the trade-size window will
    span a gap that production never spanned.
    """
    trigger = trigger or SniperTrigger(symbol=sym)
    pulses = parsed["pulses"][sym]
    prev_metrics = None
    prev_run = prev_mono = None
    for i, pulse in enumerate(pulses):
        mono = pulse_seconds(pulse)
        if pulse.run != prev_run or (prev_mono is not None and (mono - prev_mono) % 86400 > 360):
            trigger.reset_state()
            prev_metrics = None
        prev_run, prev_mono = pulse.run, mono
        cur = metrics_from_diag(pulse.diag)
        if not cur["price_dynamics"]["current_price"]:
            continue
        # Same step 0b as evaluate(): cvd_divergence compares against the sample
        # one micro candle ago, so omitting this silently zeroes that detector.
        trigger._record_cvd_sample(cur, pulse_time(pulse))
        yield i, pulse, cur, prev_metrics
        prev_metrics = cur


def run_detectors(trigger: SniperTrigger, cur, prev, now) -> List[Any]:
    """Every detector's verdict for one pulse, exceptions swallowed per detector."""
    cards = []
    for _name, method in DETECTORS:
        try:
            card = getattr(trigger, method)(cur, prev, now)
        except Exception:
            card = None
        if card is not None:
            cards.append(card)
    return cards
