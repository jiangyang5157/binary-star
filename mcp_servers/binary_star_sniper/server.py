"""
BinaryStar Sniper State MCP Server.

Read-only exposure of the sniper daemon's on-disk state plus the gate/cooldown
decisions it logs:

  .sniper_state.json          daemon liveness + config
  .sniper_pulse.json          latest pulse snapshot (incl. gate_result/gate_reason)
  .sniper_pulse_history.json  per-pulse confluence time-series of the last run
  sniper.log                  recent PRE-AI GATE FAIL / COOLDOWN BLOCK decisions

Data root resolution (first match wins):
  1. $BS_SNIPER_DATA_ROOT  (absolute, or relative to the project root)
  2. <project>/data/prod   (default)

Point it elsewhere when the daemon runs with `-p data/backtest` etc.

Usage:
  python mcp_servers/binary_star_sniper/server.py
"""

import json
import os
import re
import sys
from collections import deque
from pathlib import Path

try:  # mcp >= 2.0 renamed FastMCP -> MCPServer
    from mcp.server.mcpserver import MCPServer as _MCPServer
except ImportError:  # mcp 1.x still ships mcp.server.fastmcp
    from mcp.server.fastmcp import FastMCP as _MCPServer


mcp = _MCPServer("binary-star-sniper")

# ── Paths ──────────────────────────────────────────────────────────────────

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

DEFAULT_DATA_ROOT = PROJECT_ROOT / "data" / "prod"


def _data_root() -> Path:
    raw = os.environ.get("BS_SNIPER_DATA_ROOT", "").strip()
    if not raw:
        return DEFAULT_DATA_ROOT
    p = Path(raw).expanduser()
    return p if p.is_absolute() else (PROJECT_ROOT / p)


def _state_path() -> Path:
    return _data_root() / ".sniper_state.json"


def _pulse_path() -> Path:
    return _data_root() / ".sniper_pulse.json"


def _history_path() -> Path:
    return _data_root() / ".sniper_pulse_history.json"


def _log_path() -> Path:
    return _data_root() / "sniper.log"


def _history_max() -> int:
    """Cap from the daemon's own config so the two can never drift apart."""
    try:
        from src.utils.pipeline_utils import load_global_config

        return int(
            load_global_config().get("sniper", {}).get("heartbeat", {})
            .get("pulse_history_max_entries", 120)
        )
    except Exception:
        return 120


def _read_json(path: Path) -> dict | list | None:
    """Read a JSON file. Returns None if missing or unreadable."""
    try:
        return json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None


def _get_symbol_from_pulse(pulse: dict, symbol: str) -> tuple[dict | None, list[str]]:
    """Look up a symbol in pulse data. Returns (sym_data, available_symbols).

    sym_data is None when symbol not found.
    """
    symbols = pulse.get("symbols", {})
    sym_data = symbols.get(symbol)
    if sym_data is None:
        return None, list(symbols.keys())
    return sym_data, []


# ── Tool 1: Sniper Status ──────────────────────────────────────────────────

@mcp.tool()
async def get_sniper_status() -> dict:
    """Get the current sniper daemon status.

    Returns running state, active symbols, PID, trade_enabled flag,
    balance, started_at, last_pulse_at, active_session, and the data root
    actually being read.
    """
    state = _read_json(_state_path())
    if state is None:
        return {
            "error": "sniper state not available — daemon may not be running",
            "data_root": str(_data_root()),
        }
    if not isinstance(state, dict):
        return {"error": "sniper state data corrupted — expected dict"}
    return {**state, "data_root": str(_data_root())}


def _read_pulse_or_error() -> tuple[dict | None, dict | None]:
    """Read pulse file. Returns (pulse_dict, error_dict).

    Error dict is non-None when pulse is unavailable, corrupted, or not a dict.
    """
    pulse = _read_json(_pulse_path())
    if pulse is None:
        return None, {
            "error": "pulse data not available — daemon may not be running",
            "data_root": str(_data_root()),
        }
    if not isinstance(pulse, dict):
        return None, {"error": "pulse data corrupted — expected dict"}
    return pulse, None


