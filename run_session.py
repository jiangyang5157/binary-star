#!/usr/bin/env python3
import os
import sys
import argparse
import signal
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any
from dotenv import load_dotenv

# Setup absolute project paths
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# Load environment before any logic
load_dotenv()

from src.infrastructure.exchange.base_client import AbstractExchangeClient
from src.infrastructure.binance.client import BinanceFuturesClient
from src.agent.binary_star_orchestrator import BinaryStarOrchestrator
from src.analyzer.simulation_sampler import SniperSampler
from src.infrastructure.notifications.email_notifier import SessionNotifier
from src.utils.pipeline_utils import load_config, load_global_config, archive_strategy_result
from src.utils.logger_utils import setup_logger
from src.utils.datetime_utils import parse_iso_to_utc
from src.utils.market_utils import calculate_indicator_warmup
from src.utils.path_utils import resolve_project_root

# Initialize central engine logger
logger = setup_logger("SessionEngine")
_session_file_log = logging.getLogger("src.SessionEngine")  # writes to {data_root}/session.log

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

        # Apply per-symbol config overrides (XAUTUSDT vs BTCUSDT baseline)
        from src.config.symbol_resolver import resolve_config
        self.config = resolve_config(self.config, symbol)
        self.global_cfg = resolve_config(self.global_cfg, symbol)
        
        # Resolve API key based on active provider (decoupled)
        from src.utils.pipeline_utils import resolve_api_key
        self.api_key = resolve_api_key()
        if not self.api_key:
            logger.critical("API_KEY not found for active provider. Neural inference disabled.")
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
        self.max_failures_threshold = int(self.global_cfg.get('network', {}).get('gemini', {}).get('circuit_breaker_threshold', 3))

    def execute_cycle(self, timestamp_str: Optional[str] = None) -> Dict[str, Any]:
        """
        Executes a single market analysis cycle.
        If timestamp_str is None, it acts as 'Live' (Real-time).
        If timestamp_str is provided, it acts as 'Simulation' (Historical).
        """
        try:
            mode_label = "PROD" if not timestamp_str else f"SIMULATION @ {timestamp_str}"
            logger.info(f"--- Session Cycle Start [{mode_label}] ---")
            
            # 1. Topographic Fact Gathering
            target_dt = None
            if timestamp_str:
                from src.utils.datetime_utils import parse_iso_to_utc
                target_dt = parse_iso_to_utc(timestamp_str)
            
            logger.info(f"Observer: Mapping structural topography for {self.symbol}...")
            observation = self.orchestrator.observer.observe(timestamp=target_dt, persist=False)
            
            if "error" in observation:
                raise ValueError(f"Observer failure: {observation['error']}")

            # Metric telemetry for forensic audit trail
            metrics = observation.get('quantitative_metrics', {})
            topo = metrics.get('volume_profile', {})
            dyn = metrics.get('price_dynamics', {})
            logger.info(
                f"Topography Snapshot: POC={topo.get('poc')} | "
                f"VAH={topo.get('vah')} | VAL={topo.get('val')} | "
                f"ATR={dyn.get('atr_macro')}"
            )

            # 2. Adversarial Reasoning Triad
            logger.info("BinaryStar: Initiating adversarial debate [Session Analyst VS Critic]...")
            session_result = self.orchestrator.execute_flow(observation, self.symbol)

            # 4. Notification (always attempt; SessionNotifier gates on .env + confidence)
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
            logger.info(f"Pipeline Complete. Session archived: {os.path.basename(output_file)}")

            self.consecutive_failures = 0
            return session_result

        except Exception as e:
            self.consecutive_failures += 1
            logger.error(f"Session Cycle Failure ({self.consecutive_failures}/{self.max_failures_threshold}): {e}", exc_info=True)
            
            if self.consecutive_failures >= self.max_failures_threshold and not timestamp_str:
                logger.critical("CIRCUIT BREAKER: Threshold exceeded — stopping session engine.")
                self.notifier.notify_alert("PIPELINE_ERROR", self.symbol, str(e))
                raise RuntimeError(f"Circuit breaker tripped after {self.consecutive_failures} consecutive failures.") from e

            return {"error": str(e)}

        finally:
            # Resource Hygiene: Purge context caches
            try:
                self.orchestrator.cache_manager.delete_market_cache()
            except: pass


