"""Tests for the pulse watchdog.

The watchdog's failure mode is expensive in both directions:
  * too eager  -> it kills a healthy daemon mid-session
  * too lax    -> a hung daemon is never restarted
so the timing behaviour is asserted explicitly.
"""
import threading
import time

import pytest

from src.sniper.watchdog import PulseWatchdog


def test_rejects_non_positive_timeout():
    with pytest.raises(ValueError):
        PulseWatchdog(0)
    with pytest.raises(ValueError):
        PulseWatchdog(-1)


def test_fresh_watchdog_is_not_stale():
    wd = PulseWatchdog(60)
    assert wd.is_stale() is False
    assert wd.stale_seconds() < 1.0


def test_beat_resets_staleness():
    wd = PulseWatchdog(0.3)
    time.sleep(0.2)
    assert wd.is_stale() is False
    wd.beat()
    time.sleep(0.2)
    assert wd.is_stale() is False


def test_is_stale_after_timeout():
    wd = PulseWatchdog(0.15)
    time.sleep(0.25)
    assert wd.is_stale() is True
    assert wd.stale_seconds() >= 0.15


def test_fires_when_starved():
    fired = threading.Event()
    seen = {}

    def on_timeout(stale):
        seen["stale"] = stale
        fired.set()

    PulseWatchdog(0.2, check_interval_seconds=0.05, on_timeout=on_timeout).start()
    assert fired.wait(3.0), "watchdog did not fire on a starved heartbeat"
    assert seen["stale"] >= 0.2


def test_does_not_fire_while_beating():
    fired = threading.Event()
    wd = PulseWatchdog(0.25, check_interval_seconds=0.05,
                       on_timeout=lambda s: fired.set()).start()
    try:
        for _ in range(12):          # keep beating well past the timeout
            wd.beat()
            time.sleep(0.05)
    finally:
        wd.stop()
    assert not fired.is_set(), "watchdog fired although the heartbeat was kept fresh"


def test_stop_prevents_firing():
    fired = threading.Event()
    wd = PulseWatchdog(0.15, check_interval_seconds=0.05,
                       on_timeout=lambda s: fired.set()).start()
    wd.stop()
    time.sleep(0.4)
    assert not fired.is_set()


def test_check_interval_is_derived_and_bounded():
    # timeout/4, clamped into [1, 30]
    assert PulseWatchdog(8 * 60).check_interval_seconds == 30.0
    assert PulseWatchdog(8).check_interval_seconds == 2.0
    assert PulseWatchdog(1).check_interval_seconds == 1.0


def test_default_timeout_is_conservative():
    """The default must stay well above the longest legitimate silence (147s
    measured in production) or it will kill healthy sessions."""
    from src.sniper.watchdog import DEFAULT_TIMEOUT_SECONDS

    assert DEFAULT_TIMEOUT_SECONDS >= 5 * 60


# ── config coercion: a bad value must not crash startup ────────────────────

def test_timeout_from_minutes_valid():
    from src.sniper.watchdog import timeout_seconds_from_minutes

    assert timeout_seconds_from_minutes(10) == 600.0
    assert timeout_seconds_from_minutes(2.5) == 150.0
    assert timeout_seconds_from_minutes("3") == 180.0


@pytest.mark.parametrize("bad", [0, -1, "abc", None, [1]])
def test_timeout_from_minutes_falls_back(bad):
    """A typo in global_config must not raise — PulseWatchdog(<=0) raises, and
    that would stop the daemon from booting at all."""
    from src.sniper.watchdog import DEFAULT_TIMEOUT_SECONDS, timeout_seconds_from_minutes

    assert timeout_seconds_from_minutes(bad) == float(DEFAULT_TIMEOUT_SECONDS)


def test_before_exit_hook_runs_before_hard_exit():
    """os._exit skips normal shutdown, so the daemon needs a chance to mark its
    state file stopped first — otherwise a dead process still reads running:true."""
    import subprocess, sys, textwrap

    code = textwrap.dedent("""
        import sys, time
        sys.path.insert(0, '.')
        from src.sniper.watchdog import PulseWatchdog

        marks = []
        PulseWatchdog(0.2, check_interval_seconds=0.05,
                      before_exit=lambda: marks.append('marked')).start()
        time.sleep(5)
        open('/tmp/_wd_marks.txt', 'w').write(','.join(marks))   # unreachable
    """)
    subprocess.run([sys.executable, "-c", code], capture_output=True, timeout=20)
    # the hook ran, but os._exit still prevented the code after sleep()
    import pathlib
    assert not pathlib.Path("/tmp/_wd_marks.txt").exists()


def test_before_exit_hook_failure_does_not_block_exit():
    import subprocess, sys, textwrap

    code = textwrap.dedent("""
        import sys, time
        sys.path.insert(0, '.')
        from src.sniper.watchdog import PulseWatchdog

        def boom():
            raise RuntimeError('state write failed')

        PulseWatchdog(0.2, check_interval_seconds=0.05, before_exit=boom).start()
        time.sleep(5)
    """)
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, timeout=20)
    assert r.returncode == 1   # still hard-exits even if the hook raises


# ── gap clock: host suspend must count as elapsed time ────────────────────

