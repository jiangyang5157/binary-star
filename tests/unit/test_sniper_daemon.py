"""
Unit tests for SniperDaemon._attempt_trade_execution — the trade gate method.

Covers: opinion/confidence/tactical gates, success path, emergency-close sentinel,
and the entry_atr extraction that caused NameError / AttributeError crashes.
"""

import pytest
from unittest.mock import MagicMock


# ── Helpers ────────────────────────────────────────────────────────────────

def _make_daemon(executor=None, trade_states=None, prev_metrics=None,
                 confidence_threshold=50):
    """Build a SniperDaemon with just enough state to call _attempt_trade_execution."""
    from run_sniper import SniperDaemon

    daemon = SniperDaemon.__new__(SniperDaemon)
    daemon.global_cfg = {
        "llm": {
            "binary_star": {
                "session_confidence_threshold": confidence_threshold,
            }
        }
    }
    daemon.executor = executor
    daemon.trade_states = trade_states or {}
    daemon.prev_metrics = prev_metrics or {}
    return daemon


def _session_result(opinion="NEUTRAL", confidence=0.0, tactical=None):
    """Build a session_result dict with the shape produced by the orchestrator."""
    return {
        "final_decision": {
            "opinion": opinion,
            "confidence_score": confidence,
            "tactical_parameters": tactical or {},
        }
    }


# ── Gate 1: Directional opinion ────────────────────────────────────────────

def test_gate1_neutral_skips_trade():
    """NEUTRAL opinion returns without calling executor."""
    executor = MagicMock()
    daemon = _make_daemon(executor=executor)

    daemon._attempt_trade_execution("BTCUSDT", _session_result(opinion="NEUTRAL"))

    executor.sync_with_opinion.assert_not_called()


def test_gate1_bullish_passes():
    """BULLISH opinion passes Gate 1 (needs confidence + tactical to proceed)."""
    executor = MagicMock()
    daemon = _make_daemon(executor=executor)

    # Gate 2 will stop it (0% confidence < 50% threshold), but Gate 1 passed
    daemon._attempt_trade_execution(
        "BTCUSDT",
        _session_result(opinion="BULLISH", confidence=0),
    )

    executor.sync_with_opinion.assert_not_called()  # blocked at Gate 2


# ── Gate 2: Confidence threshold ────────────────────────────────────────────

def test_gate2_low_confidence_skips_trade():
    """Confidence below threshold returns without calling executor."""
    executor = MagicMock()
    daemon = _make_daemon(executor=executor, confidence_threshold=80)

    daemon._attempt_trade_execution(
        "BTCUSDT",
        _session_result(opinion="BEARISH", confidence=75),
    )

    executor.sync_with_opinion.assert_not_called()


def test_gate2_exact_threshold_passes():
    """Confidence == threshold passes Gate 2."""
    executor = MagicMock()
    daemon = _make_daemon(executor=executor, confidence_threshold=80)

    # Gate 3 will stop it (no tactical params), but Gate 2 passed
    daemon._attempt_trade_execution(
        "BTCUSDT",
        _session_result(opinion="BEARISH", confidence=80),
    )

    executor.sync_with_opinion.assert_not_called()  # blocked at Gate 3


# ── Gate 3: Tactical parameters ─────────────────────────────────────────────

def test_gate3_missing_entry_skips_trade():
    executor = MagicMock()
    daemon = _make_daemon(executor=executor)

    daemon._attempt_trade_execution(
        "BTCUSDT",
        _session_result(
            opinion="BULLISH", confidence=90,
            tactical={"take_profit": 70000, "stop_loss": 60000},  # no entry
        ),
    )

    executor.sync_with_opinion.assert_not_called()


def test_gate3_missing_tp_skips_trade():
    executor = MagicMock()
    daemon = _make_daemon(executor=executor)

    daemon._attempt_trade_execution(
        "BTCUSDT",
        _session_result(
            opinion="BULLISH", confidence=90,
            tactical={"entry": 65000, "stop_loss": 60000},  # no tp
        ),
    )

    executor.sync_with_opinion.assert_not_called()


# ── Success path ────────────────────────────────────────────────────────────

def test_successful_trade_long():
    """All gates pass, executor returns order_id > 0 → trade_state updated."""
    executor = MagicMock()
    executor.sync_with_opinion.return_value = 12345

    prev_metrics = {
        "BTCUSDT": {
            "price_dynamics": {"atr_macro": 403.91, "current_price": 64200},
        }
    }
    daemon = _make_daemon(executor=executor, prev_metrics=prev_metrics)

    daemon._attempt_trade_execution(
        "BTCUSDT",
        _session_result(
            opinion="BULLISH", confidence=92,
            tactical={
                "entry": 65000,
                "take_profit": 70000,
                "stop_loss": 63000,
                "projected_waiting_hours": 1.5,
                "projected_holding_hours": 3.0,
            },
        ),
    )

    # Executor called with correct direction
    executor.sync_with_opinion.assert_called_once_with(
        symbol="BTCUSDT",
        opinion_direction="LONG",
        entry_price=65000.0,
        tp_price=70000.0,
        sl_price=63000.0,
    )

    # Trade state recorded
    assert "BTCUSDT" in daemon.trade_states
    state = daemon.trade_states["BTCUSDT"]
    assert state["direction"] == "LONG"
    assert state["entry_price"] == 65000.0
    assert state["entry_order_id"] == 12345
    assert state["entry_atr"] == 403.91


