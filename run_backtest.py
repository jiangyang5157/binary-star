#!/usr/bin/env python3
"""Standalone backtest runner — spawned as a subprocess by the dashboard API.

Reads sample timestamps from ``.backtest_status.json`` (written by the
``/api/backtest/run`` endpoint) and executes one ``SessionEngine`` cycle
per timestamp, writing progress updates back to the status file so the
frontend can poll ``/api/backtest/status``.

SIGTERM / SIGINT are handled so that :ref:`/api/backtest/stop` can kill
the subprocess cleanly — matching the contract used by ``run.py session``
and ``run.py sniper``.
"""

import argparse
import json
import logging
import os
import signal
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv()

from src.utils.logger_utils import setup_logger
from src.utils.progress_utils import add_activity_entry, ERROR

STATUS_FILENAME = ".backtest_status.json"
logger = setup_logger("BacktestRunner", console_color=True)


# ── Status-file helpers (self-contained to avoid coupling to the API module) ──

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


def _compute_elapsed(status: dict) -> int:
    started_str = status.get("started_at", "")
    if not started_str:
        return 0
    try:
        started = datetime.fromisoformat(started_str.replace("Z", "+00:00"))
        return round((datetime.now(timezone.utc) - started).total_seconds())
    except Exception:
        return 0


# ── Main runner ────────────────────────────────────────────────────────────

