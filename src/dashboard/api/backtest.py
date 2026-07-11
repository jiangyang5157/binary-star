"""API endpoints for triggering and monitoring backtest sessions."""

import json
import os
import signal
import subprocess
import sys
import time
import logging
from datetime import datetime, timezone, timedelta

from src.utils.progress_utils import enrich_progress, elapsed_since_iso
from pathlib import Path

from fastapi import APIRouter, Query, HTTPException, Depends
from pydantic import BaseModel

router = APIRouter(prefix="/api/backtest")


from src.dashboard.auth import require_permission

log = logging.getLogger("BacktestAPI")

STATUS_FILENAME = ".backtest_status.json"
MAX_LOOKBACK_DAYS = 28
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent


# ── Models ──────────────────────────────────────────────────────────────

class BacktestPreviewRequest(BaseModel):
    mode: str  # "timestamp" or "range"
    symbol_prefix: str
    timestamp: str | None = None
    start: str | None = None
    end: str | None = None
    samples: int | None = None


class BacktestRunRequest(BaseModel):
    mode: str
    symbol_prefix: str
    timestamp: str | None = None
    start: str | None = None
    end: str | None = None
    samples: int | None = None
    # Pre-computed sample timestamps from preview
    sample_timestamps: list[str]


# ── Status helpers ──────────────────────────────────────────────────────

def _status_path(data_root: str) -> Path:
    return Path(data_root) / STATUS_FILENAME


def _read_status(data_root: str) -> dict | None:
    path = _status_path(data_root)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except Exception:
        return None


def _write_status(data_root: str, status: dict) -> None:
    path = _status_path(data_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(status, default=str, indent=2))
    tmp.replace(path)


# ── Stale-lock timeout ──────────────────────────────────────────────────

# Backtests can take longer than single sessions — use a generous timeout.
BACKTEST_STALE_TIMEOUT_SECONDS = 7200  # 2 hours


def _is_stale(status: dict) -> bool:
    """Check whether a backtest run status has exceeded the staleness timeout."""
    started_str = status.get("started_at", "")
    if not started_str:
        return True
    try:
        started = datetime.fromisoformat(started_str)
        elapsed = (datetime.now(timezone.utc) - started).total_seconds()
        return elapsed > BACKTEST_STALE_TIMEOUT_SECONDS
    except Exception:
        return True


# ── Date helpers ────────────────────────────────────────────────────────

def _parse_date(date_str: str) -> datetime:
    """Thin wrapper around parse_flexible_date with friendlier errors."""
    from src.utils.datetime_utils import parse_flexible_date

    if not date_str or not date_str.strip():
        raise ValueError("Date string is empty")
    try:
        return parse_flexible_date(date_str.strip())
    except ValueError:
        raise  # re-raise as-is
    except Exception as e:
        raise ValueError(f"Invalid date '{date_str}': {e}")


def _validate_date_window(dt: datetime, now: datetime) -> None:
    """Ensure dt is not earlier than MAX_LOOKBACK_DAYS ago."""
    earliest = now - timedelta(days=MAX_LOOKBACK_DAYS)
    if dt < earliest:
        raise ValueError(
            f"Date {dt.strftime('%Y-%m-%d %H:%M')} UTC is earlier than "
            f"the {MAX_LOOKBACK_DAYS}-day window "
            f"(earliest: {earliest.strftime('%Y-%m-%d %H:%M')} UTC)"
        )


def _resolve_symbol(prefix: str) -> str:
    from src.utils.symbol_utils import resolve_symbol
    return resolve_symbol(prefix.strip())


# ── Preview: compute sample timestamps ──────────────────────────────────

