"""
BinaryStar Admin MCP Server.

Read-only config introspection, prompt inspection, and evolution history.
Imports from existing src/ modules — no new abstractions.

Usage:
  python mcp_servers/binary_star_admin/server.py
"""

import json
import sys
from pathlib import Path

# Ensure project root is on sys.path for src/ imports
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("binary-star-admin")

# ── Paths ──────────────────────────────────────────────────────────────────

DATA_DIR = PROJECT_ROOT / "data"


def _get_prompt_path(module: str) -> Path | None:
    """Resolve a prompt module name to its file path via global_config.yaml."""
    from src.utils.pipeline_utils import load_global_config

    cfg = load_global_config()
    if not cfg:
        return None

    if module == "binary_star":
        rel = cfg.get("binary_star", {}).get("system_instruction", "")
    else:
        rel = cfg.get("llm", {}).get("agents", {}).get(module, {}).get("role_prompt", "")

    if not rel:
        return None
    return PROJECT_ROOT / rel


# ── Helpers ────────────────────────────────────────────────────────────────

def _get_resolved_config(symbol: str) -> dict | None:
    """Resolve effective config for a symbol. Returns None on error."""
    from src.config.symbol_resolver import load_and_resolve_for_symbol
    try:
        return load_and_resolve_for_symbol(symbol)
    except (FileNotFoundError, KeyError, ValueError, TypeError):
        return None


def _sanitize(obj):
    """Recursively convert non-serializable values to strings."""
    if isinstance(obj, dict):
        return {str(k): _sanitize(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_sanitize(v) for v in obj]
    if isinstance(obj, (int, float, str, bool, type(None))):
        return obj
    return str(obj)


# ── Tool 1: Effective Config ───────────────────────────────────────────────

@mcp.tool()
async def get_effective_config(symbol: str) -> dict:
    """Get the fully resolved config for a trading symbol.

    Args:
        symbol: Full trading pair, e.g. 'BTCUSDT' or 'XAUTUSDT'

    Returns the merged config after applying:
    global_config.yaml → strategy_config.yaml → symbol overrides.
    """
    cfg = _get_resolved_config(symbol)
    if cfg is None:
        return {
            "error": f"failed to resolve config for '{symbol}'",
            "hint": "check that the symbol is configured in config/symbol_config.yaml",
        }
    return {"symbol": symbol, "config": _sanitize(cfg)}


# ── Tool 2: Trade Params ───────────────────────────────────────────────────

@mcp.tool()
async def get_symbol_trade_params(symbol: str) -> dict:
    """Get trade execution parameters for a trading symbol.

    Args:
        symbol: Full trading pair, e.g. 'BTCUSDT' or 'XAUTUSDT'

    Returns precision_qty, precision_price, min_order_qty, sl_slippage_buffer.
    """
    from src.config.symbol_resolver import get_symbol_trade_params
    try:
        params = get_symbol_trade_params(symbol)
    except KeyError:
        return {
            "error": f"symbol '{symbol}' not configured",
            "hint": "check config/symbol_config.yaml",
        }
    return {"symbol": symbol, **params}


# ── Tool 3: Read Prompt ────────────────────────────────────────────────────

@mcp.tool()
async def get_prompt(module: str) -> dict:
    """Read a prompt template by module name.

    Args:
        module: One of 'session', 'critic', 'binary_star', 'evolver'

    Returns the raw markdown prompt text.
    """
    if module not in ("session", "critic", "binary_star", "evolver"):
        return {
            "error": f"unknown module '{module}'",
            "available_modules": ["session", "critic", "binary_star", "evolver"],
        }

    path = _get_prompt_path(module)
    if path is None:
        return {"error": f"could not resolve prompt path for '{module}' from global config"}

    try:
        text = path.read_text()
    except FileNotFoundError:
        return {"error": f"prompt file not found: {path}"}

    return {
        "module": module,
        "path": str(path.relative_to(PROJECT_ROOT)),
        "size_bytes": len(text),
        "content": text,
    }


# ── Tool 4: Evolution History ──────────────────────────────────────────────

@mcp.tool()
async def get_evolution_history(symbol: str, limit: int = 20) -> dict:
    """Get evolution proposal history for a trading symbol.

    Args:
        symbol: Full trading pair, e.g. 'BTCUSDT' or 'XAUTUSDT'
        limit: Max proposals to return (default 20)

    Scans all data directories recursively for evolution proposals.
    Returns metadata, rationale, config_patch, and semantic_refinement
    for each proposal.
    """
    limit = min(limit, 100)
    proposals = []

    for path in sorted(DATA_DIR.rglob("evolution/proposals/*.json")):
        # Filename format: {SYMBOL}_evolution_{YYYYMMDD_HHMMSS}.json
        if not path.name.startswith(f"{symbol}_evolution_"):
            continue

        try:
            data = json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            continue

        meta = data.get("metadata", {})
        proposals.append({
            "file": path.name,
            "evolved_at": meta.get("evolver_at", ""),
            "audit_reports": meta.get("audit_reports", []),
            "rationale": data.get("rationale", ""),
            "config_patch": data.get("config_patch", []),
            "semantic_refinement": data.get("semantic_refinement", []),
        })

    return {
        "symbol": symbol,
        "total_proposals": len(proposals),
        "returned": min(len(proposals), limit),
        "proposals": proposals[-limit:],
    }


# ── Tool 5: List Symbols ───────────────────────────────────────────────────

@mcp.tool()
async def list_configured_symbols() -> dict:
    """List all trading symbols configured in the system.

    Returns symbol names and their trade parameters.
    """
    from src.config.symbol_resolver import list_configured_symbols, get_symbol_trade_params

    symbols = list_configured_symbols()
    result = {}
    for sym in symbols:
        try:
            result[sym] = get_symbol_trade_params(sym)
        except KeyError:
            result[sym] = {"error": "params unavailable"}

    return {
        "count": len(symbols),
        "symbols": result,
    }


# ── Run ────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    mcp.run()
