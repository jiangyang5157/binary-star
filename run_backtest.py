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
import signal
import sys
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
    tmp.write_text(json.dumps(status, default=str, indent=2))
    tmp.replace(path)



# ── Main runner ────────────────────────────────────────────────────────────

class BacktestRunner:
    """Runs historical session cycles — dashboard mode (with status file) or CLI mode."""

    def __init__(self, args: argparse.Namespace):
        self.args = args
        self.data_root: str = args.path
        self.symbol: str = args.symbol.upper()
        self.is_dashboard = getattr(args, "write_status", False)
        self._setup_signals()

    # ── Signal handling ─────────────────────────────────────────────────

    def _setup_signals(self):
        for sig in (signal.SIGINT, signal.SIGTERM):
            signal.signal(sig, self._handle_termination)

    def _handle_termination(self, signum, frame):
        logger.warning("termination signal received | shutting down")
        if self.is_dashboard:
            try:
                current = _read_status(self.data_root)
                if current:
                    _write_status(self.data_root, {
                        **current,
                        "running": False,
                    })
            except Exception as e:
                logger.warning("failed to write final status during shutdown | error=%s", e)
        sys.exit(0)

    # ── Timestamp collection ─────────────────────────────────────────────

    def _collect_timestamps(self) -> list[str]:
        """Resolve timestamps based on the active mode."""
        from src.utils.datetime_utils import to_iso_zulu

        # Mode A: Dashboard — read from status file
        if self.is_dashboard:
            current = _read_status(self.data_root)
            if not current:
                raise SystemExit("BacktestRunner: no status file found — aborting.")
            all_samples = current.get("samples") or []
            ts_list = [s["timestamp"] for s in all_samples if s.get("status") != "completed"]
            if not ts_list:
                logger.info("dashboard mode | all %d samples already completed — exiting.", len(all_samples))
                raise SystemExit(0)
            logger.info(
                "dashboard mode | pending=%d/%d | symbol=%s",
                len(ts_list), len(all_samples), self.symbol,
            )
            return ts_list

        # Mode B: CLI single-point
        if self.args.timestamp:
            from src.utils.datetime_utils import parse_flexible_date
            dt = parse_flexible_date(self.args.timestamp)
            ts = to_iso_zulu(dt)
            logger.info("single point | ts=%s", ts)
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
        from src.utils.pipeline_utils import load_combined_config
        from src.infrastructure.binance.client import BinanceFuturesClient
        from src.analyzer.simulation_sampler import SniperSampler
        from src.utils.market_utils import calculate_indicator_warmup

        strategy_cfg = load_combined_config()
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
            "fetching klines | interval=%s | limit=%d | warmup=%d",
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
            "sampled %d noteworthy points | from=%s | to=%s",
            len(timestamps),
            start_dt.strftime("%Y-%m-%d"),
            end_dt.strftime("%Y-%m-%d"),
        )
        for i, dt in enumerate(timestamps, 1):
            logger.info("  sample [%d] | ts=%s", i, dt.isoformat())

        return [to_iso_zulu(dt) for dt in timestamps]

    # ── Status helpers (dashboard mode) ───────────────────────────────────

    def _update_sample_status(self, index: int, status: str, **extra):
        """Update one sample's status in the dashboard status file."""
        if not self.is_dashboard:
            return
        current = _read_status(self.data_root)
        if not current:
            return
        samples = list(current.get("samples") or [])
        if index < len(samples):
            samples[index]["status"] = status
            for k, v in extra.items():
                samples[index][k] = v
        _write_status(self.data_root, {
            **current,
            "samples": samples,
        })

    def _finalize(self):
        """Mark the dashboard status file as complete."""
        if not self.is_dashboard:
            return
        current = _read_status(self.data_root)
        if current:
            _write_status(self.data_root, {
                **current,
                "running": False,
            })

    # ── Run ──────────────────────────────────────────────────────────────

    def run(self):
        timestamps = self._collect_timestamps()
        total = len(timestamps)

        try:
            from run_session import SessionEngine

            engine = SessionEngine(symbol=self.symbol, data_root=self.data_root)

            for i, ts in enumerate(timestamps):
                self._update_sample_status(i, "running",
                    started_at=datetime.now(timezone.utc).isoformat())

                try:
                    # ── Progress callback (dashboard only; CLI is no-op) ──
                    def _bt_progress(
                        stage=None, activity=None, status="running",
                        stage_label=None, result=None, error=None,
                        _sample_idx=i,
                    ):
                        if not self.is_dashboard:
                            return
                        current3 = _read_status(self.data_root)
                        if not current3:
                            return
                        samples3 = list(current3.get("samples") or [])
                        if _sample_idx >= len(samples3):
                            return
                        now_utc = datetime.now(timezone.utc)
                        started_str3 = samples3[_sample_idx].get("started_at") or current3.get("started_at", "")
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
                            add_activity_entry(activities, activity, stage=stage)
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

                    result = engine.execute_cycle(
                        timestamp_str=ts,
                        progress_callback=_bt_progress if self.is_dashboard else None,
                    )

                    if isinstance(result, dict) and "error" in result:
                        err_msg = result["error"]
                        logger.warning(
                            "sample failed internally | symbol=%s | sample=%d/%d | error=%s",
                            self.symbol, i + 1, total, err_msg,
                        )
                        self._update_sample_status(i, "failed", error=err_msg)
                    else:
                        self._update_sample_status(i, "completed")

                except Exception as e:
                    logger.exception(
                        "backtest failed | symbol=%s | sample=%d/%d", self.symbol, i + 1, total,
                    )
                    self._update_sample_status(i, "failed", error=str(e))

            self._finalize()
            logger.info("completed %d samples | symbol=%s", total, self.symbol)

        except Exception as e:
            logger.exception("backtest failed | symbol=%s | error=%s", self.symbol, e)
            if self.is_dashboard:
                current = _read_status(self.data_root)
                if current:
                    _write_status(self.data_root, {
                        **current,
                        "running": False,
                        "error": str(e),
                    })


# ── CLI entry point ────────────────────────────────────────────────────────

def main():
    """Direct invocation: ``python run_backtest.py --symbol BTC --start T-7d --samples 10``."""
    parser = argparse.ArgumentParser(description="Backtest Runner")

    parser.add_argument("--symbol", type=str, required=True,
                        help="Trading pair (e.g. BTCUSDT)")

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
        args.write_status,
        args.timestamp is not None,
        args.start is not None,
    ])
    if modes == 0:
        raise SystemExit("Error: one of --write-status, --timestamp, or --start is required.")
    if modes > 1:
        raise SystemExit("Error: --write-status, --timestamp, and --start are mutually exclusive.")
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
