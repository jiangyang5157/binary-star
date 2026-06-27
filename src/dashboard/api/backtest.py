"""API endpoints for triggering and monitoring backtest sessions."""

import json
import threading
import logging
from datetime import datetime, timezone

from src.utils.progress_utils import add_activity_entry, ACTIVE, COMPLETE, ERROR
from pathlib import Path

from fastapi import APIRouter, Query, HTTPException, Depends
from pydantic import BaseModel

router = APIRouter(prefix="/api/backtest")


def _require(perm: str):
    import json
    _users_path = Path(__file__).resolve().parent.parent.parent.parent / "config" / "auth" / "users.json"

    def checker(user: str = Query(None)):
        perms: set[str] = set()
        if _users_path.exists():
            try:
                cfg = json.loads(_users_path.read_text())
            except json.JSONDecodeError:
                cfg = {}
            roles = cfg.get("roles", {})
            users_data = cfg.get("users", {})
            role_key = users_data.get(user, {}).get("role", "") if user else ""
            role = roles.get(role_key, roles.get("anonymous", {}))
            perms = set(role.get("permissions", []))
        if perm not in perms:
            raise HTTPException(status_code=403, detail=f"Missing permission: {perm}")
    return checker

log = logging.getLogger("BacktestAPI")

STATUS_FILENAME = ".backtest_status.json"
MAX_LOOKBACK_DAYS = 28


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
    tmp.write_text(json.dumps(status, default=str))
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


# ── Run ID tracking ─────────────────────────────────────────────────────

_run_id_lock = threading.Lock()
_next_run_id = 0


def _next_id() -> int:
    global _next_run_id
    with _run_id_lock:
        _next_run_id += 1
        return _next_run_id


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
    earliest = now - __import__("datetime").timedelta(days=MAX_LOOKBACK_DAYS)
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
        from src.config.loader import load_strategy_config

        strategy_cfg = load_strategy_config()
        macro_interval = strategy_cfg.get(
            "analysis_window", {}
        ).get("macro_context", {}).get("time_interval", "15m")

        # Calculate warmup for indicators
        topo_cfg = strategy_cfg.get("topography_parameters", {})
        indicators = topo_cfg.get("indicators", {})
        ema_period = indicators.get("exponential_moving_average_period", 200)
        atr_period = indicators.get("average_true_range_period", 14)
        fir_period = strategy_cfg.get("analysis_window", {}).get(
            "macro_context", {}
        ).get("lookback_candles", 500)

        # Warmup = max(ema, atr) + fir (same as run_session.py)
        warmup = max(ema_period, atr_period) + fir_period

        range_seconds = (end_dt - start_dt).total_seconds()
        interval_seconds = get_interval_seconds(macro_interval)
        limit = int(range_seconds / interval_seconds) + warmup

        from src.infrastructure.binance.client import (
            BinanceFuturesClient,
        )
        from src.analyzer.simulation_sampler import SniperSampler
        from src.infrastructure.exchange.models import KlineData

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

