#!/usr/bin/env python3
import os
import sys
import argparse
import signal
import logging
from datetime import datetime, timezone
from typing import Optional, Dict, Any
from dotenv import load_dotenv

# Setup absolute project paths
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# Load environment before any logic
load_dotenv()

from src.infrastructure.exchange.base_client import AbstractExchangeClient
from src.agent.binary_star_orchestrator import BinaryStarOrchestrator
from src.infrastructure.notifications.email_notifier import SessionNotifier
from src.utils.pipeline_utils import load_config, load_global_config, archive_strategy_result
from src.utils.logger_utils import setup_logger
from src.utils.datetime_utils import parse_iso_to_utc
from src.utils.path_utils import resolve_project_root
from src.utils.progress_utils import add_activity_entry, ERROR as PROGRESS_ERROR
from src.utils.status_file_utils import read_status, write_status

# Initialize central engine logger (colorized when called standalone;
# dedup-safe: sniper daemon already owns the root console handler)
logger = setup_logger("SessionEngine", console_color=True)

class SessionEngine:
    """The Singularity Session Engine.

    Orchestrates real-time and historical market analysis using an 
    adversarial reasoning triad. Supports Live and Backtest modes 
    with complete logic parity.
    """
    def __init__(self, symbol: str, data_root: str, args: Any = None, 
                 exchange_client: Optional[AbstractExchangeClient] = None):
        self.symbol = symbol
        self.data_root = data_root
        self.args = args
        self.config = load_config()
        self.global_cfg = load_global_config()

        # Apply per-symbol config overrides on top of base config
        from src.config.symbol_resolver import resolve_config
        self.config = resolve_config(self.config, symbol)
        self.global_cfg = resolve_config(self.global_cfg, symbol)
        
        # Resolve API key based on active provider (decoupled)
        from src.utils.pipeline_utils import resolve_api_key
        self.api_key = resolve_api_key()
        if not self.api_key:
            logger.critical("API_KEY not found | neural inference disabled")
            sys.exit(1)
            
        self.orchestrator = BinaryStarOrchestrator(
            config_dict=self.config,
            api_key=self.api_key,
            data_root=self.data_root,
            symbol=self.symbol,
            exchange_client=exchange_client,
            global_config=self.global_cfg,
        )
        self.notifier = SessionNotifier(data_root=self.data_root)
        
        # Notification control — always enabled at the engine level.
        # The SessionNotifier gates actual email dispatch on .env credentials.

        # Failure tracking for circuit breaker
        self.consecutive_failures = 0
        self.max_failures_threshold = int(self.global_cfg.get('llm', {}).get('max_consecutive_failures', 3))

    def execute_cycle(self, timestamp_str: Optional[str] = None,
                      situation_brief: Optional[Dict[str, Any]] = None,
                      progress_callback=None) -> Dict[str, Any]:
        """
        Executes a single market analysis cycle.
        If timestamp_str is None, it acts as 'Live' (Real-time).
        If timestamp_str is provided, it acts as 'Simulation' (Historical).
        situation_brief: Optional upstream intelligence injected into observation.
        progress_callback: Optional fn(stage, activity, stage_label=..., status=...,
                           result=..., error=...) for progress reporting.
        """
        try:
            mode_label = "PROD" if not timestamp_str else f"SIMULATION @ {timestamp_str}"
            logger.info(f"═══ SESSION CYCLE START [{mode_label}] ═══")

            # 1. Topographic Fact Gathering
            target_dt = None
            if timestamp_str:
                from src.utils.datetime_utils import parse_iso_to_utc
                target_dt = parse_iso_to_utc(timestamp_str)

            if progress_callback:
                progress_callback(stage=1, activity="Fetching kline data…")

            logger.info(f"[{self.symbol}] observer mapping topography")
            observation = self.orchestrator.observer.observe(
                timestamp=target_dt, persist=False,
                progress_callback=progress_callback,
            )

            if "error" in observation:
                raise ValueError(f"Observer failure: {observation['error']}")

            # Metric telemetry for forensic audit trail
            metrics = observation.get('quantitative_metrics', {})
            topo = metrics.get('volume_profile', {})
            dyn = metrics.get('price_dynamics', {})
            logger.info(
                f"[{self.symbol}] topography snapshot | "
                f"POC={topo.get('poc')} | "
                f"VAH={topo.get('vah')} | VAL={topo.get('val')} | "
                f"ATR={dyn.get('atr_macro')}"
            )

            # 2. Adversarial Reasoning Triad
            # Inject situation brief into the observation before the debate.
            # SessionAgent and Critic both see it inside observation_json.
            if situation_brief:
                observation['situation_brief'] = situation_brief

            logger.info(f"[{self.symbol}] initiating Binary Star debate")
            session_result = self.orchestrator.execute_flow(
                observation, self.symbol,
                progress_callback=progress_callback,
            )

            # 4. Notification (always attempt; SessionNotifier gates on .env + confidence)
            if progress_callback:
                progress_callback(stage=5, activity="Saving session…")

            self.notifier.notify_session(
                self.symbol,
                session_result,
                save_local=True,
                dispatch_email=True
            )

            # 5. Audit Archival
            output_file = archive_strategy_result(
                symbol=self.symbol,
                timestamp=observation['observed_at'],
                result=session_result,
                data_root=self.data_root,
                target_dir="sessions"
            )
            logger.info(f"pipeline complete | session archived | file={os.path.basename(output_file)}")

            if progress_callback:
                progress_callback(stage=5, activity="Sending notification…")

            # Progress: completed
            if progress_callback:
                final_decision = session_result.get("final_decision", {})
                debate_history = session_result.get("debate_history", [])
                # Build debate path string
                debate_path_parts = []
                for entry in debate_history:
                    r = entry.get("round", "?")
                    v = entry.get("critic", {}).get("veto_level", "?")
                    debate_path_parts.append(f"R{r} {v}")
                debate_path = " → ".join(debate_path_parts) if debate_path_parts else ""
                progress_callback(
                    status="completed",
                    result={
                        "direction": str(final_decision.get("opinion", "NEUTRAL")),
                        "confidence": int(final_decision.get("confidence_score", 0)),
                        "debate_path": debate_path,
                        "session_file": os.path.basename(output_file) if output_file else "",
                    },
                )

            self.consecutive_failures = 0
            return session_result

        except Exception as e:
            self.consecutive_failures += 1
            logger.error(f"session cycle failure ({self.consecutive_failures}/{self.max_failures_threshold}) | error={e}", exc_info=True)

            if progress_callback:
                progress_callback(status="failed", error=str(e))

            if self.consecutive_failures >= self.max_failures_threshold and not timestamp_str:
                logger.critical(f"CIRCUIT BREAKER — threshold exceeded ({self.max_failures_threshold})")
                self.notifier.notify_alert("PIPELINE_ERROR", self.symbol, str(e))
                raise RuntimeError(f"Circuit breaker tripped after {self.consecutive_failures} consecutive failures.") from e

            return {"error": str(e)}