def test_elapsed_wall_seconds_counts_suspend(monkeypatch):
    """The gap check must use a clock that advances while the host is asleep.

    Monotonic clocks do not reliably do that (Linux CLOCK_MONOTONIC excludes
    suspend), which would make the whole gap reset a no-op in exactly the
    scenario it exists for.  Simulate a 2-hour suspend by stepping wall time.
    """
    import time as _time
    from run_sniper import SniperDaemon

    base = 1_000_000.0
    monkeypatch.setattr(_time, "time", lambda: base)
    stamp = _time.time()

    monkeypatch.setattr(_time, "time", lambda: base + 7200)   # slept 2h
    assert SniperDaemon._elapsed_wall_seconds(stamp) == 7200.0


def test_elapsed_wall_seconds_none_without_baseline():
    from run_sniper import SniperDaemon

    assert SniperDaemon._elapsed_wall_seconds(None) is None


def test_elapsed_wall_seconds_clamps_backwards_clock(monkeypatch):
    """An NTP step backwards must not produce a negative gap (which would both
    skip the reset and, if unclamped, look like a huge elapsed time)."""
    import time as _time
    from run_sniper import SniperDaemon

    base = 1_000_000.0
    monkeypatch.setattr(_time, "time", lambda: base)
    stamp = _time.time()
    monkeypatch.setattr(_time, "time", lambda: base - 500)
    assert SniperDaemon._elapsed_wall_seconds(stamp) == 0.0


# ── suspend detection: an idle host is not a hung loop ─────────────────────
#
# Regression case, macOS 2026-09-23 02:19 → 2026-09-24 06:57.  The laptop never
# truly woke; it cycled DarkWake/Sleep every ~15 min all night.  time.monotonic()
# advances during DarkWake but not during deep sleep, so it accumulated 15.3 min
# while 4 h 38 m of wall time passed — enough to trip the 15-minute timeout.
# The daemon was NOT hung, and firing forced a pointless manual restart.

REAL_SUSPEND_WALL = 4 * 3600 + 38 * 60      # 4h38m
REAL_SUSPEND_MONO = int(15.3 * 60)          # 15.3m


def _frozen_watchdog(monkeypatch, wall0, mono0, **kw):
    import src.sniper.watchdog as wd

    monkeypatch.setattr(wd.time, "time", lambda: wall0)
    monkeypatch.setattr(wd.time, "monotonic", lambda: mono0)
    fired = []
    w = wd.PulseWatchdog(15 * 60, check_interval_seconds=10 ** 9,
                         on_timeout=fired.append, **kw)
    return wd, w, fired


def test_does_not_fire_when_host_was_asleep(monkeypatch):
    import src.sniper.watchdog as wd

    wall0, mono0 = 1_000_000.0, 500.0
    _, w, fired = _frozen_watchdog(monkeypatch, wall0, mono0)

    # the overnight gap: wall races ahead, monotonic barely moves
    monkeypatch.setattr(wd.time, "time", lambda: wall0 + REAL_SUSPEND_WALL)
    monkeypatch.setattr(wd.time, "monotonic", lambda: mono0 + REAL_SUSPEND_MONO)

    assert w.is_stale() is True, "monotonic clock does say stale"
    assert w.host_suspended_seconds() > 4 * 3600, "and the host was clearly asleep"
    assert w.should_fire() is False, "so the watchdog must NOT fire"
    assert fired == []


def test_fires_when_stale_without_suspend(monkeypatch):
    """A genuine hang: the host is awake, so both clocks advance together."""
    import src.sniper.watchdog as wd

    wall0, mono0 = 1_000_000.0, 500.0
    _, w, _ = _frozen_watchdog(monkeypatch, wall0, mono0)

    monkeypatch.setattr(wd.time, "time", lambda: wall0 + 16 * 60)
    monkeypatch.setattr(wd.time, "monotonic", lambda: mono0 + 16 * 60)

    assert w.is_stale() is True
    assert abs(w.host_suspended_seconds()) < 1
    assert w.should_fire() is True


def test_small_sleep_within_slack_still_fires(monkeypatch):
    """A brief sleep must not be used as an excuse to ignore a real hang."""
    import src.sniper.watchdog as wd

    wall0, mono0 = 1_000_000.0, 500.0
    _, w, _ = _frozen_watchdog(monkeypatch, wall0, mono0)

    # 20 min of monotonic staleness, only 30 s of which was suspend
    monkeypatch.setattr(wd.time, "time", lambda: wall0 + 20 * 60 + 30)
    monkeypatch.setattr(wd.time, "monotonic", lambda: mono0 + 20 * 60)

    assert w.should_fire() is True


def test_rebase_clears_staleness_after_suspend(monkeypatch):
    """After re-basing, the watchdog starts a fresh window (so the daemon gets a
    full timeout of *awake* time before being judged stuck)."""
    import src.sniper.watchdog as wd

    wall0, mono0 = 1_000_000.0, 500.0
    _, w, _ = _frozen_watchdog(monkeypatch, wall0, mono0)
    monkeypatch.setattr(wd.time, "time", lambda: wall0 + REAL_SUSPEND_WALL)
    monkeypatch.setattr(wd.time, "monotonic", lambda: mono0 + REAL_SUSPEND_MONO)
    assert w.should_fire() is False

    w.beat()   # what _run() does on the suspend branch
    assert w.is_stale() is False
    assert w.host_suspended_seconds() < 1
