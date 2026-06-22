"""API endpoints for starting/stopping the Sniper daemon."""

import json
import os
import subprocess
import sys
import logging
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Query, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/api/sniper")

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
STATUS_FILENAME = ".sniper_status.json"
log = logging.getLogger("SniperRunAPI")


# ── Models ──────────────────────────────────────────────────────────────

class SniperStartRequest(BaseModel):
    symbol_prefix: str
    trade: bool = False
    balance: float | None = None


# ── Helpers ─────────────────────────────────────────────────────────────

def _resolve_data_root(value: str) -> str:
    return value or os.environ.get("SINGULARITY_DATA_ROOT", "data/prod")


def _read_sniper_status(data_root: str) -> dict | None:
    path = Path(data_root) / STATUS_FILENAME
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except Exception:
        return None


def _write_sniper_status(data_root: str, status: dict) -> None:
    path = Path(data_root) / STATUS_FILENAME
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(status, default=str))
    tmp.replace(path)


def _is_pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False


def _check_email_available() -> bool:
    return bool(os.environ.get("EMAIL_ADDRESS") and os.environ.get("EMAIL_APP_PASSWORD"))


# ── Endpoints ───────────────────────────────────────────────────────────

@router.post("/start")
def sniper_start(req: SniperStartRequest, data_root: str = Query("")):
    """Start the Sniper daemon for the given symbol prefix."""
    data_root = _resolve_data_root(data_root)

    # Validate symbol
    raw = (req.symbol_prefix or "").strip()
    if not raw or len(raw) < 2 or not raw.isalnum():
        raise HTTPException(
            status_code=400,
            detail="Invalid symbol prefix — must be ≥2 alphanumeric characters",
        )
    symbol = raw.upper() + "USDT"

    # Singleton check
    status = _read_sniper_status(data_root)
    if status and status.get("running"):
        pid = status.get("pid")
        if pid and _is_pid_alive(pid):
            started = status.get("started_at", "unknown")
            raise HTTPException(
                status_code=409,
                detail=f"Sniper already running: {status.get('symbol', '?')} (started {started})",
            )
        log.warning("Clearing stale sniper lock for dead PID %s", pid)

    # Balance: null / <= 0 → omit
    balance = req.balance
    if balance is not None and balance <= 0:
        balance = None

    # Build command
    cmd = [
        sys.executable, "run.py", "sniper",
        "--symbol", symbol,
        "--trigger",
        "-p", data_root,
    ]
    if _check_email_available():
        cmd.append("--email")
    if req.trade:
        cmd.append("--trade")
    if balance is not None:
        cmd.extend(["-b", str(balance)])

    log.info("Starting sniper: %s", " ".join(cmd))

    proc = subprocess.Popen(cmd, cwd=str(PROJECT_ROOT))

    _write_sniper_status(data_root, {
        "running": True,
        "symbol": symbol,
        "pid": proc.pid,
        "trade_enabled": req.trade,
        "balance": balance,
        "started_at": datetime.now(timezone.utc).isoformat(),
    })

    return {"accepted": True, "symbol": symbol}


@router.post("/stop")
def sniper_stop(data_root: str = Query("")):
    """Stop the running Sniper daemon."""
    data_root = _resolve_data_root(data_root)

    status = _read_sniper_status(data_root)
    if not status or not status.get("running"):
        raise HTTPException(status_code=404, detail="No sniper is running")

    pid = status.get("pid")
    symbol = status.get("symbol", "?")

    if pid and _is_pid_alive(pid):
        try:
            os.kill(pid, 15)  # SIGTERM
            log.info("Sent SIGTERM to sniper PID %s (%s)", pid, symbol)
        except OSError as e:
            log.error("Failed to kill sniper PID %s: %s", pid, e)
    else:
        log.warning("Sniper PID %s was already dead — clearing lock", pid)

    _write_sniper_status(data_root, {"running": False})
    return {"stopped": True, "symbol": symbol}


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
    elapsed = 0
    if started_str:
        try:
            started = datetime.fromisoformat(started_str.replace("Z", "+00:00"))
            elapsed = (datetime.now(timezone.utc) - started).total_seconds()
        except Exception:
            pass

    return {
        "running": True,
        "symbol": status.get("symbol", ""),
        "trade_enabled": status.get("trade_enabled", False),
        "balance": status.get("balance"),
        "started_at": started_str,
        "elapsed_seconds": round(elapsed),
        "guardian": _read_guardian_status(data_root),
    }


def _read_guardian_status(data_root: str) -> dict | None:
    """Read the guardian pulse file written by the sniper daemon."""
    path = Path(data_root) / ".sniper_guardian.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except Exception:
        return None
