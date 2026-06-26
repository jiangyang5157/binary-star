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

router = APIRouter(prefix="/api/sniper")


def _require(perm: str):
    """Reject requests lacking the named permission (matches config/auth/users.json)."""
    import json
    from pathlib import Path
    _users_path = Path(__file__).resolve().parent.parent.parent.parent / "config" / "auth" / "users.json"

    def checker(user: str = Query(None)):
        perms: set[str] = set()
        if _users_path.exists():
            try:
                cfg = json.loads(_users_path.read_text())
            except json.JSONDecodeError:
                cfg = {}
            roles = cfg.get("roles", {})
            users = cfg.get("users", {})
            role_key = users.get(user, {}).get("role", "") if user else ""
            role = roles.get(role_key, roles.get("anonymous", {}))
            perms = set(role.get("permissions", []))
        if perm not in perms:
            raise HTTPException(status_code=403, detail=f"Missing permission: {perm}")
    return checker

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
STATUS_FILENAME = ".sniper_daemon_status.json"
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


def _write_sniper_status(data_root: str, status: dict) -> None:
    path = Path(data_root) / STATUS_FILENAME
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(status, default=str))
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
                 _=Depends(_require("run_sniper"))):
    """Start the Sniper daemon for the given symbol prefix(es)."""
    from src.utils.symbol_utils import resolve_symbols

    data_root = _resolve_data_root(data_root)

    # Validate and resolve symbols (CSV: "BTC,ETH,XAUT")
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
            existing = status.get("symbols", [status.get("symbol", "?")])
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

    proc = subprocess.Popen(cmd, cwd=str(PROJECT_ROOT))

    _write_sniper_status(data_root, {
        "running": True,
        "symbols": symbols,
        "pid": proc.pid,
        "trade_enabled": req.trade,
        "balance": balance,
        "started_at": datetime.now(timezone.utc).isoformat(),
    })

    return {"accepted": True, "symbols": symbols}


@router.post("/stop")
def sniper_stop(data_root: str = Query(""),
                _=Depends(_require("run_sniper"))):
    """Stop the running Sniper daemon."""
    data_root = _resolve_data_root(data_root)

    status = _read_sniper_status(data_root)
    if not status or not status.get("running"):
        raise HTTPException(status_code=404, detail="No sniper is running")

    pid = status.get("pid")
    symbols = status.get("symbols", [status.get("symbol", "?")])

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
    elapsed = 0
    if started_str:
        try:
            started = datetime.fromisoformat(started_str.replace("Z", "+00:00"))
            elapsed = (datetime.now(timezone.utc) - started).total_seconds()
        except Exception:
            pass

    # Backwards-compatible: if old format with "symbol" (single string), wrap in array
    symbols = status.get("symbols")
    if not symbols:
        single = status.get("symbol")
        symbols = [single] if single else []

    # Pulse timer: prefer lightweight heartbeat (always fresh), fall back to
    # heavy heartbeat, then daemon uptime as last resort.
    pulse_seconds = _read_pulse_seconds(data_root, fallback_elapsed=round(elapsed))

    # Active session (AI session triggered by sniper signal)
    active_session = status.get("active_session")
    recent_signals = status.get("recent_signals", [])
    pulse_count = status.get("pulse_count", 0)

    # Next scout countdown (only when idle — no active session)
    next_scout = None
    if active_session is None:
        try:
            from src.utils.pipeline_utils import load_global_config
            gcfg = load_global_config()
            pulse_mins = int(gcfg.get('sniper', {}).get('heartbeat', {}).get('pulse_interval_minutes', 2))
            next_scout = max(0, pulse_mins * 60 - pulse_seconds)
        except Exception:
            pass

    return {
        "running": True,
        "symbols": symbols,
        "trade_enabled": status.get("trade_enabled", False),
        "balance": status.get("balance"),
        "started_at": started_str,
        "elapsed_seconds": round(elapsed),
        "pulse_seconds": pulse_seconds,
        "pulse_count": pulse_count,
        "next_scout_in_seconds": next_scout,
        "active_session": active_session,
        "recent_signals": recent_signals,
        "guardian": _read_guardian_status(data_root),
    }


def _seconds_since_iso(ts: str) -> int | None:
    """Parse an ISO timestamp string and return seconds elapsed since then."""
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return round((datetime.now(timezone.utc) - dt).total_seconds())
    except Exception:
        return None


def _read_pulse_seconds(data_root: str, fallback_elapsed: int = 0) -> int:
    """Seconds since the last daemon pulse, using the most reliable heartbeat.

    Priority: lightweight heartbeat > heavyweight heartbeat > daemon uptime.
    """
    # Try lightweight heartbeat first (zero-API-call, always written)
    light = Path(data_root) / ".sniper_alive.json"
    if light.exists():
        try:
            data = json.loads(light.read_text())
            last_str = data.get("last_pulse_at", "")
            if last_str:
                secs = _seconds_since_iso(last_str)
                if secs is not None:
                    return max(secs, 0)  # clamp negative (clock skew) to zero
        except Exception:
            pass

    # Fall back to heavyweight heartbeat
    heavy = _read_guardian_status(data_root)
    if heavy:
        last_str = heavy.get("last_pulse_at", "")
        if last_str:
            secs = _seconds_since_iso(last_str)
            if secs is not None:
                return max(secs, 0)

    # Last resort: daemon uptime (inaccurate but non-zero proves it's running)
    return fallback_elapsed


def _read_guardian_status(data_root: str) -> dict | None:
    """Read the guardian pulse file written by the sniper daemon."""
    path = Path(data_root) / ".sniper_heartbeat.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except Exception:
        return None
