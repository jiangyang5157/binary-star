"""API endpoints for triggering on-demand session runs."""

import json
import threading
import logging
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Query, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/api/session")


# ── Models ──────────────────────────────────────────────────────────────

class RunRequest(BaseModel):
    symbol_prefix: str


# ── Status file helpers ─────────────────────────────────────────────────

STATUS_FILENAME = ".session_run_status.json"
log = logging.getLogger("SessionRunAPI")


def _read_status(data_root: str) -> dict | None:
    """Read the run status file. Returns None if missing or corrupt."""
    path = Path(data_root) / STATUS_FILENAME
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except Exception:
        return None


def _write_status(data_root: str, status: dict) -> None:
    """Atomically write the run status file."""
    path = Path(data_root) / STATUS_FILENAME
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(status, default=str))
    tmp.replace(path)



# ── Stale-lock timeout ──────────────────────────────────────────────────

# If a run status hasn't been updated in this many seconds, it's
# assumed to have crashed (background thread died without cleanup).
STALE_TIMEOUT_SECONDS = 3600  # 1 hour


def _is_stale(status: dict) -> bool:
    """Check whether a run status has exceeded the staleness timeout."""
    started_str = status.get("started_at", "")
    if not started_str:
        return True
    try:
        started = datetime.fromisoformat(started_str)
        elapsed = (datetime.now(timezone.utc) - started).total_seconds()
        return elapsed > STALE_TIMEOUT_SECONDS
    except Exception:
        return True


# ── Run ID tracking (prevents stale-thread races on stop/restart) ──────

_run_id_lock = threading.Lock()
_next_run_id = 0


def _next_id() -> int:
    global _next_run_id
    with _run_id_lock:
        _next_run_id += 1
        return _next_run_id


# ── Background runner ───────────────────────────────────────────────────

def _run_session_in_thread(symbol: str, data_root: str, run_id: int) -> None:
    """Execute a session cycle in a background thread. Updates status file on
    completion only if no newer run has been started (checked via run_id)."""
    try:
        from run_session import SessionEngine

        engine = SessionEngine(
            symbol=symbol,
            data_root=data_root,
        )
        result = engine.execute_cycle(timestamp_str=None)

        # Only write completion if this run hasn't been superseded
        current = _read_status(data_root)
        if not current or current.get("run_id") != run_id:
            log.info("Run %d for %s completed but was superseded — discarding result", run_id, symbol)
            return

        if result and "error" in result:
            _write_status(data_root, {
                "running": False,
                "run_id": run_id,
                "last_run": {
                    "symbol": symbol,
                    "result": "error",
                    "error_message": str(result["error"]),
                    "at": datetime.now(timezone.utc).isoformat(),
                },
            })
        else:
            _write_status(data_root, {
                "running": False,
                "run_id": run_id,
                "last_run": {
                    "symbol": symbol,
                    "result": "success",
                    "at": datetime.now(timezone.utc).isoformat(),
                },
            })
    except Exception as e:
        log.exception("Session run thread failed for %s", symbol)
        current = _read_status(data_root)
        if not current or current.get("run_id") != run_id:
            return
        _write_status(data_root, {
            "running": False,
            "run_id": run_id,
            "last_run": {
                "symbol": symbol,
                "result": "error",
                "error_message": str(e),
                "at": datetime.now(timezone.utc).isoformat(),
            },
        })


# ── Endpoints ───────────────────────────────────────────────────────────

@router.post("/run")
def trigger_run(req: RunRequest, data_root: str = Query("")):
    """Trigger a one-time session run for the given symbol prefix.

    Uppercases the prefix and appends 'USDT' to form the symbol.
    Only one run is allowed at a time — returns 409 if busy.
    """
    from src.dashboard.api.sessions import _resolve_data_root
    data_root = _resolve_data_root(data_root)

    # Validate and construct symbol
    raw = (req.symbol_prefix or "").strip()
    if not raw or len(raw) < 2 or not raw.isalnum():
        raise HTTPException(status_code=400, detail="Invalid symbol prefix — must be ≥2 alphanumeric characters")

    symbol = raw.upper() + "USDT"

    # Check current status
    status = _read_status(data_root)
    if status and status.get("running"):
        if not _is_stale(status):
            started = status.get("started_at", "unknown")
            raise HTTPException(
                status_code=409,
                detail=f"Run already in progress: {status.get('symbol', '?')} (started {started})",
            )
        # Stale lock — run timed out, proceed
        log.warning("Clearing stale lock for run_id %s", status.get("run_id"))

    # Write running status with unique run_id for stale-thread guard
    run_id = _next_id()
    _write_status(data_root, {
        "running": True,
        "symbol": symbol,
        "run_id": run_id,
        "started_at": datetime.now(timezone.utc).isoformat(),
    })

    # Spawn background thread
    thread = threading.Thread(
        target=_run_session_in_thread,
        args=(symbol, data_root, run_id),
        daemon=True,
    )
    thread.start()

    return {"accepted": True, "symbol": symbol}


@router.post("/stop")
def stop_run(data_root: str = Query("")):
    """Stop the currently running session. The background thread will still
    complete, but its result is discarded via run_id tracking."""
    from src.dashboard.api.sessions import _resolve_data_root
    data_root = _resolve_data_root(data_root)

    status = _read_status(data_root)
    if not status or not status.get("running"):
        raise HTTPException(status_code=404, detail="No session is running")

    symbol = status.get("symbol", "?")
    _write_status(data_root, {"running": False, "last_run": None})
    log.info("Session run stopped for %s", symbol)
    return {"stopped": True, "symbol": symbol}


@router.get("/run-status")
def get_run_status(data_root: str = Query("")):
    """Return the current run status (running/idle, last run info)."""
    from src.dashboard.api.sessions import _resolve_data_root
    data_root = _resolve_data_root(data_root)

    status = _read_status(data_root)
    if not status:
        return {"running": False, "last_run": None}

    if status.get("running"):
        if _is_stale(status):
            # Stale lock — run timed out, clear it
            log.warning("Clearing stale lock for run_id %s", status.get("run_id"))
            _write_status(data_root, {"running": False, "last_run": None})
            return {"running": False, "last_run": None}

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
            "started_at": started_str,
            "elapsed_seconds": round(elapsed),
        }

    return {
        "running": False,
        "last_run": status.get("last_run"),
    }
