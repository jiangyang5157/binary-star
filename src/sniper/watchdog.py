"""
Pulse watchdog — turns a *silently frozen* daemon into a *loudly stopped* one.

Why this exists
---------------
The sniper's main loop is a single thread doing blocking network work.  When the
host suspends (laptop lid closed, power loss) the process is frozen; on resume a
socket can be left half-open and the loop may never return.  A hung daemon is
the worst outcome: it manages nothing **and** it still reports itself as running,
so nothing tells you it is gone (a stopped daemon still showing
"Connected · 126m" is exactly how this was discovered).

This watchdog watches a heartbeat that the pulse loop stamps every iteration
(and the session progress callback stamps during AI sessions).  If the beat goes
stale it exits the process immediately with ``os._exit(1)`` — deliberately
skipping cleanup, because the whole point is that the process is not making
progress.

Operational contract — read before relying on this
--------------------------------------------------
Exiting is all this can do; it cannot restart itself.  Whether the daemon comes
back is entirely up to how you launched it:

  * under a supervisor (systemd, supervisord, a ``while true`` shell wrapper,
    docker ``restart:``, …) it comes back on its own;
  * started by hand in a terminal it **stays down** until you start it again.

That trade is deliberate: "stopped and visible" beats "hung and invisible" even
when nothing restarts it.  Use a supervisor if you want self-healing.

Sizing (deliberately conservative — a false kill mid-session is worse than a
few extra minutes of detection latency):
  * measured over ~42 h of production log (2026-09-22 → 09-23), the longest
    legitimate silence inside the loop was **147 s**;
  * every blocking network call on the session path is now bounded — Binance
    REST 30 s, LLM 180 s (``llm.api_timeout_seconds``), SMTP 30 s — and the
    progress callback fires immediately before *and* after each LLM call, so
    the watched interval is one call, not one whole session;
so the worst legitimate beat gap is ~210 s and the 15-minute default keeps a
~4x margin.  Detection latency is deliberately traded for safety: the failure
this guards against ran for *hours*, so restarting at 15 min instead of 10
costs nothing, while a false kill mid-session is expensive.
"""
from __future__ import annotations

import os
import threading
import time
from typing import Callable, Optional

from src.utils.logger_utils import setup_logger

logger = setup_logger(__name__)

DEFAULT_TIMEOUT_SECONDS = 15 * 60
DEFAULT_CHECK_INTERVAL_SECONDS = 30.0


def timeout_seconds_from_minutes(value: object,
                                 default_seconds: float = DEFAULT_TIMEOUT_SECONDS) -> float:
    """Validate a configured watchdog timeout (minutes) and return seconds.

    A mistyped config value must never crash startup (``PulseWatchdog`` rejects
    non-positive timeouts), so anything unusable falls back to the default with
    an error log instead of propagating.
    """
    try:
        minutes = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        logger.error(
            f"invalid watchdog_timeout_minutes={value!r} | falling back to {default_seconds / 60:.0f}m"
        )
        return float(default_seconds)
    if minutes <= 0:
        logger.error(
            f"non-positive watchdog_timeout_minutes={minutes} | falling back to {default_seconds / 60:.0f}m"
        )
        return float(default_seconds)
    return minutes * 60.0


class PulseWatchdog:
    """Exit the process when the pulse loop stops beating.

    Args:
        timeout_seconds: how long the beat may go stale before firing.
        check_interval_seconds: how often to test (defaults to timeout/4, 1–30s).
        on_timeout: called with the stale duration instead of exiting the process
            (injected in tests).
        before_exit: optional hook run just before the hard exit — used to mark
            the state file stopped, since ``os._exit`` skips the normal shutdown
            path and a dead process that still claims ``running: true`` makes the
            dashboard lie.
        name: thread name, for logs and debugging.
    """

    def __init__(
        self,
        timeout_seconds: float,
        *,
        check_interval_seconds: Optional[float] = None,
        on_timeout: Optional[Callable[[float], None]] = None,
        before_exit: Optional[Callable[[], None]] = None,
        name: str = "pulse-watchdog",
    ):
        if timeout_seconds <= 0:
            raise ValueError(f"timeout_seconds must be > 0, got {timeout_seconds}")
        self.timeout_seconds = float(timeout_seconds)
        self.check_interval_seconds = float(
            check_interval_seconds
            if check_interval_seconds is not None
            else min(DEFAULT_CHECK_INTERVAL_SECONDS, max(1.0, self.timeout_seconds / 4))
        )
        self._on_timeout = on_timeout or self._exit_process
        self._before_exit = before_exit
        self._name = name
        self._last_beat = time.monotonic()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    # ── heartbeat ──────────────────────────────────────────────────────────

    def beat(self) -> None:
        """Stamp the heartbeat. Safe to call from any thread."""
        self._last_beat = time.monotonic()

    def stale_seconds(self) -> float:
        return time.monotonic() - self._last_beat

    def is_stale(self) -> bool:
        return self.stale_seconds() > self.timeout_seconds

    # ── lifecycle ──────────────────────────────────────────────────────────

    def start(self) -> "PulseWatchdog":
        if self._thread is not None:
            return self
        self._thread = threading.Thread(target=self._run, name=self._name, daemon=True)
        self._thread.start()
        logger.info(
            f"watchdog armed | timeout={self.timeout_seconds / 60:.1f}m "
            f"| check_interval={self.check_interval_seconds:.1f}s"
        )
        return self

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        while not self._stop.wait(self.check_interval_seconds):
            if self.is_stale():
                stale = self.stale_seconds()
                self._on_timeout(stale)
                return

    # ── default action ─────────────────────────────────────────────────────

    def _exit_process(self, stale_seconds: float) -> None:
        logger.critical(
            f"WATCHDOG TRIPPED | no pulse for {stale_seconds / 60:.1f}m "
            f"(limit {self.timeout_seconds / 60:.0f}m) — hard-exiting so the supervisor "
            f"can restart from a clean state; positions keep their exchange-side TP/SL"
        )
        # Mark the daemon stopped first: os._exit skips the normal shutdown path,
        # and a dead process that still reads "running: true" misleads the
        # dashboard and the singleton guard.
        if self._before_exit is not None:
            try:
                self._before_exit()
            except Exception as e:
                logger.error(f"watchdog before_exit hook failed | error={e}")
        try:
            import logging
            for h in list(logging.getLogger().handlers) + list(logger.handlers):
                h.flush()
        except Exception:
            pass
        # os._exit, not sys.exit: this runs on a worker thread, where sys.exit
        # would only end the thread and leave the frozen main loop in place.
        os._exit(1)
