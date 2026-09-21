"""Smoke tests for the MCP servers in mcp_servers/.

These exist because the servers are thin read-only adapters over on-disk state,
so their failure mode is *silent drift*: a field gets renamed/removed in the
daemon and the tool keeps returning null (this happened — `gate_reason` was
dropped from the pulse payload on 2026-07-15 and the server kept asking for it
for two months).

They assert the contract, not the values: tools load, documented fields are
actually present in the payload the daemon writes, and missing files degrade to
an error dict instead of raising.
"""
import asyncio
import importlib.util
import json
import sys
from pathlib import Path

import pytest

pytest.importorskip("mcp", reason="mcp extra not installed")

ROOT = Path(__file__).resolve().parents[2]
SNIPER = ROOT / "mcp_servers" / "binary_star_sniper" / "server.py"
ADMIN = ROOT / "mcp_servers" / "binary_star_admin" / "server.py"


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def sniper_mod():
    return _load("_bs_sniper_srv", SNIPER)


@pytest.fixture(scope="module")
def admin_mod():
    return _load("_bs_admin_srv", ADMIN)


def run(coro):
    return asyncio.run(coro)


# ── tool registration ──────────────────────────────────────────────────────

def test_sniper_tools_registered(sniper_mod):
    names = {t.name for t in run(sniper_mod.mcp.list_tools())}
    assert {
        "get_sniper_status", "get_pulse_state", "get_active_signals",
        "get_gate_status", "get_cooldown_status", "get_recent_gate_blocks",
        "get_pulse_history",
    } <= names


def test_admin_tools_registered(admin_mod):
    names = {t.name for t in run(admin_mod.mcp.list_tools())}
    assert {
        "get_effective_config", "get_symbol_trade_params", "get_prompt",
        "get_evolution_history", "list_configured_symbols",
    } <= names


# ── data-root resolution (was hardcoded to data/prod) ──────────────────────

def test_data_root_default(sniper_mod, monkeypatch):
    monkeypatch.delenv("BS_SNIPER_DATA_ROOT", raising=False)
    assert sniper_mod._data_root() == ROOT / "data" / "prod"


def test_data_root_env_relative_and_absolute(sniper_mod, monkeypatch, tmp_path):
    monkeypatch.setenv("BS_SNIPER_DATA_ROOT", "data/backtest")
    assert sniper_mod._data_root() == ROOT / "data" / "backtest"

    monkeypatch.setenv("BS_SNIPER_DATA_ROOT", str(tmp_path))
    assert sniper_mod._data_root() == tmp_path

    # blank value must behave as "unset" (see .mcp.json)
    monkeypatch.setenv("BS_SNIPER_DATA_ROOT", "")
    assert sniper_mod._data_root() == ROOT / "data" / "prod"


# ── graceful degradation when the daemon isn't running ─────────────────────

def test_missing_state_returns_error_dict(sniper_mod, monkeypatch, tmp_path):
    monkeypatch.setenv("BS_SNIPER_DATA_ROOT", str(tmp_path))
    out = run(sniper_mod.get_sniper_status())
    assert "error" in out and out["data_root"] == str(tmp_path)


def test_missing_pulse_returns_error_dict(sniper_mod, monkeypatch, tmp_path):
    monkeypatch.setenv("BS_SNIPER_DATA_ROOT", str(tmp_path))
    out = run(sniper_mod.get_pulse_state("BTCUSDT"))
    assert "error" in out


def test_missing_history_returns_error_dict(sniper_mod, monkeypatch, tmp_path):
    monkeypatch.setenv("BS_SNIPER_DATA_ROOT", str(tmp_path))
    out = run(sniper_mod.get_pulse_history("BTCUSDT"))
    assert "error" in out


def test_unknown_symbol_lists_available(sniper_mod, monkeypatch, tmp_path):
    monkeypatch.setenv("BS_SNIPER_DATA_ROOT", str(tmp_path))
    (tmp_path / ".sniper_pulse.json").write_text(json.dumps({
        "pulse_at": "2026-01-01T00:00:00+00:00",
        "symbols": {"BTCUSDT": {"confluence_score": 0.1, "signals": []}},
    }))
    out = run(sniper_mod.get_pulse_state("BTC"))
    assert out["available_symbols"] == ["BTCUSDT"]
    assert "full pair" in out["hint"]


# ── the payload contract the tools document ────────────────────────────────

def test_gate_fields_surface_from_pulse_payload(sniper_mod, monkeypatch, tmp_path):
    """get_gate_status must expose gate_result/gate_reason — the exact pair that
    was silently dead for two months."""
    monkeypatch.setenv("BS_SNIPER_DATA_ROOT", str(tmp_path))
    (tmp_path / ".sniper_pulse.json").write_text(json.dumps({
        "pulse_at": "2026-01-01T00:00:00+00:00",
        "symbols": {"BTCUSDT": {
            "triggered": False, "confluence_score": 0.29, "threshold": 0.27,
            "direction": "BEARISH", "cooldown_active": False,
            "cooldown_remaining_seconds": 1200,
            "gate_result": "FAIL",
            "gate_reason": "MIN_ACTIVE_SIGNALS: regime=squeeze requires >=3 signals",
            "signals": [{"type": "cvd_momentum", "strength": 0.5,
                         "direction": "BEARISH", "is_active": True}],
        }},
    }))
    out = run(sniper_mod.get_gate_status("BTCUSDT"))
    assert out["gate_result"] == "FAIL"
    assert "MIN_ACTIVE_SIGNALS" in out["gate_reason"]
    # back-compat alias must agree
    assert run(sniper_mod.get_cooldown_status("BTCUSDT"))["gate_reason"] == out["gate_reason"]


