"""API endpoints for triggering on-demand session runs.

Spawning a subprocess (``run.py session --write_status``) rather than a
daemon thread so that :ref:`stop_run` can actually kill the session with
SIGTERM instead of merely flagging it — matching the behaviour of
``Ctrl+C`` in the CLI and of the Sniper stop endpoint.
"""

import os
import signal
import subprocess
import sys
import time
import logging
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Query, HTTPException, Depends
from pydantic import BaseModel

from src.utils.progress_utils import enrich_progress, elapsed_since_iso
from src.utils.status_file_utils import read_status as _read_status, write_status as _write_status

router = APIRouter(prefix="/api/session")

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent


from src.dashboard.auth import require_permission

# ── Models ──────────────────────────────────────────────────────────────

class RunRequest(BaseModel):
    symbol_prefix: str


log = logging.getLogger("SessionRunAPI")


def _is_pid_alive(pid: int) -> bool:
    """Check whether a process is still running."""
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False


# ── Endpoints ───────────────────────────────────────────────────────────

@router.post("/run")
def trigger_run(req: RunRequest, data_root: str = Query(""),
                _=Depends(require_permission("run_new_session"))):
    """Trigger a one-time session run for the given symbol prefix.

    Spawns ``run.py session --write_status`` as an independent subprocess so
    that :ref:`stop_run` can kill it with SIGTERM.

    Only one run is allowed at a time — returns 409 if busy.
    """
    from src.dashboard.api.sessions import _resolve_data_root
    from src.utils.symbol_utils import get_quote_currency
    data_root = _resolve_data_root(data_root)

    # Validate and construct symbol
    raw = (req.symbol_prefix or "").strip()
    if not raw or len(raw) < 2 or not raw.isalnum():
        raise HTTPException(status_code=400, detail="Invalid symbol prefix — must be ≥2 alphanumeric characters")

    symbol = raw.upper() + get_quote_currency()

    # Singleton check — reject if a session is already running
    status = _read_status(data_root)
    if status and status.get("running"):
        pid = status.get("pid")
        if pid and _is_pid_alive(pid):
            started = status.get("started_at", "unknown")
            raise HTTPException(
                status_code=409,
                detail=f"Run already in progress: {status.get('symbol', '?')} (started {started})",
            )
        # PID is dead — stale lock, clear it and proceed
        log.warning("Clearing stale session lock for dead PID %s", pid)

    # Spawn subprocess (like Sniper does)
    cmd = [
        sys.executable, "run.py", "session",
        "--symbol", raw.upper(),
        "--write_status",
        "-p", data_root,
    ]

    # Write initial status *before* Popen so the subprocess's first progress
    # callback always finds the status file.  pid is None until Popen returns;
    # the subprocess only reads/writes "progress" and "started_at", never "pid".
    _write_status(data_root, {
        "running": True,
        "symbol": symbol,
        "pid": None,
        "started_at": datetime.now(timezone.utc).isoformat(),
    })

    log.info("Starting session subprocess: %s", " ".join(cmd))
    proc = subprocess.Popen(cmd, cwd=str(PROJECT_ROOT))

    # Patch in the real PID
    status = _read_status(data_root)
    if status is not None:
        status["pid"] = proc.pid
        _write_status(data_root, status)

    return {"accepted": True, "symbol": symbol}


@router.post("/stop")
def stop_run(data_root: str = Query(""),
             _=Depends(require_permission("run_new_session"))):
    """Stop the currently running session by sending SIGTERM to its subprocess.

    Escalates to SIGKILL if the process does not exit within ~0.5 s, then
    writes the final status so the frontend can display the last-known
    progress.
    """
    from src.dashboard.api.sessions import _resolve_data_root
    data_root = _resolve_data_root(data_root)

    status = _read_status(data_root)
    if not status or not status.get("running"):
        raise HTTPException(status_code=404, detail="No session is running")

    symbol = status.get("symbol", "?")
    pid = status.get("pid")

    if pid and _is_pid_alive(pid):
        try:
            # Graceful shutdown via SIGTERM — SessionController catches it
            os.kill(pid, signal.SIGTERM)
            log.info("Sent SIGTERM to session PID %s (%s)", pid, symbol)
            for _ in range(5):  # ~0.5 s grace period
                if not _is_pid_alive(pid):
                    log.info("Session PID %s terminated cleanly.", pid)
                    break
                time.sleep(0.1)
            else:
                # Process didn't respond to SIGTERM — force kill
                log.warning("Session PID %s did not exit after SIGTERM, sending SIGKILL", pid)
                os.kill(pid, signal.SIGKILL)
                for _ in range(5):
                    if not _is_pid_alive(pid):
                        log.info("Session PID %s killed.", pid)
                        break
                    time.sleep(0.1)
        except OSError as e:
            log.error("Failed to kill session PID %s: %s", pid, e)
    else:
        log.warning("Session PID %s was already dead — clearing lock", pid)

    # Preserve the last progress snapshot so the frontend can render it
    current = _read_status(data_root)
    progress = current.get("progress") if current else None
    if progress and isinstance(progress, dict):
        progress["status"] = "stopped"

    _write_status(data_root, {
        "running": False,
        "last_run": {
            "symbol": symbol,
            "result": "stopped",
            "at": datetime.now(timezone.utc).isoformat(),
        },
        "progress": progress,
    })
    return {"stopped": True, "symbol": symbol}


@router.get("/run-status")
def get_run_status(data_root: str = Query("")):
    """Return the current run status (running/idle, last run info).

    If the status file claims *running* but the subprocess PID is dead,
    the lock is considered stale and is cleared automatically.
    """
    from src.dashboard.api.sessions import _resolve_data_root
    data_root = _resolve_data_root(data_root)

    status = _read_status(data_root)
    if not status:
        return {"running": False, "last_run": None}

    if status.get("running"):
        pid = status.get("pid")
        if pid and not _is_pid_alive(pid):
            # Subprocess died without writing completion — treat as stale lock
            log.warning("Clearing stale session lock for dead PID %s", pid)
            progress = status.get("progress")
            _write_status(data_root, {
                "running": False,
                "last_run": {
                    "symbol": status.get("symbol", ""),
                    "result": "error",
                    "error_message": "Subprocess died unexpectedly",
                    "at": datetime.now(timezone.utc).isoformat(),
                },
                "progress": progress,
            })
            return {
                "running": False,
                "last_run": status.get("last_run"),
                "progress": enrich_progress(progress),
            }

        started_str = status.get("started_at", "")
        elapsed = elapsed_since_iso(started_str)

        progress = status.get("progress")
        if progress:
            progress["elapsed_seconds"] = elapsed

        return {
            "running": True,
            "symbol": status.get("symbol", ""),
            "started_at": started_str,
            "elapsed_seconds": elapsed,
            "progress": enrich_progress(progress),
        }

    return {
        "running": False,
        "last_run": status.get("last_run"),
        "progress": enrich_progress(status.get("progress")),
    }