def _symbol_payload(symbol: str) -> tuple[dict | None, dict | None]:
    """Shared prologue for the per-symbol tools. Returns (sym_data, error_dict)."""
    pulse, error = _read_pulse_or_error()
    if error:
        return None, error
    sym_data, available = _get_symbol_from_pulse(pulse, symbol)
    if sym_data is None:
        return None, {
            "error": f"symbol '{symbol}' not in pulse snapshot",
            "available_symbols": available,
            "hint": "use the full pair, e.g. 'BTCUSDT' (prefixes like 'BTC' are not accepted)",
        }
    return {"pulse_at": pulse.get("pulse_at"), "symbol": symbol, **sym_data}, None


# ── Tool 2: Pulse State ────────────────────────────────────────────────────

@mcp.tool()
async def get_pulse_state(symbol: str) -> dict:
    """Get the latest pulse state for a trading symbol.

    Args:
        symbol: Full trading pair, e.g. 'BTCUSDT' or 'XAUTUSDT'

    Returns pulse timestamp, and per-symbol fields:
    net_qty, active_orders, entry/tp/sl prices, current_price, triggered,
    confluence_score, threshold, direction, cooldown status,
    gate_result ("PASS" | "FAIL" | "SKIPPED"), gate_reason, and all 10 signal
    cards (each with its own strength/direction/is_active).
    """
    payload, error = _symbol_payload(symbol)
    return error if error else payload


# ── Tool 3: Active Signals ─────────────────────────────────────────────────

@mcp.tool()
async def get_active_signals(symbol: str) -> dict:
    """Get the signal cards that fired on the latest pulse.

    Args:
        symbol: Full trading pair, e.g. 'BTCUSDT' or 'XAUTUSDT'

    NOTE ON SEMANTICS: `is_active` means "this detector produced a fresh signal
    on this pulse with strength >= MIN_STACK_STRENGTH (0.15)".  It does NOT mean
    the signal contributed to a wake, and it says nothing about the gate — a
    pulse can have several active signals and still be blocked.  Use
    `get_gate_status` / `get_recent_gate_blocks` to see why it did not wake.

    Returns the active signal cards plus confluence score, threshold, direction.
    """
    payload, error = _symbol_payload(symbol)
    if error:
        return error

    all_signals = payload.get("signals", [])
    active = [s for s in all_signals if s.get("is_active")]

    return {
        "pulse_at": payload.get("pulse_at"),
        "symbol": symbol,
        "confluence_score": payload.get("confluence_score"),
        "threshold": payload.get("threshold"),
        "direction": payload.get("direction"),
        "triggered": payload.get("triggered"),
        "gate_result": payload.get("gate_result"),
        "gate_reason": payload.get("gate_reason"),
        "active_count": len(active),
        "active_signals": active,
    }


# ── Tool 4: Gate / Cooldown Status ─────────────────────────────────────────

@mcp.tool()
async def get_gate_status(symbol: str) -> dict:
    """Get why the latest pulse for a symbol did or did not wake a session.

    Args:
        symbol: Full trading pair, e.g. 'BTCUSDT' or 'XAUTUSDT'

    Returns:
      gate_result          "PASS" (woke) | "FAIL" (reached the gate and was
                           rejected) | "SKIPPED" (never reached it)
      gate_reason          e.g. "MIN_ACTIVE_SIGNALS: regime=ranging requires
                           >=3 signals in BULLISH direction, got 1", or
                           "COOLDOWN_RANGING (12.3m/40m)", or
                           "BELOW_THRESHOLD (conf=0.21 < thr=0.340)"
      cooldown_active      whether the symbol is inside its post-trigger cooldown
      cooldown_remaining_seconds

    For the history of rejections use `get_recent_gate_blocks`.
    """
    payload, error = _symbol_payload(symbol)
    if error:
        return error

    return {
        "pulse_at": payload.get("pulse_at"),
        "symbol": symbol,
        "gate_result": payload.get("gate_result"),
        "gate_reason": payload.get("gate_reason"),
        "triggered": payload.get("triggered"),
        "confluence_score": payload.get("confluence_score"),
        "threshold": payload.get("threshold"),
        "direction": payload.get("direction"),
        "cooldown_active": payload.get("cooldown_active"),
        "cooldown_remaining_seconds": payload.get("cooldown_remaining_seconds"),
    }


# ── Tool 5: Cooldown Status (back-compat alias) ────────────────────────────

@mcp.tool()
async def get_cooldown_status(symbol: str) -> dict:
    """Cooldown-only view. Prefer `get_gate_status`, which also explains *why*.

    Args:
        symbol: Full trading pair, e.g. 'BTCUSDT' or 'XAUTUSDT'
    """
    return await get_gate_status(symbol)