def _run_backtest_in_thread(
    symbol: str,
    data_root: str,
    timestamps: list[str],
    run_id: int,
) -> None:
    """Execute backtest sessions in a background thread, one per timestamp."""
    try:
        from run_session import SessionEngine

        engine = SessionEngine(symbol=symbol, data_root=data_root)

        total = len(timestamps)
        for i, ts in enumerate(timestamps):
            # Check if superseded
            current = _read_status(data_root)
            if not current or current.get("run_id") != run_id:
                log.info(
                    "Backtest run %d superseded — discarding", run_id
                )
                return

            # Update progress: mark this sample as running
            samples_state = (current.get("samples") or [])
            if i < len(samples_state):
                samples_state[i]["status"] = "running"
            _write_status(data_root, {
                **current,
                "samples": samples_state,
                "current_index": i,
            })

            try:
                # ── Progress callback for this sample ──
                # Use default-arg capture to bind i at definition time
                def _bt_progress(stage=None, activity=None, status="running",
                                 stage_label=None, result=None, error=None,
                                 _sample_idx=i):
                    current3 = _read_status(data_root)
                    if not current3 or current3.get("run_id") != run_id:
                        return
                    samples3 = list(current3.get("samples") or [])
                    if _sample_idx >= len(samples3):
                        return
                    now_utc = datetime.now(timezone.utc)
                    started_str3 = current3.get("started_at", "")
                    elapsed3 = 0
                    if started_str3:
                        try:
                            started3 = datetime.fromisoformat(started_str3.replace("Z", "+00:00"))
                            elapsed3 = round((now_utc - started3).total_seconds())
                        except Exception:
                            pass

                    progress = samples3[_sample_idx].get("progress", {})
                    if status == "running":
                        activities = list(progress.get("activities", []))
                        add_activity_entry(activities, activity)
                        progress = {
                            "status": "running",
                            "current_stage": stage if stage is not None else progress.get("current_stage", 1),
                            "stage_label": stage_label or progress.get("stage_label", ""),
                            "activity": activity or progress.get("activity", ""),
                            "elapsed_seconds": elapsed3,
                            "activities": activities,
                        }
                    elif status == "completed":
                        progress = {
                            "status": "completed",
                            "current_stage": 5,
                            "elapsed_seconds": elapsed3,
                            "result": result or {},
                            "activities": progress.get("activities", []),
                        }
                    elif status == "failed":
                        activities = list(progress.get("activities", []))
                        if activity:
                            activities.append({
                                "type": ERROR,
                                "message": activity,
                            })
                        progress = {
                            "status": "failed",
                            "current_stage": stage if stage is not None else progress.get("current_stage", 1),
                            "elapsed_seconds": elapsed3,
                            "error": error or activity or "Unknown error",
                            "activities": activities,
                        }

                    samples3[_sample_idx]["progress"] = progress
                    _write_status(data_root, {**current3, "samples": samples3})

                result = engine.execute_cycle(timestamp_str=ts,
                                              progress_callback=_bt_progress)

                # Mark as completed
                current2 = _read_status(data_root)
                if not current2 or current2.get("run_id") != run_id:
                    return
                samples_state2 = current2.get("samples") or []
                if i < len(samples_state2):
                    samples_state2[i]["status"] = "completed"
                    # Build the session filename from the deterministic archive pattern
                    from src.utils.datetime_utils import sanitize_timestamp
                    samples_state2[i]["session_file"] = f"{symbol}_session_{sanitize_timestamp(ts)}.json"
                _write_status(data_root, {
                    **current2,
                    "samples": samples_state2,
                    "current_index": i,
                    "done_count": i + 1,
                    "elapsed_seconds": _compute_elapsed(current2),
                })
            except Exception as e:
                log.exception(
                    "Backtest sample %d/%d failed for %s", i + 1, total, symbol
                )
                current2 = _read_status(data_root)
                if not current2 or current2.get("run_id") != run_id:
                    return
                samples_state2 = current2.get("samples") or []
                if i < len(samples_state2):
                    samples_state2[i]["status"] = "failed"
                    samples_state2[i]["error"] = str(e)
                _write_status(data_root, {
                    **current2,
                    "samples": samples_state2,
                    "current_index": i,
                    "done_count": i + 1,
                    "elapsed_seconds": _compute_elapsed(current2),
                })

        # All done
        current = _read_status(data_root)
        if current and current.get("run_id") == run_id:
            _write_status(data_root, {
                **current,
                "running": False,
                "elapsed_seconds": _compute_elapsed(current),
            })

    except Exception as e:
        log.exception("Backtest run thread failed for %s", symbol)
        current = _read_status(data_root)
        if current and current.get("run_id") == run_id:
            _write_status(data_root, {
                **current,
                "running": False,
                "error": str(e),
                "elapsed_seconds": _compute_elapsed(current),
            })


def _compute_elapsed(status: dict) -> int:
    started_str = status.get("started_at", "")
    if not started_str:
        return 0
    try:
        started = datetime.fromisoformat(started_str.replace("Z", "+00:00"))
        return round(
            (datetime.now(timezone.utc) - started).total_seconds()
        )
    except Exception:
        return 0


# ── Endpoints ───────────────────────────────────────────────────────────