class SessionController:
    """Manages the lifecycle of the SessionEngine according to user-specified modes."""
    def __init__(self, args):
        self.args = args
        self.data_root = args.path
        self.global_cfg = load_global_config()
        from src.utils.symbol_utils import resolve_symbol
        self.symbol = resolve_symbol(args.symbol)
        
        self.engine = SessionEngine(self.symbol, self.data_root, args=args)
        self._setup_signals()

    def _setup_signals(self):
        for sig in (signal.SIGINT, signal.SIGTERM):
            signal.signal(sig, self._handle_termination)

    def _handle_termination(self, signum, frame):
        logger.warning(f"Termination signal received. Cleaning up context caches...")
        try:
            self.engine.orchestrator.cache_manager.delete_market_cache()
        except: pass
        sys.exit(0)

    def run(self):
        if self.args.timestamp:
            self.engine.execute_cycle(timestamp_str=self.args.timestamp)
        elif self.args.start:
            self._run_backtest()
        else:
            self.engine.execute_cycle(timestamp_str=None)

    def _run_backtest(self):
        """Historical simulation orchestration."""
        start_dt = self.args.start
        end_dt = self.args.end
        count = self.args.samples

        logger.info(f"Backtest: Sniper-sampling {count} noteworthy points from {start_dt} to {end_dt}")
        
        from src.utils.datetime_utils import get_interval_seconds
        
        macro_interval = self.engine.config['analysis_window']['macro_context']['time_interval']
        
        # 2. Preparation
        topo_cfg = self.engine.config.get('topography_parameters', {})
        
        # Calculate warmup needed for technical indicators
        fir_period = self.engine.config['analysis_window']['macro_context']['lookback_candles']
        warmup = calculate_indicator_warmup(
            iir_periods=[
                topo_cfg['indicators']['exponential_moving_average_period'],
                topo_cfg['indicators']['average_true_range_period'],
            ],
            fir_periods=[fir_period],
        )
        
        # Calculate needed limit plus buffer
        range_seconds = (end_dt - start_dt).total_seconds()
        interval_seconds = get_interval_seconds(macro_interval)
        limit = int(range_seconds / interval_seconds) + warmup 

        logger.info(f"Backtest Engine: Fetching {macro_interval} klines for simulation (Limit: {limit}, Warmup: {warmup})...")
        binance = BinanceFuturesClient()
        klines = binance.fetch_historical_klines(
            symbol=self.symbol,
            interval=macro_interval,
            limit=limit,
            startTime=int(start_dt.timestamp() * 1000) - (warmup * interval_seconds * 1000),
            endTime=int(end_dt.timestamp() * 1000)
        )
        binance.close()
        
        # Prepare KlineData range for sampling
        klines_range = [
            k for k in klines 
            if start_dt <= datetime.fromtimestamp(k.open_time / 1000, tz=timezone.utc) <= end_dt
        ]
        
        # SniperSampler: scans historical range for noteworthy asymmetry events
        sampler = SniperSampler(self.symbol)
        timestamps = sampler.sample(klines_range, self.args.samples)

        # Log the full sample list to session.log for traceability
        _session_file_log.info("Backtest sample selection (%d timestamps):", len(timestamps))
        for i, dt in enumerate(timestamps, 1):
            _session_file_log.info("  [%d] %s", i, dt.isoformat())

        # 3. Execution Loop
        logger.info(f"Simulating {len(timestamps)} temporal snapshots (Requested: {self.args.samples})...")
        for i, dt in enumerate(timestamps, 1):
            logger.info(f"\n[BACKTEST PROGRESS: {i}/{len(timestamps)}]")
            _session_file_log.info("[BACKTEST %d/%d] %s — starting", i, len(timestamps), dt.isoformat())
            self.engine.execute_cycle(timestamp_str=dt.isoformat())

def parse_date(date_str: str) -> datetime:
    """Helper to parse flexible dates (T-30d, ISO, now)."""
    from src.utils.datetime_utils import parse_flexible_date
    try:
        return parse_flexible_date(date_str)
    except ValueError as e:
        raise argparse.ArgumentTypeError(str(e))

def main():
    parser = argparse.ArgumentParser(description="Singularity Session Engine")
    parser.add_argument("--symbol", type=str, required=True, help="Trading pair prefix (e.g. BTC)")

    # 2. Backtest Configuration Group
    bt_group = parser.add_argument_group("Backtest Options")
    bt_group.add_argument("--timestamp", "-ts", type=str, help="Precise historical timestamp")
    bt_group.add_argument("--start", type=parse_date, help="Start date (YYYY-MM-DD or T-30d)")
    bt_group.add_argument("--end", type=parse_date, default="now", help="End date (YYYY-MM-DD or now)")
    bt_group.add_argument("--samples", type=int, default=None, help="Number of historical samples")

    
    from src.utils.pipeline_utils import add_data_path_argument
    add_data_path_argument(parser)
    
    args = parser.parse_args()
    
    # --- Mode Resolution & Parameter Validation ---
    if not args.path:
        args.path = "data/prod"

    if getattr(args, 'timestamp', None):
        logger.info(f"=== Mode Resolved: SIMULATION (One-Off Historical) ===")
        logger.info(f" => ACTION: Replaying market cross-section at historical point")
        logger.info(f" => ADOPTED: --timestamp '{args.timestamp}'")
        logger.info(f" => ARCHIVAL: {args.path}")
    elif getattr(args, 'start', None):
        if args.samples is None:
            raise SystemExit("Error: --samples is required for backtest mode.")
        logger.info(f"=== Mode Resolved: BACKTEST (Batch Historical) ===")
        logger.info(f" => ACTION: Simulating multiple historical data points")
        logger.info(f" => ADOPTED: --start '{args.start}', --end '{args.end}', --samples {args.samples}")
        logger.info(f" => ARCHIVAL: {args.path}")
    else:
        logger.info(f"=== Mode Resolved: PROD (Live Execution) ===")
        logger.info(f" => ACTION: Fetching current real-time market data")
        logger.info(f" => ARCHIVAL: {args.path}")

    print("\n") # formatting spacing before engine start
    controller = SessionController(args)
    controller.run()

if __name__ == "__main__":
    main()