def test_successful_trade_short():
    """BEARISH opinion maps to SHORT direction."""
    executor = MagicMock()
    executor.sync_with_opinion.return_value = 99999

    prev_metrics = {
        "XAUTUSDT": {
            "price_dynamics": {"atr_macro": 23.0, "current_price": 4200},
        }
    }
    daemon = _make_daemon(executor=executor, prev_metrics=prev_metrics)

    daemon._attempt_trade_execution(
        "XAUTUSDT",
        _session_result(
            opinion="BEARISH", confidence=95,
            tactical={
                "entry": 4100,
                "take_profit": 4000,
                "stop_loss": 4150,
            },
        ),
    )

    executor.sync_with_opinion.assert_called_once_with(
        symbol="XAUTUSDT",
        opinion_direction="SHORT",
        entry_price=4100.0,
        tp_price=4000.0,
        sl_price=4150.0,
    )

    assert daemon.trade_states["XAUTUSDT"]["direction"] == "SHORT"
    assert daemon.trade_states["XAUTUSDT"]["entry_atr"] == 23.0


# ── entry_atr extraction (the bug we fixed) ─────────────────────────────────

def test_entry_atr_falls_back_to_zero_when_prev_metrics_is_none():
    """prev_metrics.get(symbol) returns None → entry_atr defaults to 0.0."""
    executor = MagicMock()
    executor.sync_with_opinion.return_value = 1

    # Simulates first-pulse state: key exists but value is None
    daemon = _make_daemon(
        executor=executor,
        prev_metrics={"BTCUSDT": None},
    )

    daemon._attempt_trade_execution(
        "BTCUSDT",
        _session_result(
            opinion="BULLISH", confidence=90,
            tactical={"entry": 65000, "take_profit": 70000, "stop_loss": 63000},
        ),
    )

    assert daemon.trade_states["BTCUSDT"]["entry_atr"] == 0.0


def test_entry_atr_falls_back_to_zero_when_symbol_missing():
    """Symbol not in prev_metrics → entry_atr defaults to 0.0."""
    executor = MagicMock()
    executor.sync_with_opinion.return_value = 1

    daemon = _make_daemon(executor=executor, prev_metrics={})

    daemon._attempt_trade_execution(
        "BTCUSDT",
        _session_result(
            opinion="BEARISH", confidence=90,
            tactical={"entry": 65000, "take_profit": 64000, "stop_loss": 66000},
        ),
    )

    assert daemon.trade_states["BTCUSDT"]["entry_atr"] == 0.0


# ── Emergency-close sentinel ─────────────────────────────────────────────────

def test_emergency_close_sentinel_clears_trade_state():
    """Executor returns -1 → trade state is cleared."""
    executor = MagicMock()
    executor.sync_with_opinion.return_value = -1

    daemon = _make_daemon(
        executor=executor,
        trade_states={"BTCUSDT": {"direction": "SHORT"}},
    )

    daemon._attempt_trade_execution(
        "BTCUSDT",
        _session_result(
            opinion="BEARISH", confidence=90,
            tactical={"entry": 65000, "take_profit": 64000, "stop_loss": 66000},
        ),
    )

    assert "BTCUSDT" not in daemon.trade_states


# ── Executor returns None (no action) ───────────────────────────────────────

def test_executor_returns_none_without_existing_state():
    """sync_with_opinion returns None, no existing trade → silent no-op."""
    executor = MagicMock()
    executor.sync_with_opinion.return_value = None

    daemon = _make_daemon(executor=executor)

    # Should not raise
    daemon._attempt_trade_execution(
        "BTCUSDT",
        _session_result(
            opinion="BEARISH", confidence=90,
            tactical={"entry": 65000, "take_profit": 64000, "stop_loss": 66000},
        ),
    )

    assert "BTCUSDT" not in daemon.trade_states


def test_executor_returns_none_preserves_existing_state():
    """sync_with_opinion returns None, existing trade → state preserved (same-dir optimization)."""
    executor = MagicMock()
    executor.sync_with_opinion.return_value = None

    existing = {"direction": "SHORT", "entry_price": 66000}
    daemon = _make_daemon(executor=executor, trade_states={"BTCUSDT": existing})

    daemon._attempt_trade_execution(
        "BTCUSDT",
        _session_result(
            opinion="BEARISH", confidence=90,
            tactical={"entry": 65000, "take_profit": 64000, "stop_loss": 66000},
        ),
    )

    assert daemon.trade_states["BTCUSDT"] == existing  # untouched
