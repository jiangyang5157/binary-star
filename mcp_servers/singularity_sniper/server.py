"""
Singularity Sniper State MCP Server.

Read-only exposure of the sniper daemon's on-disk state files
(.sniper_state.json, .sniper_pulse.json, .sniper_pulse_history.json).

Usage:
  python mcp_servers/singularity_sniper/server.py
"""

import json
from pathlib import Path

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("singularity-sniper")

# ── Paths ──────────────────────────────────────────────────────────────────

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_ROOT = PROJECT_ROOT / "data" / "prod"
STATE_PATH = DATA_ROOT / ".sniper_state.json"
PULSE_PATH = DATA_ROOT / ".sniper_pulse.json"
HISTORY_PATH = DATA_ROOT / ".sniper_pulse_history.json"


def _read_json(path: Path) -> dict | list | None:
    """Read a JSON file. Returns None if missing or unreadable."""
    try:
        return json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
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
    balance, started_at, last_pulse_at, and active_session info.
    """
    state = _read_json(STATE_PATH)
    if state is None:
        return {"error": "sniper state not available — daemon may not be running"}
    if not isinstance(state, dict):
        return {"error": "sniper state data corrupted — expected dict"}
    return state


def _read_pulse_or_error() -> tuple[dict | None, dict | None]:
    """Read pulse file. Returns (pulse_dict, error_dict).

    Error dict is non-None when pulse is unavailable, corrupted, or not a dict.
    """
    pulse = _read_json(PULSE_PATH)
    if pulse is None:
        return None, {"error": "pulse data not available — daemon may not be running"}
    if not isinstance(pulse, dict):
        return None, {"error": "pulse data corrupted — expected dict"}
    return pulse, None


# ── Tool 2: Pulse State ────────────────────────────────────────────────────

@mcp.tool()
async def get_pulse_state(symbol: str) -> dict:
    """Get the latest pulse state for a trading symbol.

    Args:
        symbol: Full trading pair, e.g. 'BTCUSDT' or 'XAUTUSDT'

    Returns pulse timestamp, account_balance, and per-symbol fields:
    net_qty, active_orders, triggered, confluence_score, threshold,
    direction, cooldown status, and all 10 signal cards.
    """
    pulse, error = _read_pulse_or_error()
    if error:
        return error

    sym_data, available = _get_symbol_from_pulse(pulse, symbol)
    if sym_data is None:
        return {
            "error": f"symbol '{symbol}' not in pulse snapshot",
            "available_symbols": available,
        }

    return {
        "pulse_at": pulse.get("pulse_at"),
        "account_balance": pulse.get("account_balance"),
        "symbol": symbol,
        **sym_data,
    }


# ── Tool 3: Active Signals ─────────────────────────────────────────────────

@mcp.tool()
async def get_active_signals(symbol: str) -> dict:
    """Get only the currently active signals for a trading symbol.

    Args:
        symbol: Full trading pair, e.g. 'BTCUSDT' or 'XAUTUSDT'

    Returns only the signal cards where is_active is true, plus
    the confluence score, threshold, and direction.
    """
    pulse, error = _read_pulse_or_error()
    if error:
        return error

    sym_data, available = _get_symbol_from_pulse(pulse, symbol)
    if sym_data is None:
        return {
            "error": f"symbol '{symbol}' not in pulse snapshot",
            "available_symbols": available,
        }

    all_signals = sym_data.get("signals", [])
    active = [s for s in all_signals if s.get("is_active")]

    return {
        "pulse_at": pulse.get("pulse_at"),
        "symbol": symbol,
        "confluence_score": sym_data.get("confluence_score"),
        "threshold": sym_data.get("threshold"),
        "direction": sym_data.get("direction"),
        "triggered": sym_data.get("triggered"),
        "active_count": len(active),
        "active_signals": active,
    }


# ── Tool 4: Cooldown Status ────────────────────────────────────────────────

@mcp.tool()
async def get_cooldown_status(symbol: str) -> dict:
    """Get the cooldown status for a trading symbol.

    Args:
        symbol: Full trading pair, e.g. 'BTCUSDT' or 'XAUTUSDT'

    Returns whether cooldown is active, remaining seconds, and gate reason.
    """
    pulse, error = _read_pulse_or_error()
    if error:
        return error

    sym_data, available = _get_symbol_from_pulse(pulse, symbol)
    if sym_data is None:
        return {
            "error": f"symbol '{symbol}' not in pulse snapshot",
            "available_symbols": available,
        }

    return {
        "pulse_at": pulse.get("pulse_at"),
        "symbol": symbol,
        "cooldown_active": sym_data.get("cooldown_active"),
        "cooldown_remaining_seconds": sym_data.get("cooldown_remaining_seconds"),
        "gate_reason": sym_data.get("gate_reason"),
    }


# ── Tool 5: Pulse History ──────────────────────────────────────────────────

@mcp.tool()
async def get_pulse_history(symbol: str, limit: int = 20) -> dict:
    """Get the pulse history for a trading symbol.

    Args:
        symbol: Full trading pair, e.g. 'BTCUSDT' or 'XAUTUSDT'
        limit: Max entries to return (default 20, max 120)

    Returns a time-series of confluence_score, threshold, direction,
    and session_active for each pulse.
    """
    limit = min(limit, 120)
    history = _read_json(HISTORY_PATH)
    if history is None:
        return {"error": "pulse history not available — daemon may not be running"}
    if not isinstance(history, list):
        return {"error": "pulse history data corrupted — expected list"}

    entries = []
    for entry in history:
        sym_data = entry.get("symbols", {}).get(symbol)
        if sym_data is not None:
            entries.append({
                "at": entry.get("at"),
                **sym_data,
            })

    return {
        "symbol": symbol,
        "total_entries": len(entries),
        "returned": min(len(entries), limit),
        "history": entries[-limit:],
    }


# ── Run ────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    mcp.run()