def _compute_samples(
    mode: str,
    symbol: str,
    timestamp_str: str | None,
    start_str: str | None,
    end_str: str | None,
    samples: int | None,
) -> list[str]:
    """Compute the list of sample timestamps. Raises ValueError on bad input."""
    now = datetime.now(timezone.utc)

    if mode == "timestamp":
        if not timestamp_str:
            raise ValueError("Timestamp is required for single-timestamp mode")
        dt = _parse_date(timestamp_str)
        _validate_date_window(dt, now)
        from src.utils.datetime_utils import to_iso_zulu
        return [to_iso_zulu(dt)]

    if mode == "range":
        if not start_str:
            raise ValueError("Start date is required for date-range mode")
        if not end_str:
            raise ValueError("End date is required for date-range mode")
        if not samples or samples < 1:
            raise ValueError("Samples must be ≥ 1")

        start_dt = _parse_date(start_str)
        end_dt = _parse_date(end_str)

        _validate_date_window(start_dt, now)
        _validate_date_window(end_dt, now)

        if start_dt >= end_dt:
            raise ValueError("Start date must be before end date")

        # Fetch klines and run SniperSampler
        from src.utils.datetime_utils import get_interval_seconds
        from src.utils.pipeline_utils import load_combined_config

        strategy_cfg = load_combined_config()
        macro_interval = strategy_cfg.get(
            "analysis_window", {}
        ).get("macro_context", {}).get("time_interval", "15m")

        # Calculate warmup for indicators (must match run_backtest.py:_sample_batch)
        from src.utils.market_utils import calculate_indicator_warmup

        topo_cfg = strategy_cfg.get("topography_parameters", {})
        indicators = topo_cfg.get("indicators", {})
        fir_period = strategy_cfg.get("analysis_window", {}).get(
            "macro_context", {}
        ).get("lookback_candles", 500)

        warmup = calculate_indicator_warmup(
            iir_periods=[
                indicators.get("exponential_moving_average_period", 200),
                indicators.get("average_true_range_period", 14),
            ],
            fir_periods=[fir_period],
        )

        range_seconds = (end_dt - start_dt).total_seconds()
        interval_seconds = get_interval_seconds(macro_interval)
        limit = int(range_seconds / interval_seconds) + warmup

        from src.infrastructure.binance.client import BinanceFuturesClient
        from src.analyzer.simulation_sampler import SniperSampler

        binance = BinanceFuturesClient()
        try:
            klines_raw = binance.fetch_historical_klines(
                symbol=symbol,
                interval=macro_interval,
                limit=limit,
                startTime=int(start_dt.timestamp() * 1000)
                - (warmup * interval_seconds * 1000),
                endTime=int(end_dt.timestamp() * 1000),
            )
        finally:
            binance.close()

        # Filter to the requested range
        klines_range = [
            k
            for k in klines_raw
            if start_dt
            <= datetime.fromtimestamp(k.open_time / 1000, tz=timezone.utc)
            <= end_dt
        ]

        if not klines_range:
            raise ValueError(
                "No kline data available in the specified date range"
            )

        sampler = SniperSampler(symbol)
        timestamps = sampler.sample(klines_range, samples)

        if not timestamps:
            raise ValueError("SniperSampler returned no timestamps")

        from src.utils.datetime_utils import to_iso_zulu
        return [to_iso_zulu(dt) for dt in timestamps]

    raise ValueError(f"Unknown mode: '{mode}'")


# ── Background runner ───────────────────────────────────────────────────

def _is_pid_alive(pid: int) -> bool:
    """Check whether a process is still running."""
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False



# ── Endpoints ───────────────────────────────────────────────────────────