# ── Subprocess status-file progress writer ───────────────────────────────


def write_status_file_callback(data_root: str):
    """Create a progress callback that writes to the session status file.

    Used when ``run.py session --write_status`` is spawned as a subprocess
    (e.g. by the dashboard API).  The subprocess reads the initial status
    written by the caller, updates only the ``progress`` section, and
    writes it back so the status can be polled.
    """

    def on_progress(stage=None, activity=None, status="running",
                    stage_label=None, result=None, error=None):
        current = read_status(data_root)
        if not current:
            return

        now_utc = datetime.now(timezone.utc)
        started_str = current.get("started_at", "")
        elapsed = 0
        if started_str:
            try:
                started = datetime.fromisoformat(started_str.replace("Z", "+00:00"))
                elapsed = round((now_utc - started).total_seconds())
            except Exception:
                pass

        progress = current.get("progress", {})

        if status == "running":
            activities = list(progress.get("activities", []))
            add_activity_entry(activities, activity)
            progress = {
                "status": "running",
                "current_stage": stage if stage is not None else progress.get("current_stage", 1),
                "stage_label": stage_label or progress.get("stage_label", ""),
                "activity": activity or progress.get("activity", ""),
                "elapsed_seconds": elapsed,
                "activities": activities,
            }
        elif status == "completed":
            current["running"] = False
            current["last_run"] = {
                "symbol": current.get("symbol", ""),
                "result": "success",
                "at": datetime.now(timezone.utc).isoformat(),
            }
            progress = {
                "status": "completed",
                "current_stage": 5,
                "stage_label": "Archive",
                "elapsed_seconds": elapsed,
                "result": result or {},
                "activities": progress.get("activities", []),
            }
        elif status == "failed":
            current["running"] = False
            current["last_run"] = {
                "symbol": current.get("symbol", ""),
                "result": "error",
                "error_message": error or activity or "Unknown error",
                "at": datetime.now(timezone.utc).isoformat(),
            }
            activities = list(progress.get("activities", []))
            if activity:
                activities.append({
                    "type": PROGRESS_ERROR,
                    "message": activity,
                })
            progress = {
                "status": "failed",
                "current_stage": stage if stage is not None else progress.get("current_stage", 1),
                "elapsed_seconds": elapsed,
                "error": error or activity or "Unknown error",
                "activities": activities,
            }

        current["progress"] = progress
        write_status(data_root, current)

    return on_progress


class SessionController:
    """Manages the lifecycle of a live SessionEngine cycle."""

    def __init__(self, args, progress_callback=None):
        self.args = args
        self.data_root = args.path
        self.global_cfg = load_global_config()
        from src.utils.symbol_utils import resolve_symbol
        self.symbol = resolve_symbol(args.symbol)

        # Validate symbol is explicitly configured — no silent fallback
        from src.config.symbol_resolver import is_symbol_configured
        if not is_symbol_configured(self.symbol):
            logger.critical(
                "symbol '%s' is not configured in symbol_config.yaml | "
                "add precision_qty, precision_price, min_order_qty, sl_slippage_buffer",
                self.symbol,
            )
            sys.exit(1)
        self.progress_callback = progress_callback

        self.engine = SessionEngine(self.symbol, self.data_root, args=args)
        self._setup_signals()

    def _setup_signals(self):
        for sig in (signal.SIGINT, signal.SIGTERM):
            signal.signal(sig, self._handle_termination)

    def _handle_termination(self, signum, frame):
        sys.exit(0)

    def run(self):
        self.engine.execute_cycle(timestamp_str=None,
                                   progress_callback=self.progress_callback)

def main():
    """Entry point for direct invocation: ``python run_session.py --symbol BTC``."""
    parser = argparse.ArgumentParser(description="Singularity Session Engine (live)")
    parser.add_argument("--symbol", type=str, required=True,
                        help="Trading pair prefix (e.g. BTC)")
    from src.utils.pipeline_utils import add_data_path_argument
    add_data_path_argument(parser)
    args = parser.parse_args()

    if not args.path:
        args.path = "data/prod"

    logger.info("mode=PROD | live execution")
    print("\n")
    controller = SessionController(args)
    controller.run()

if __name__ == "__main__":
    main()
