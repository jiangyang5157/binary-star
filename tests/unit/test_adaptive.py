"""Tests for scale-free detector thresholds (src/sniper/adaptive.py)."""
import math
from datetime import datetime, timedelta, timezone

import pytest

from src.sniper.adaptive import MAD_TO_SIGMA, RobustWindow, RobustWindows

T0 = datetime(2026, 10, 14, tzinfo=timezone.utc)


def _feed(win, values, start=T0, step_minutes=2.0, now=None):
    """Feed samples; returns the timestamp after the last one."""
    t = start
    for v in values:
        win.update(v, t)
        t += timedelta(minutes=step_minutes)
    return t


class TestConstruction:

    def test_rejects_non_positive_window(self):
        with pytest.raises(ValueError):
            RobustWindow(0, 10)
        with pytest.raises(ValueError):
            RobustWindow(-5, 10)

    def test_rejects_zero_min_samples(self):
        with pytest.raises(ValueError):
            RobustWindow(60, 0)

    def test_starts_empty_and_not_ready(self):
        win = RobustWindow(60, 5)
        assert win.count == 0
        assert win.ready is False


class TestWarmup:

    def test_not_ready_below_min_samples(self):
        win = RobustWindow(600, 5)
        _feed(win, [1.0, 2.0, 3.0, 4.0])
        assert win.ready is False

    def test_ready_at_min_samples(self):
        win = RobustWindow(600, 5)
        _feed(win, [1.0, 2.0, 3.0, 4.0, 5.0])
        assert win.ready is True

    def test_z_is_zero_during_warmup(self):
        """Callers compare abs(z) > k, so 0.0 keeps the detector dark."""
        win = RobustWindow(600, 10)
        _feed(win, [1.0, 100.0, 2.0])
        assert win.z(999.0) == 0.0


class TestStatistics:

    def test_median_odd_and_even(self):
        win = RobustWindow(600, 1)
        _feed(win, [1.0, 3.0, 2.0])
        assert win.median() == pytest.approx(2.0)
        win.update(4.0, T0 + timedelta(minutes=10))
        assert win.median() == pytest.approx(2.5)

    def test_scale_is_mad_times_constant(self):
        win = RobustWindow(600, 1)
        # deviations from median 3.0 are [2,1,0,1,2] → MAD = 1
        _feed(win, [1.0, 2.0, 3.0, 4.0, 5.0])
        assert win.scale() == pytest.approx(MAD_TO_SIGMA * 1.0)

    def test_z_of_an_outlier_is_large(self):
        win = RobustWindow(600, 3)
        _feed(win, [1.0, 2.0, 3.0, 4.0, 5.0])
        assert win.z(20.0) > 3.0

    def test_z_of_a_typical_value_is_small(self):
        win = RobustWindow(600, 3)
        _feed(win, [1.0, 2.0, 3.0, 4.0, 5.0])
        assert abs(win.z(3.0)) < 1.0

    def test_zero_dispersion_returns_zero_not_inf(self):
        """A perfectly constant metric has nothing to be an outlier of."""
        win = RobustWindow(600, 3)
        _feed(win, [7.0, 7.0, 7.0, 7.0])
        assert win.scale() == 0.0
        assert win.z(7.0) == 0.0
        assert win.z(1000.0) == 0.0
        assert math.isfinite(win.z(1000.0))

    def test_single_sample_has_no_scale(self):
        win = RobustWindow(600, 1)
        win.update(5.0, T0)
        assert win.scale() == 0.0
        assert win.z(5.0) == 0.0


class TestScoringOrder:

    def test_score_uses_the_prior_window(self):
        """An extreme must not be able to move its own threshold."""
        win = RobustWindow(600, 3)
        _feed(win, [1.0, 2.0, 3.0, 4.0, 5.0])
        before = win.z(100.0)
        scored = win.score(100.0, T0 + timedelta(minutes=20))
        assert scored == pytest.approx(before)

    def test_score_folds_the_value_in(self):
        win = RobustWindow(600, 3)
        _feed(win, [1.0, 2.0, 3.0])
        n = win.count
        win.score(4.0, T0 + timedelta(minutes=10))
        assert win.count == n + 1


class TestWindowing:

    def test_old_samples_age_out(self):
        win = RobustWindow(10, 1)
        _feed(win, [1.0, 2.0, 3.0], step_minutes=2.0)          # t = 0, 2, 4
        assert win.count == 3
        win.update(9.0, T0 + timedelta(minutes=30))            # prunes everything older than 20
        assert win.count == 1

    def test_window_is_in_minutes_not_pulses(self):
        """A short pulse interval must not shrink the reach of the window."""
        fast = RobustWindow(60, 1)
        _feed(fast, [float(i) for i in range(30)], step_minutes=1.0)   # 30 min
        slow = RobustWindow(60, 1)
        _feed(slow, [float(i) for i in range(30)], step_minutes=1.0)
        assert fast.count == slow.count == 30

    def test_becomes_not_ready_again_after_a_long_gap(self):
        """After a suspend/resume the baseline is stale — better dark than wrong."""
        win = RobustWindow(60, 5)
        _feed(win, [1.0, 2.0, 3.0, 4.0, 5.0])
        assert win.ready is True
        win.update(6.0, T0 + timedelta(hours=5))
        assert win.ready is False


class TestIngestionGuards:

    def test_none_is_ignored(self):
        win = RobustWindow(600, 1)
        win.update(None, T0)
        assert win.count == 0

    @pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
    def test_non_finite_is_ignored(self, bad):
        win = RobustWindow(600, 1)
        win.update(bad, T0)
        assert win.count == 0

    def test_int_is_coerced(self):
        win = RobustWindow(600, 1)
        win.update(3, T0)
        assert win.count == 1
        assert win.median() == pytest.approx(3.0)

    def test_clear_empties(self):
        win = RobustWindow(600, 1)
        _feed(win, [1.0, 2.0])
        win.clear()
        assert win.count == 0
        assert win.ready is False


class TestRobustWindows:

    def test_named_windows_are_independent(self):
        ws = RobustWindows(600, 3, names=["a", "b"])
        _feed(ws.window("a"), [1.0, 2.0, 3.0, 4.0, 5.0])
        assert ws.ready("a") is True
        assert ws.ready("b") is False

    def test_unknown_name_is_created_lazily(self):
        ws = RobustWindows(600, 3)
        assert ws.ready("brand_new") is False
        _feed(ws.window("brand_new"), [1.0, 2.0, 3.0])
        assert ws.ready("brand_new") is True

    def test_clear_clears_all(self):
        ws = RobustWindows(600, 1)
        _feed(ws.window("a"), [1.0])
        _feed(ws.window("b"), [1.0])
        ws.clear()
        assert ws.window("a").count == 0
        assert ws.window("b").count == 0

    def test_score_updates_the_named_window(self):
        ws = RobustWindows(600, 3)
        _feed(ws.window("a"), [1.0, 2.0, 3.0, 4.0, 5.0])
        before = ws.window("a").count
        z = ws.score("a", 20.0, T0 + timedelta(minutes=20))
        assert ws.window("a").count == before + 1
        assert z > 3.0

    def test_z_reports_the_prior_window_without_ingesting(self):
        """z() is a pure read — used where the value is a derived quantity that
        the caller does not want counted twice."""
        ws = RobustWindows(600, 3)
        _feed(ws.window("a"), [1.0, 2.0, 3.0, 4.0, 5.0])
        before = ws.window("a").count
        assert ws.z("a", 20.0) > 3.0
        assert ws.window("a").count == before