@router.post("/preview")
def preview(req: BacktestPreviewRequest, data_root: str = Query(""),
             _=Depends(require_permission("run_backtest"))):
    """Start a background preview subprocess to compute sample timestamps.

    The subprocess writes results to .backtest_status.json.  The frontend
    polls GET /status to track progress and render the sample list.
    """
    from src.dashboard.api.sessions import _resolve_data_root
    data_root = _resolve_data_root(data_root)

    # Validate and construct symbol
    raw = (req.symbol_prefix or "").strip()
    if not raw or len(raw) < 2 or not raw.isalnum():
        raise HTTPException(
            status_code=400,
            detail="Invalid symbol prefix — must be ≥2 alphanumeric characters",
        )

    try:
        symbol = _resolve_symbol(raw)
    except Exception as e:
        log.exception("Symbol resolution failed for prefix=%s", raw)
        raise HTTPException(status_code=400, detail="Symbol resolution failed — check symbol exists in config")

    if req.mode not in ("timestamp", "range"):
        raise HTTPException(
            status_code=400,
            detail="Mode must be 'timestamp' or 'range'",
        )

    # Single-timestamp mode: trivially fast, compute inline
    if req.mode == "timestamp":
        try:
            ts_list = _compute_samples(
                mode=req.mode,
                symbol=symbol,
                timestamp_str=req.timestamp,
                start_str=None,
                end_str=None,
                samples=None,
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except Exception as e:
            log.exception("Preview failed for %s", req.symbol_prefix)
            raise HTTPException(status_code=500, detail="Preview failed")
        # Persist so page refresh can restore
        _write_status(data_root, {
            "running": False,
            "mode": req.mode,
            "symbol": symbol,
            "preview": True,
            "timestamp_value": req.timestamp,
            "samples": [
                {"timestamp": ts, "status": "pending"}
                for ts in ts_list
            ],
        })
        return {
            "mode": req.mode,
            "symbol": symbol,
            "count": len(ts_list),
            "timestamps": ts_list,
        }

    # Date-range mode: spawn subprocess (heavy SniperSampler work, cancellable)
    status = _read_status(data_root)
    if status and status.get("running"):
        if not _is_stale(status):
            raise HTTPException(
                status_code=409,
                detail=f"Backtest already in progress: {status.get('symbol', '?')}",
            )
        log.warning("Clearing stale backtest lock for %s", status.get("symbol", "?"))

    _write_status(data_root, {
        "running": True,
        "mode": req.mode,
        "symbol": symbol,
        "preview": True,
        "pid": None,
        "samples": [],
        "start_value": req.start,
        "end_value": req.end,
        "samples_count": req.samples,
    })

    payload = json.dumps({
        "data_root": data_root,
        "mode": req.mode,
        "symbol": symbol,
        "timestamp": None,
        "start": req.start,
        "end": req.end,
        "samples": req.samples,
    })
    preview_script = str(
        Path(__file__).resolve().parent.parent / "preview_runner.py"
    )
    proc = subprocess.Popen(
        [sys.executable, preview_script],
        stdin=subprocess.PIPE,
        cwd=str(PROJECT_ROOT),
    )
    proc.stdin.write(payload.encode())
    proc.stdin.close()

    status = _read_status(data_root)
    if status is not None:
        status["pid"] = proc.pid
        _write_status(data_root, status)

    log.info("Preview subprocess started: PID %s for %s", proc.pid, symbol)
    return {
        "started": True,
        "symbol": symbol,
        "mode": req.mode,
    }


@router.post("/run")
def trigger_run(req: BacktestRunRequest, data_root: str = Query(""),
                _=Depends(require_permission("run_backtest"))):
    """Start a backtest run against the pre-computed sample timestamps."""
    from src.dashboard.api.sessions import _resolve_data_root
    data_root = _resolve_data_root(data_root)

    # Check if already running
    status = _read_status(data_root)
    if status and status.get("running"):
        if not _is_stale(status):
            raise HTTPException(
                status_code=409,
                detail=f"Backtest already in progress: {status.get('symbol', '?')}",
            )
        log.warning("Clearing stale backtest lock for %s", status.get("symbol", "?"))

    # Validate symbol
    raw = (req.symbol_prefix or "").strip()
    if not raw or len(raw) < 2 or not raw.isalnum():
        raise HTTPException(
            status_code=400,
            detail="Invalid symbol prefix",
        )
    try:
        symbol = _resolve_symbol(raw)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Validate we have timestamps
    ts_list = req.sample_timestamps
    if not ts_list:
        raise HTTPException(
            status_code=400, detail="No sample timestamps provided"
        )

    # Build initial sample states — check for existing session files
    from src.utils.datetime_utils import format_timestamp_for_filename

    sessions_dir = Path(data_root) / "sessions"
    samples_state = []
    for ts in ts_list:
        try:
            compact = format_timestamp_for_filename(ts)
        except Exception:
            compact = None
        session_file = f"{symbol}_session_{compact}.json" if compact else None
        if session_file and (sessions_dir / session_file).exists():
            samples_state.append({"timestamp": ts, "status": "completed"})
        else:
            samples_state.append({"timestamp": ts, "status": "pending"})

    pending = [s for s in samples_state if s["status"] == "pending"]
    if not pending:
        # All samples already have session files — nothing to run
        _done_status = {
            "running": False,
            "mode": req.mode,
            "symbol": symbol,
            "samples": samples_state,
        }
        for _key in ("timestamp_value", "start_value", "end_value", "samples_count"):
            if status and _key in status:
                _done_status[_key] = status[_key]
        _write_status(data_root, _done_status)
        return {
            "all_complete": True,
            "symbol": symbol,
            "samples": samples_state,
        }

    # Write initial status *before* Popen so the subprocess can read it.
    # Preserve raw input values from preview (if any) so they survive refresh
    _run_status = {
        "running": True,
        "mode": req.mode,
        "symbol": symbol,
        "pid": None,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "samples": samples_state,
    }
    for _key in ("timestamp_value", "start_value", "end_value", "samples_count"):
        if status and _key in status:
            _run_status[_key] = status[_key]
    _write_status(data_root, _run_status)

    cmd = [
        sys.executable, "run.py", "backtest-run",
        "--symbol", symbol,
        "--write-status",
        "-p", data_root,
    ]

    log.info("Starting backtest subprocess: %s", " ".join(cmd))
    proc = subprocess.Popen(cmd, cwd=str(PROJECT_ROOT))

    # Patch in the real PID
    status = _read_status(data_root)
    if status is not None:
        status["pid"] = proc.pid
        _write_status(data_root, status)

    return {
        "accepted": True,
        "symbol": symbol,
    }


@router.get("/status")
def get_status(data_root: str = Query("")):
    """Return the current backtest run status."""
    from src.dashboard.api.sessions import _resolve_data_root
    data_root = _resolve_data_root(data_root)

    status = _read_status(data_root)
    if not status:
        return {"running": False}

    # Inject stage config into each sample's progress for frontend rendering.
    # Use per-sample started_at for elapsed (fall back to batch started_at).
    if status.get("samples"):
        for sample in status["samples"]:
            progress = sample.get("progress")
            if progress and progress.get("status") == "running":
                sample_started = sample.get("started_at") or status.get("started_at", "")
                progress["elapsed_seconds"] = elapsed_since_iso(sample_started)
            enrich_progress(progress)

    if status.get("running"):
        pid = status.get("pid")
        # Check PID first (subprocess mode), then fall back to time-based stale check
        if pid and not _is_pid_alive(pid):
            log.warning("Clearing stale backtest lock for dead PID %s (%s)",
                        pid, status.get("symbol", "?"))
            _write_status(data_root, {
                **status,
                "running": False,
                "error": "Subprocess died unexpectedly",
            })
            return {
                "running": False,
                "error": "Subprocess died unexpectedly",
                "mode": status.get("mode"),
                "symbol": status.get("symbol"),
                "samples": status.get("samples"),
            }
        if not pid and _is_stale(status):
            log.warning("Clearing stale backtest lock for %s", status.get("symbol", "?"))
            _write_status(data_root, {
                **status,
                "running": False,
                "error": "Run timed out — thread likely crashed",
            })
            return {
                "running": False,
                "error": "Run timed out — thread likely crashed",
                "mode": status.get("mode"),
                "symbol": status.get("symbol"),
                "samples": status.get("samples"),
            }

    return status


@router.post("/stop")
def stop_run(data_root: str = Query(""),
             _=Depends(require_permission("run_backtest"))):
    """Stop the currently running backtest by sending SIGTERM to its subprocess.

    Escalates to SIGKILL if the process does not exit within ~0.5 s, then
    writes the final status so the frontend can display the last-known
    progress.
    """
    from src.dashboard.api.sessions import _resolve_data_root
    data_root = _resolve_data_root(data_root)

    status = _read_status(data_root)
    if not status or not status.get("running"):
        raise HTTPException(status_code=404, detail="No backtest is running")

    symbol = status.get("symbol", "?")
    pid = status.get("pid")

    if pid and _is_pid_alive(pid):
        try:
            os.kill(pid, signal.SIGTERM)
            log.info("Sent SIGTERM to backtest PID %s (%s)", pid, symbol)
            for _ in range(5):  # ~0.5 s grace period
                if not _is_pid_alive(pid):
                    log.info("Backtest PID %s terminated cleanly.", pid)
                    break
                time.sleep(0.1)
            else:
                log.warning("Backtest PID %s did not exit after SIGTERM, sending SIGKILL", pid)
                os.kill(pid, signal.SIGKILL)
                for _ in range(5):
                    if not _is_pid_alive(pid):
                        log.info("Backtest PID %s killed.", pid)
                        break
                    time.sleep(0.1)
        except OSError as e:
            log.error("Failed to kill backtest PID %s: %s", pid, e)
    else:
        log.warning("Backtest PID %s was already dead — clearing lock", pid)

    # Preserve the last progress snapshot so the frontend can render it
    current = _read_status(data_root)
    _write_status(data_root, {
        **current,
        "running": False,
    })
    return {"stopped": True, "symbol": symbol}