class BacktestRunner:
    """Runs historical session cycles — dashboard mode (with status file) or CLI mode."""

    def __init__(self, args: argparse.Namespace):
        self.args = args
        self.data_root: str = args.path
        self.symbol: str = args.symbol.upper()
        self.run_id: int | None = args.run_id
        self._write_status = getattr(args, "write_status", False)
        self._setup_signals()

    # ── Signal handling ─────────────────────────────────────────────────

    def _setup_signals(self):
        for sig in (signal.SIGINT, signal.SIGTERM):
            signal.signal(sig, self._handle_termination)

    def _handle_termination(self, signum, frame):
        logger.warning("Termination signal received. Shutting down BacktestRunner...")
        if self.run_id is not None:
            try:
                current = _read_status(self.data_root)
                if current and current.get("run_id") == self.run_id:
                    _write_status(self.data_root, {
                        **current,
                        "running": False,
                        "stopped": True,
                        "elapsed_seconds": _compute_elapsed(current),
                    })
            except Exception as e:
                logger.warning("Failed to write final status during shutdown: %s", e)
        sys.exit(0)

    # ── Timestamp collection ─────────────────────────────────────────────

    def _collect_timestamps(self) -> list[str]:
        """Resolve timestamps based on the active mode."""
        from src.utils.datetime_utils import to_iso_zulu

        # Mode A: Dashboard — read from status file
        if self.run_id is not None:
            current = _read_status(self.data_root)
            if not current or current.get("run_id") != self.run_id:
                raise SystemExit("BacktestRunner: run_id mismatch — aborting.")
            ts_list = [s["timestamp"] for s in (current.get("samples") or [])]
            if not ts_list:
                raise SystemExit("BacktestRunner: no sample timestamps in status file.")
            logger.info(
                "BacktestRunner: dashboard mode — %d samples for %s (run_id=%d)",
                len(ts_list), self.symbol, self.run_id,
            )
            return ts_list

        # Mode B: CLI single-point
        if self.args.timestamp:
            from src.utils.datetime_utils import parse_flexible_date
            dt = parse_flexible_date(self.args.timestamp)
            ts = to_iso_zulu(dt)
            logger.info("BacktestRunner: single-point — %s", ts)
            return [ts]

        # Mode C: CLI batch range
        if self.args.start:
            return self._sample_batch()

        raise SystemExit("BacktestRunner: no valid mode detected.")

    def _sample_batch(self) -> list[str]:
        """Sniper-sample noteworthy timestamps in a date range."""
        start_dt = self.args.start
        end_dt = self.args.end
        count = self.args.samples

        from src.utils.datetime_utils import get_interval_seconds, to_iso_zulu
        from src.config.loader import load_strategy_config
        from src.infrastructure.binance.client import BinanceFuturesClient
        from src.analyzer.simulation_sampler import SniperSampler
        from src.utils.market_utils import calculate_indicator_warmup

        strategy_cfg = load_strategy_config()
        macro_interval = strategy_cfg.get(
            "analysis_window", {}
        ).get("macro_context", {}).get("time_interval", "15m")

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

        logger.info(
            "BacktestRunner: fetching %s klines (limit=%d, warmup=%d)",
            macro_interval, limit, warmup,
        )
        binance = BinanceFuturesClient()
        try:
            klines = binance.fetch_historical_klines(
                symbol=self.symbol,
                interval=macro_interval,
                limit=limit,
                startTime=int(start_dt.timestamp() * 1000)
                - (warmup * interval_seconds * 1000),
                endTime=int(end_dt.timestamp() * 1000),
            )
        finally:
            binance.close()

        klines_range = [
            k for k in klines
            if start_dt <= datetime.fromtimestamp(k.open_time / 1000, tz=timezone.utc) <= end_dt
        ]

        sampler = SniperSampler(self.symbol)
        timestamps = sampler.sample(klines_range, count)

        logger.info(
            "BacktestRunner: sampled %d noteworthy points from %s → %s",
            len(timestamps),
            start_dt.strftime("%Y-%m-%d"),
            end_dt.strftime("%Y-%m-%d"),
        )
        for i, dt in enumerate(timestamps, 1):
            logger.info("  [%d] %s", i, dt.isoformat())

        return [to_iso_zulu(dt) for dt in timestamps]

    # ── Status helpers (dashboard mode) ───────────────────────────────────

    def _should_continue(self) -> bool:
        """Check supersede guard (dashboard mode only)."""
        if self.run_id is None:
            return True
        current = _read_status(self.data_root)
        return current is not None and current.get("run_id") == self.run_id

    def _update_sample_status(self, index: int, status: str, **extra):
        """Update one sample's status in the dashboard status file."""
        if self.run_id is None:
            return
        current = _read_status(self.data_root)
        if not current or current.get("run_id") != self.run_id:
            return
        samples = list(current.get("samples") or [])
        if index < len(samples):
            samples[index]["status"] = status
            for k, v in extra.items():
                samples[index][k] = v
        _write_status(self.data_root, {
            **current,
            "samples": samples,
            "current_index": index,
            "done_count": sum(1 for s in samples if s["status"] in ("completed", "failed")),
            "elapsed_seconds": _compute_elapsed(current),
        })

    def _finalize(self):
        """Mark the dashboard status file as complete."""
        if self.run_id is None:
            return
        current = _read_status(self.data_root)
        if current and current.get("run_id") == self.run_id:
            _write_status(self.data_root, {
                **current,
                "running": False,
                "elapsed_seconds": _compute_elapsed(current),
            })

    # ── Run ──────────────────────────────────────────────────────────────

    def run(self):
        timestamps = self._collect_timestamps()
        total = len(timestamps)

        is_dashboard = self.run_id is not None

        try:
            from run_session import SessionEngine

            engine = SessionEngine(symbol=self.symbol, data_root=self.data_root)

            for i, ts in enumerate(timestamps):
                # ── Supersede check (dashboard only) ──
                if is_dashboard and not self._should_continue():
                    logger.info("Backtest run %d superseded — discarding.", self.run_id)
                    return

                self._update_sample_status(i, "running")

                try:
                    # ── Progress callback (dashboard only; CLI is no-op) ──
                    def _bt_progress(
                        stage=None, activity=None, status="running",
                        stage_label=None, result=None, error=None,
                        _sample_idx=i,
                    ):
                        if not is_dashboard:
                            return
                        current3 = _read_status(self.data_root)
                        if not current3 or current3.get("run_id") != self.run_id:
                            return
                        samples3 = list(current3.get("samples") or [])
                        if _sample_idx >= len(samples3):
                            return
                        now_utc = datetime.now(timezone.utc)
                        started_str3 = current3.get("started_at", "")
                        elapsed3 = 0
                        if started_str3:
                            try:
                                started3 = datetime.fromisoformat(
                                    started_str3.replace("Z", "+00:00")
                                )
                                elapsed3 = round((now_utc - started3).total_seconds())
                            except Exception:
                                pass

                        progress = samples3[_sample_idx].get("progress", {})
                        if status == "running":
                            activities = list(progress.get("activities", []))
                            add_activity_entry(activities, activity)
                            progress = {
                                "status": "running",
                                "current_stage": (
                                    stage
                                    if stage is not None
                                    else progress.get("current_stage", 1)
                                ),
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
                                activities.append({"type": ERROR, "message": activity})
                            progress = {
                                "status": "failed",
                                "current_stage": (
                                    stage
                                    if stage is not None
                                    else progress.get("current_stage", 1)
                                ),
                                "elapsed_seconds": elapsed3,
                                "error": error or activity or "Unknown error",
                                "activities": activities,
                            }

                        samples3[_sample_idx]["progress"] = progress
                        _write_status(self.data_root, {**current3, "samples": samples3})

                    engine.execute_cycle(
                        timestamp_str=ts,
                        progress_callback=_bt_progress if is_dashboard else None,
                    )

                    from src.utils.datetime_utils import sanitize_timestamp
                    self._update_sample_status(
                        i, "completed",
                        session_file=f"{self.symbol}_session_{sanitize_timestamp(ts)}.json",
                    )

                except Exception as e:
                    logger.exception(
                        "Backtest sample %d/%d failed for %s", i + 1, total, self.symbol,
                    )
                    self._update_sample_status(i, "failed", error=str(e))

            self._finalize()
            logger.info("BacktestRunner: completed %d samples for %s", total, self.symbol)

        except Exception as e:
            logger.exception("Backtest run failed for %s: %s", self.symbol, e)
            if is_dashboard:
                current = _read_status(self.data_root)
                if current and current.get("run_id") == self.run_id:
                    _write_status(self.data_root, {
                        **current,
                        "running": False,
                        "error": str(e),
                        "elapsed_seconds": _compute_elapsed(current),
                    })


# ── CLI entry point ────────────────────────────────────────────────────────

def main():
    """Direct invocation: ``python run_backtest.py --symbol BTC --start T-7d --samples 10``."""
    parser = argparse.ArgumentParser(description="Backtest Runner")

    parser.add_argument("--symbol", type=str, required=True,
                        help="Trading pair prefix (e.g. BTC)")

    # Dashboard mode
    parser.add_argument("--run-id", type=int, default=None,
                        help="Dashboard mode: read timestamps from .backtest_status.json")

    # CLI: single-point
    parser.add_argument("--timestamp", "-ts", type=str, default=None,
                        help="Run against a single historical timestamp (ISO-8601)")

    # CLI: batch range
    parser.add_argument("--start", type=str, default=None,
                        help="Start date for batch sampling (YYYY-MM-DD or T-30d)")
    parser.add_argument("--end", type=str, default="now",
                        help="End date for batch sampling (default: now)")
    parser.add_argument("--samples", type=int, default=None,
                        help="Number of historical samples (requires --start)")

    parser.add_argument("--write-status", action="store_true",
                        help="Write progress to .backtest_status.json")
    from src.utils.pipeline_utils import add_data_path_argument
    add_data_path_argument(parser)

    args = parser.parse_args()

    # Validate mode exclusivity
    modes = sum([
        args.run_id is not None,
        args.timestamp is not None,
        args.start is not None,
    ])
    if modes == 0:
        raise SystemExit("Error: one of --run-id, --timestamp, or --start is required.")
    if modes > 1:
        raise SystemExit("Error: --run-id, --timestamp, and --start are mutually exclusive.")
    if args.start and not args.samples:
        raise SystemExit("Error: --samples is required with --start for batch mode.")

    if not args.path:
        args.path = "data/prod"

    # Parse date strings for CLI modes
    from src.utils.datetime_utils import parse_flexible_date
    if args.start:
        args.start = parse_flexible_date(args.start)
    args.end = parse_flexible_date(args.end) if args.end != "now" else datetime.now(timezone.utc)

    runner = BacktestRunner(args)
    runner.run()


if __name__ == "__main__":
    main()