@router.post("/preview")
def preview(req: BacktestPreviewRequest, data_root: str = Query("")):
    """Validate parameters and return the list of sample timestamps."""
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
        raise HTTPException(status_code=400, detail=str(e))

    if req.mode not in ("timestamp", "range"):
        raise HTTPException(
            status_code=400,
            detail="Mode must be 'timestamp' or 'range'",
        )

    try:
        ts_list = _compute_samples(
            mode=req.mode,
            symbol=symbol,
            timestamp_str=req.timestamp,
            start_str=req.start,
            end_str=req.end,
            samples=req.samples,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        log.exception("Preview failed for %s", req.symbol_prefix)
        raise HTTPException(status_code=500, detail=f"Preview failed: {e}")

    return {
        "mode": req.mode,
        "symbol": symbol,
        "count": len(ts_list),
        "timestamps": ts_list,
    }


@router.post("/run")
def trigger_run(req: BacktestRunRequest, data_root: str = Query(""),
                _=Depends(_require("run_backtest"))):
    """Start a backtest run against the pre-computed sample timestamps."""
    from src.dashboard.api.sessions import _resolve_data_root
    data_root = _resolve_data_root(data_root)

    # Check if already running
    status = _read_status(data_root)
    if status and status.get("running"):
        if not _is_stale(status):
            raise HTTPException(
                status_code=409,
                detail=f"Backtest already in progress: {status.get('symbol', '?')} "
                f"({status.get('done_count', 0)}/{status.get('total_count', '?')})",
            )
        log.warning("Clearing stale backtest lock for run_id %s", status.get("run_id"))

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

    # Build initial sample states
    samples_state = [
        {"index": i + 1, "timestamp": ts, "status": "pending"}
        for i, ts in enumerate(ts_list)
    ]

    run_id = _next_id()
    _write_status(data_root, {
        "running": True,
        "mode": req.mode,
        "symbol": symbol,
        "run_id": run_id,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "total_count": len(ts_list),
        "done_count": 0,
        "current_index": 0,
        "samples": samples_state,
    })

    thread = threading.Thread(
        target=_run_backtest_in_thread,
        args=(symbol, data_root, ts_list, run_id),
        daemon=True,
    )
    thread.start()

    return {
        "accepted": True,
        "symbol": symbol,
        "total_count": len(ts_list),
    }


@router.get("/status")
def get_status(data_root: str = Query("")):
    """Return the current backtest run status."""
    from src.dashboard.api.sessions import _resolve_data_root
    data_root = _resolve_data_root(data_root)

    status = _read_status(data_root)
    if not status:
        return {"running": False}

    # Compute overall summary from samples
    if status and status.get("samples"):
        samples = status["samples"]
        status["overall"] = {
            "total": len(samples),
            "completed": sum(1 for s in samples if s.get("status") == "completed"),
            "running": sum(1 for s in samples if s.get("status") == "running"),
            "failed": sum(1 for s in samples if s.get("status") == "failed"),
            "pending": sum(1 for s in samples if s.get("status") == "pending"),
        }
    else:
        status["overall"] = None

    if status.get("running"):
        if _is_stale(status):
            log.warning("Clearing stale backtest lock for run_id %s", status.get("run_id"))
            _write_status(data_root, {
                **status,
                "running": False,
                "error": "Run timed out — thread likely crashed",
            })
            return {"running": False, "error": "Run timed out — thread likely crashed"}

        elapsed = _compute_elapsed(status)
        return {
            **status,
            "elapsed_seconds": elapsed,
        }

    return status


@router.post("/stop")
def stop_run(data_root: str = Query(""),
             _=Depends(_require("run_backtest"))):
    """Stop the currently running backtest."""
    from src.dashboard.api.sessions import _resolve_data_root
    data_root = _resolve_data_root(data_root)

    status = _read_status(data_root)
    if not status or not status.get("running"):
        raise HTTPException(status_code=404, detail="No backtest is running")

    symbol = status.get("symbol", "?")
    _write_status(data_root, {
        **status,
        "running": False,
        "stopped": True,
    })
    log.info("Backtest stopped for %s", symbol)
    return {"stopped": True, "symbol": symbol}
