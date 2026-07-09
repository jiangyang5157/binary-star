"""API endpoints for starting/stopping the Sniper daemon."""

import json
import os
import subprocess
import sys
import logging
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Query, HTTPException, Depends
from pydantic import BaseModel

from src.utils.progress_utils import enrich_progress, elapsed_since_iso

router = APIRouter(prefix="/api/sniper")


from src.dashboard.auth import require_permission

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
STATUS_FILENAME = ".sniper_state.json"
PULSE_FILENAME = ".sniper_pulse.json"
HISTORY_FILENAME = ".sniper_pulse_history.json"
log = logging.getLogger("SniperRunAPI")


# ── Models ──────────────────────────────────────────────────────────────

class SniperStartRequest(BaseModel):
    symbol_prefix: str
    trade: bool = False
    balance: float | None = None
    llm: bool = False  # enable AI session dispatch (--trade implies --llm)


# ── Helpers ─────────────────────────────────────────────────────────────

def _resolve_data_root(value: str) -> str:
    resolved = value or os.environ.get("SINGULARITY_DATA_ROOT", "data/prod")
    if ".." in resolved:
        raise HTTPException(status_code=400, detail="data_root contains path traversal")
    return resolved


def _read_sniper_status(data_root: str) -> dict | None:
    path = Path(data_root) / STATUS_FILENAME
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except Exception:
        return None


def _write_sniper_status(data_root: str, updates: dict) -> None:
    """Read-modify-write .sniper_state.json — preserves fields not in updates."""
    path = Path(data_root) / STATUS_FILENAME
    path.parent.mkdir(parents=True, exist_ok=True)
    current = {}
    if path.exists():
        try:
            current = json.loads(path.read_text())
        except Exception:
            pass
    current.update(updates)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(current, default=str, indent=2))
    tmp.replace(path)


def _is_pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False


# ── Endpoints ───────────────────────────────────────────────────────────

@router.post("/start")
def sniper_start(req: SniperStartRequest, data_root: str = Query(""),
                 _=Depends(require_permission("run_sniper"))):
    """Start the Sniper daemon for the given symbol prefix(es)."""
    from src.utils.symbol_utils import resolve_symbols

    data_root = _resolve_data_root(data_root)

    # Validate and resolve symbols (CSV: "XAUT,BTC")
    raw = (req.symbol_prefix or "").strip()
    try:
        symbols = resolve_symbols(raw)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Singleton check
    status = _read_sniper_status(data_root)
    if status and status.get("running"):
        pid = status.get("pid")
        if pid and _is_pid_alive(pid):
            started = status.get("started_at", "unknown")
            existing = status.get("symbols", [])
            raise HTTPException(
                status_code=409,
                detail=f"Sniper already running: {existing} (started {started})",
            )
        log.warning("Clearing stale sniper lock for dead PID %s", pid)

    # Balance: null / <= 0 → omit
    balance = req.balance
    if balance is not None and balance <= 0:
        balance = None

    # Build command — pass CSV prefix string to daemon (strip quote suffix)
    from src.utils.symbol_utils import get_quote_currency
    quote = get_quote_currency()
    csv_arg = ",".join(s[:s.rfind(quote)] if s.endswith(quote) else s for s in symbols)
    cmd = [
        sys.executable, "run.py", "sniper",
        "--symbol", csv_arg,
        "-p", data_root,
    ]
    if req.llm or req.trade:
        cmd.append("--llm")
    if req.trade:
        if balance is not None:
            cmd.extend(["--trade", str(balance)])
        else:
            cmd.append("--trade")

    log.info("Starting sniper: %s", " ".join(cmd))

    # Clean up stale pulse file from any previous run so the frontend
    # doesn't flash old guardian data / signal state before the first pulse.
    _data_root_path = Path(data_root)
    try:
        (_data_root_path / PULSE_FILENAME).unlink(missing_ok=True)
        (_data_root_path / HISTORY_FILENAME).unlink(missing_ok=True)
    except Exception:
        pass

    proc = subprocess.Popen(cmd, cwd=str(PROJECT_ROOT))

    _write_sniper_status(data_root, {
        "running": True,
        "symbols": symbols,
        "pid": proc.pid,
        "trade_enabled": req.trade,
        "balance": balance,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "last_pulse_at": None,
        "active_session": None,
    })

    return {"accepted": True, "symbols": symbols}


