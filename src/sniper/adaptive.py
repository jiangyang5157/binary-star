"""Scale-free detector thresholds.

Why this exists
---------------
Detector conditions used to be absolute constants, hand-tuned per symbol:
``ls > 1.5`` (BTC 2.0), ``|funding| > 0.0005``, ``|oi_delta| > 0.02``,
``|cvd| > 0.24``, ``|dCVD| > 0.35``.  Two things went wrong with that.

**They silently died.**  Measured over 2026-09-18 → 10-14 (7281 pulses/symbol),
XAUT's ``ls`` never exceeded 1.07 and BTC's never exceeded 1.72 while their
thresholds were 1.5 / 2.0; ``|funding|`` never exceeded 0.0001 against a 0.0005
threshold.  Three of ``positioning_extreme``'s five trigger paths could not fire
— not rarely, *never* — and nothing reported it.  A detector that is declared
but unreachable is worse than a missing one, because it looks like coverage.

**They do not transfer.**  BTC's ``ls`` distribution is far narrower than
XAUT's, so the same constant means different things; the historical fix was
another per-symbol number (0.25 → 0.08, 0.18 → 0.12, …).  Each one is a
calibration debt that no test can catch.

A robust z-score against the symbol's own recent distribution fixes both: the
condition is reachable by construction, one constant serves every symbol, and it
follows the instrument when its volatility regime shifts.

Median/MAD rather than mean/stdev because these metrics are fat-tailed — the
whole point is to detect extremes, and an extreme must not be able to move its
own threshold.  For the same reason ``score()`` evaluates the value against the
window *before* folding it in.

Windows are expressed in **minutes**, not pulse counts, so that changing the
pulse interval cannot silently leave a window too short to ever fill (that bug
class already bit the cvd_divergence history buffer).
"""
from __future__ import annotations

import math
from collections import deque
from datetime import datetime, timedelta
from typing import Deque, Iterable, Optional, Tuple

# MAD → σ for a normal distribution.  Without it a z-score would read ~0.67x
# too small, which only matters for interpreting the configured k, but there is
# no reason to carry a non-standard scale.
MAD_TO_SIGMA = 1.4826


class RobustWindow:
    """Rolling median/MAD over a time window, for scale-free thresholds.

    ``score(value, now)`` returns the robust z of ``value`` against the window
    as it stood *before* this value was added, then folds the value in.  Use
    that rather than calling ``z()`` and ``update()`` separately.

    Before ``min_samples`` are available the window is not ``ready`` and every
    score is 0.0 — callers compare ``abs(z) > k``, so a detector is simply dark
    during warm-up rather than firing on an unstable baseline.
    """

    def __init__(self, window_minutes: float, min_samples: int):
        if not (window_minutes > 0):
            raise ValueError("window_minutes must be positive")
        if min_samples < 1:
            raise ValueError("min_samples must be >= 1")
        self.window_minutes = float(window_minutes)
        self.min_samples = int(min_samples)
        self._samples: Deque[Tuple[datetime, float]] = deque()

    # ── ingestion ──────────────────────────────────────────────────────────

    def update(self, value: Optional[float], now: datetime) -> None:
        """Fold a sample in, dropping anything older than the window."""
        if value is None:
            return
        value = float(value)
        if not math.isfinite(value):
            return
        self._samples.append((now, value))
        self._prune(now)

    def score(self, value: Optional[float], now: datetime) -> float:
        """Robust z of ``value`` against the prior window, then fold it in."""
        z = self.z(value)
        self.update(value, now)
        return z

    def _prune(self, now: datetime) -> None:
        cutoff = now - timedelta(minutes=self.window_minutes)
        while self._samples and self._samples[0][0] < cutoff:
            self._samples.popleft()

    def clear(self) -> None:
        self._samples.clear()

    # ── statistics ─────────────────────────────────────────────────────────

    @property
    def ready(self) -> bool:
        return len(self._samples) >= self.min_samples

    @property
    def count(self) -> int:
        return len(self._samples)

    def median(self) -> float:
        values = sorted(v for _, v in self._samples)
        if not values:
            return 0.0
        mid = len(values) // 2
        if len(values) % 2:
            return values[mid]
        return 0.5 * (values[mid - 1] + values[mid])

    def scale(self) -> float:
        """Robust σ estimate (1.4826 × MAD)."""
        if len(self._samples) < 2:
            return 0.0
        med = self.median()
        deviations = sorted(abs(v - med) for _, v in self._samples)
        mid = len(deviations) // 2
        mad = (deviations[mid] if len(deviations) % 2
               else 0.5 * (deviations[mid - 1] + deviations[mid]))
        return MAD_TO_SIGMA * mad

    def z(self, value: Optional[float]) -> float:
        """Robust z, or 0.0 when not ready / no dispersion.

        Returning 0.0 for a zero-width window is deliberate: if the metric has
        been perfectly constant there is nothing to be an outlier of, and 0.0
        keeps the caller's ``abs(z) > k`` false instead of dividing by zero.
        """
        if value is None or not self.ready:
            return 0.0
        value = float(value)
        if not math.isfinite(value):
            return 0.0
        scale = self.scale()
        if scale <= 0:
            return 0.0
        return (value - self.median()) / scale


class RobustWindows:
    """A named set of :class:`RobustWindow` sharing one window/min_samples."""

    def __init__(self, window_minutes: float, min_samples: int,
                 names: Iterable[str] = ()):
        self.window_minutes = float(window_minutes)
        self.min_samples = int(min_samples)
        self._windows = {n: RobustWindow(window_minutes, min_samples) for n in names}

    def window(self, name: str) -> RobustWindow:
        win = self._windows.get(name)
        if win is None:
            win = RobustWindow(self.window_minutes, self.min_samples)
            self._windows[name] = win
        return win

    def update(self, name: str, value: Optional[float], now: datetime) -> None:
        """Fold a sample into one named window."""
        self.window(name).update(value, now)

    def score(self, name: str, value: Optional[float], now: datetime) -> float:
        return self.window(name).score(value, now)

    def z(self, name: str, value: Optional[float]) -> float:
        return self.window(name).z(value)

    def ready(self, name: str) -> bool:
        return self.window(name).ready

    def clear(self) -> None:
        for win in self._windows.values():
            win.clear()