def test_history_cap_comes_from_config(sniper_mod):
    """The old code hardcoded 120, which silently drifts from the daemon's own
    pulse_history_max_entries setting."""
    from src.utils.pipeline_utils import load_global_config
    expected = load_global_config().get("sniper", {}).get("heartbeat", {}).get(
        "pulse_history_max_entries", 120)
    assert sniper_mod._history_max() == expected


# ── log-derived gate blocks ────────────────────────────────────────────────

GATE_FAIL_LINE = (
    "09:52:56.392 INF [trigger               ] [BTCUSDT] PRE-AI GATE FAIL | "
    "MIN_ACTIVE_SIGNALS: regime=squeeze requires ≥3 signals in BEARISH direction, got 1 | "
    "conf=0.29 | dir=BEARISH | regime=squeeze | fresh=3"
)
COOLDOWN_LINE = (
    "01:35:38.521 INF [trigger               ] [BTCUSDT] COOLDOWN BLOCK | "
    "COOLDOWN_TRENDING (2.1m/16.0m) | conf=0.58 >= thr=0.306 | dir=BULLISH | regime=trending"
)
XAUT_LINE = (
    "10:22:22.489 INF [trigger               ] [XAUTUSDT] PRE-AI GATE FAIL | "
    "MIN_ACTIVE_SIGNALS: regime=ranging requires ≥3 signals in BULLISH direction, got 1 | "
    "conf=0.41 | dir=BULLISH | regime=ranging | fresh=1"
)


def _write_log(tmp_path, lines):
    (tmp_path / "sniper.log").write_text("\n".join(lines) + "\n")


def test_recent_gate_blocks_parses_both_kinds(sniper_mod, monkeypatch, tmp_path):
    monkeypatch.setenv("BS_SNIPER_DATA_ROOT", str(tmp_path))
    _write_log(tmp_path, [GATE_FAIL_LINE, COOLDOWN_LINE, XAUT_LINE])

    out = run(sniper_mod.get_recent_gate_blocks(limit=10))
    assert out["returned"] == 3
    # newest first
    assert out["blocks"][0]["symbol"] == "XAUTUSDT"
    kinds = {b["kind"] for b in out["blocks"]}
    assert kinds == {"gate_fail", "cooldown_block"}
    gate = next(b for b in out["blocks"] if b["kind"] == "gate_fail")
    assert gate["regime"] == "ranging" and gate["confluence_score"] == 0.41


def test_recent_gate_blocks_filters_symbol(sniper_mod, monkeypatch, tmp_path):
    monkeypatch.setenv("BS_SNIPER_DATA_ROOT", str(tmp_path))
    _write_log(tmp_path, [GATE_FAIL_LINE, COOLDOWN_LINE, XAUT_LINE])
    out = run(sniper_mod.get_recent_gate_blocks(symbol="XAUTUSDT", limit=10))
    assert out["returned"] == 1
    assert out["blocks"][0]["symbol"] == "XAUTUSDT"


def test_recent_gate_blocks_missing_log(sniper_mod, monkeypatch, tmp_path):
    monkeypatch.setenv("BS_SNIPER_DATA_ROOT", str(tmp_path))
    out = run(sniper_mod.get_recent_gate_blocks())
    assert "error" in out


def test_recent_gate_blocks_ignores_unrelated_lines(sniper_mod, monkeypatch, tmp_path):
    monkeypatch.setenv("BS_SNIPER_DATA_ROOT", str(tmp_path))
    _write_log(tmp_path, ["13:00:00.000 INF [trigger               ] [BTCUSDT] SIGNAL DIAG | cvd=+0.1",
                          "13:00:01.000 INF [SniperDaemon          ] \u26aa SNIPER MONITORING STARTED"])
    out = run(sniper_mod.get_recent_gate_blocks())
    assert out["returned"] == 0


# ── admin: prompt registry must match config/prompts/ ──────────────────────

def test_admin_prompt_modules_match_disk(admin_mod):
    allowed = {"session", "critic", "binary_star", "evolver"}
    on_disk = {p.stem for p in (ROOT / "config" / "prompts").glob("*.md")}
    assert allowed == on_disk, "get_prompt's allow-list drifted from config/prompts/"
    for module in sorted(allowed):
        out = run(admin_mod.get_prompt(module))
        assert "error" not in out, out
        assert out["content"].strip(), f"empty prompt for {module}"


def test_admin_rejects_unknown_prompt_module(admin_mod):
    out = run(admin_mod.get_prompt("nope"))
    assert "error" in out and "available_modules" in out