@router.post("/stop")
def sniper_stop(data_root: str = Query(""),
                _=Depends(require_permission("run_sniper"))):
    """Stop the running Sniper daemon."""
    data_root = _resolve_data_root(data_root)

    status = _read_sniper_status(data_root)
    if not status or not status.get("running"):
        raise HTTPException(status_code=404, detail="No sniper is running")

    pid = status.get("pid")
    symbols = status.get("symbols", [])

    if pid and _is_pid_alive(pid):
        try:
            os.kill(pid, 15)  # SIGTERM
            log.info("Sent SIGTERM to sniper PID %s (%s)", pid, symbols)
            # Brief grace period for the process to flush state and exit
            import time
            for _ in range(30):  # up to 3 seconds
                if not _is_pid_alive(pid):
                    log.info("Sniper PID %s terminated cleanly.", pid)
                    break
                time.sleep(0.1)
        except OSError as e:
            log.error("Failed to kill sniper PID %s: %s", pid, e)
    else:
        log.warning("Sniper PID %s was already dead — clearing lock", pid)

    _write_sniper_status(data_root, {"running": False})
    return {"stopped": True, "symbols": symbols}


@router.get("/status")
def sniper_status(data_root: str = Query("")):
    """Return current sniper daemon status."""
    data_root = _resolve_data_root(data_root)

    status = _read_sniper_status(data_root)
    if not status or not status.get("running"):
        return {"running": False}

    pid = status.get("pid")
    if pid and not _is_pid_alive(pid):
        log.warning("Clearing stale sniper lock for dead PID %s", pid)
        _write_sniper_status(data_root, {"running": False})
        return {"running": False}

    started_str = status.get("started_at", "")
    elapsed = elapsed_since_iso(started_str)

    symbols = status.get("symbols", [])

    # Pulse timer: from state file's last_pulse_at (always fresh, zero-API)
    pulse_seconds = _read_pulse_seconds(data_root, fallback_elapsed=round(elapsed))

    # Combined pulse file: guardian + signal diagnostics (single read)
    guardian, pulse_signals = _read_pulse(data_root)
    pulse_history = _read_pulse_history(data_root)

    # Active session (AI session triggered by sniper signal)
    active_session = status.get("active_session")
    if active_session and active_session.get("progress"):
        trig_iso = active_session.get("triggered_at_iso", "")
        if trig_iso:
            active_session["progress"]["elapsed_seconds"] = elapsed_since_iso(trig_iso)
        enrich_progress(active_session["progress"])

    return {
        "running": True,
        "symbols": symbols,
        "trade_enabled": status.get("trade_enabled", False),
        "balance": status.get("balance"),
        "started_at": started_str,
        "elapsed_seconds": round(elapsed),
        "pulse_seconds": pulse_seconds,
        "active_session": active_session,
        "guardian": guardian,
        "pulse_signals": pulse_signals,
        "pulse_history": pulse_history or [],
    }


def _read_pulse_seconds(data_root: str, fallback_elapsed: int = 0) -> int:
    """Seconds since the last daemon pulse, from the state file's last_pulse_at."""
    path = Path(data_root) / STATUS_FILENAME
    if path.exists():
        try:
            data = json.loads(path.read_text())
            last_str = data.get("last_pulse_at", "")
            if last_str:
                return elapsed_since_iso(last_str)
        except Exception:
            pass
    return fallback_elapsed


def _read_pulse(data_root: str) -> tuple[dict | None, dict | None]:
    """Read .sniper_pulse.json, return (guardian_dict, pulse_signals_dict).

    Splits the combined pulse file into the two shapes the frontend expects.
    Returns (None, None) if the file is missing or unreadable.
    """
    path = Path(data_root) / PULSE_FILENAME
    if not path.exists():
        return None, None
    try:
        data = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return None, None

    # Guardian shape: account_balance + per-symbol position/order state
    guardian = {
        "account_balance": data.get("account_balance"),
        "symbols": {},
    }

    # Pulse signals shape: per-symbol signal diagnostics for the frontend
    pulse_signals = {
        "pulse_at": data.get("pulse_at", ""),
        "symbols": {},
    }

    try:
        for sym, entry in data.get("symbols", {}).items():
            if not isinstance(entry, dict):
                continue
            guardian["symbols"][sym] = {
                "net_qty": entry.get("net_qty", 0.0),
                "active_orders": entry.get("active_orders", 0),
            }

            pulse_signals["symbols"][sym] = {
                "triggered": entry.get("triggered", False),
                "confluence_score": entry.get("confluence_score", 0.0),
                "threshold": entry.get("threshold") or 0.0,
                "direction": entry.get("direction", "NEUTRAL"),
                "all_signals": entry.get("signals", []),
                "cooldown_active": entry.get("cooldown_active", False),
                "cooldown_remaining_seconds": entry.get("cooldown_remaining_seconds", 0),
                "gate_reason": entry.get("gate_reason") or "",
            }
    except Exception as e:
        log.warning("pulse entry iteration failed | error=%s", e)

    return guardian, pulse_signals


def _read_pulse_history(data_root: str) -> list | None:
    """Read .sniper_pulse_history.json, return the array or None if missing."""
    path = Path(data_root) / HISTORY_FILENAME
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return None