# ── Tool 6: Recent Gate Blocks (from the log) ──────────────────────────────

_GATE_FAIL_RE = re.compile(
    r"^(?P<t>\d{2}:\d{2}:\d{2}\.\d{3}).*\[(?P<sym>[A-Z0-9]+)\] PRE-AI GATE FAIL \| "
    r"(?P<reason>.*?) \| conf=(?P<conf>[\d.]+) \| dir=(?P<dir>\w+) \| regime=(?P<regime>\w+)")
_CD_BLOCK_RE = re.compile(
    r"^(?P<t>\d{2}:\d{2}:\d{2}\.\d{3}).*\[(?P<sym>[A-Z0-9]+)\] COOLDOWN BLOCK \| "
    r"(?P<reason>.*?) \| conf=(?P<conf>[\d.]+) >= thr=(?P<thr>[\d.]+) \| dir=(?P<dir>\w+) \| "
    r"regime=(?P<regime>\w+)")


def _tail_lines(path: Path, max_bytes: int = 2_000_000) -> list[str]:
    """Read roughly the last `max_bytes` of a file as lines (cheap tail)."""
    try:
        size = path.stat().st_size
        with path.open("rb") as f:
            if size > max_bytes:
                f.seek(size - max_bytes)
                f.readline()  # discard the partial first line
            return f.read().decode("utf-8", errors="replace").splitlines()
    except (FileNotFoundError, OSError):
        return []


@mcp.tool()
async def get_recent_gate_blocks(symbol: str = "", limit: int = 20) -> dict:
    """List the most recent gate / cooldown rejections from the daemon log.

    Args:
        symbol: Optional full trading pair to filter by (e.g. 'BTCUSDT').
                Empty string returns all symbols.
        limit: Max entries to return (default 20).

    Reads `PRE-AI GATE FAIL` (rejected at the pre-AI gate) and `COOLDOWN BLOCK`
    (a would-be wake suppressed by the post-trigger cooldown) lines out of
    sniper.log.  Only available while the daemon is writing that log; the log
    persists across restarts.
    """
    limit = max(1, min(limit, 200))
    path = _log_path()
    if not path.exists():
        return {"error": f"sniper log not found: {path}", "data_root": str(_data_root())}

    found: list[dict] = []
    for line in reversed(_tail_lines(path)):
        m = _GATE_FAIL_RE.match(line)
        kind = "gate_fail"
        if not m:
            m = _CD_BLOCK_RE.match(line)
            kind = "cooldown_block"
        if not m:
            continue
        if symbol and m.group("sym") != symbol:
            continue
        found.append({
            "at": m.group("t"),
            "kind": kind,
            "symbol": m.group("sym"),
            "direction": m.group("dir"),
            "regime": m.group("regime"),
            "confluence_score": float(m.group("conf")),
            "reason": m.group("reason"),
        })
        if len(found) >= limit:
            break

    return {
        "data_root": str(_data_root()),
        "symbol_filter": symbol or None,
        "returned": len(found),
        "blocks": found,
    }


# ── Tool 7: Pulse History ──────────────────────────────────────────────────

@mcp.tool()
async def get_pulse_history(symbol: str, limit: int = 20) -> dict:
    """Get the pulse history (confluence time-series) for a trading symbol.

    Args:
        symbol: Full trading pair, e.g. 'BTCUSDT' or 'XAUTUSDT'
        limit: Max entries to return (default 20, capped by the daemon's
               `sniper.heartbeat.pulse_history_max_entries`)

    Each entry has `at` plus confluence_score, threshold and direction.
    The file holds the most recent run and is preserved after shutdown, so this
    also works once the daemon has stopped.
    """
    cap = _history_max()
    limit = max(1, min(limit, cap))
    history = _read_json(_history_path())
    if history is None:
        return {
            "error": "pulse history not available — no run has produced one yet",
            "data_root": str(_data_root()),
        }
    if not isinstance(history, list):
        return {"error": "pulse history data corrupted — expected list"}

    entries = []
    for entry in history:
        if not isinstance(entry, dict):
            continue
        sym_data = entry.get("symbols", {}).get(symbol)
        if sym_data is not None:
            entries.append({"at": entry.get("at"), **sym_data})

    return {
        "symbol": symbol,
        "cap": cap,
        "total_entries": len(entries),
        "returned": min(len(entries), limit),
        "history": entries[-limit:],
    }


# ── Run ────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    mcp.run()
