#!/usr/bin/env python3
import os
import sys
import argparse
import signal
import pandas as pd
from datetime import datetime, timezone, timedelta
from typing import List, Optional, Dict, Any
from dotenv import load_dotenv

# Setup absolute project paths
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# Load environment before any logic
load_dotenv()

from src.infrastructure.binance.client import BinanceFuturesClient
from src.agent.binary_star_orchestrator import BinaryStarOrchestrator
from src.analyzer.simulation_sampler import SpacedSampler, SniperSampler
from src.infrastructure.notifications.email_notifier import SessionNotifier
from src.utils.pipeline_utils import load_config, load_global_config, archive_strategy_result
from src.utils.logger_utils import setup_logger
from src.utils.datetime_utils import parse_iso_to_utc
from src.utils.market_utils import calculate_indicator_warmup

# Initialize central engine logger
logger = setup_logger("SessionEngine")

class SessionEngine:
    """The Singularity Session Engine (v6.0).

    Orchestrates real-time and historical market analysis using an 
    adversarial reasoning triad. Supports Live and Backtest modes 
    with complete logic parity.
    """
    def __init__(self, symbol: str, data_root: str, args: Any = None):
        self.symbol = symbol
        self.data_root = data_root
        self.args = args
        self.config = load_config()
        self.global_cfg = load_global_config()
        
        # Initialize Infrastructure
        self.api_key = os.environ.get("GEMINI_API_KEY")
        if not self.api_key:
            logger.critical("GEMINI_API_KEY not found. Neural inference disabled.")
            sys.exit(1)
            
        self.orchestrator = BinaryStarOrchestrator(
            config_dict=self.config,
            api_key=self.api_key,
            data_root=self.data_root
        )
        self.notifier = SessionNotifier(data_root=self.data_root)
        
        # UI/Notification control
        self.send_email = getattr(args, 'email', False)
        
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

            # 4. Notification (Filtered)
            # We skip email notifications unless --email is explicitly provided.
            # Local previews are ALWAYS generated for audit trails.
            self.notifier.notify_session(
                self.symbol, 
                session_result, 
                save_local=self.send_email, 
                dispatch_email=self.send_email
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
                logger.critical("CIRCUIT BREAKER: Triggering emergency notification.")
                self.notifier.notify_alert("PIPELINE_ERROR", self.symbol, str(e))
                
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
        self.symbol = args.symbol or self.global_cfg['system']['default_symbol']
        
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
        mode = self.args.mode
        logger.info(f"Starting SessionEngine: {mode} mode for {self.symbol}")
        
        if mode == "prod":
            self.engine.execute_cycle(timestamp_str=getattr(self.args, 'timestamp', None))
        
        elif mode == "backtest":
            self._run_backtest()

    def _run_backtest(self):
        """Historical simulation orchestration."""
        start_dt = self.args.start
        end_dt = self.args.end
        count = self.args.samples
        sample_mode = self.args.sampling_mode or "sniper"

        logger.info(f"Backtest: Sampling {count} points from {start_dt} to {end_dt} ({sample_mode} mode)")
        
        from src.utils.datetime_utils import get_interval_seconds
        
        macro_interval = self.engine.config['analysis_window']['macro_context']['time_interval']
        
        # 2. Preparation (v6.30: Sniper-Led Architecture)
        topo_cfg = self.engine.config.get('topography_parameters', {})
        bt_cfg = self.engine.global_cfg.get('backtest', {})
        
        # Calculate warmup needed for technical indicators
        fir_period = self.engine.config['analysis_window']['macro_context']['lookback_candles']
        warmup = calculate_indicator_warmup(
            iir_periods=[topo_cfg['exponential_moving_average_period'], topo_cfg['average_true_range_period']],
            fir_periods=[fir_period],
            multiplier=self.engine.global_cfg.get('analytical', {}).get('indicator_warmup_multiplier', 5.0)
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
        
        # Prepare DataFrame for sampling
        df = pd.DataFrame(klines, columns=[
            'timestamp', 'open', 'high', 'low', 'close', 'volume',
            'close_time', 'qav', 'num_trades', 'taker_base_vol', 'taker_quote_vol', 'ignore'
        ])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms', utc=True)
        df['close'] = df['close'].astype(float)
        
        df_range = df[(df['timestamp'] >= start_dt) & (df['timestamp'] <= end_dt)]
        
        # v6.15: Backtest Sampling Architecture
        self.sampling_mode = self.args.sampling_mode or "sniper"
        self.sampling_count = self.args.samples or self.engine.global_cfg.get('backtest', {})['default_samples']

        if self.sampling_mode == "sniper":
            sampler = SniperSampler(self.symbol)
        else:
            sampler = SpacedSampler()
            
        timestamps = sampler.sample(df_range, self.sampling_count)
        
        # 3. Execution Loop
        logger.info(f"Simulating {len(timestamps)} temporal snapshots (Sample Count: {self.sampling_count})...")
        for i, dt in enumerate(timestamps, 1):
            logger.info(f"\n[BACKTEST PROGRESS: {i}/{len(timestamps)}]")
            self.engine.execute_cycle(timestamp_str=dt.isoformat())

def parse_date(date_str: str) -> datetime:
    """Helper to parse flexible dates (T-30d, ISO, now)."""
    if date_str.lower() == "now":
        return datetime.now(timezone.utc)
    if date_str.upper().startswith("T-"):
        val = int(date_str[2:-1])
        unit = date_str[-1].lower()
        if unit == 'd': return datetime.now(timezone.utc) - timedelta(days=val)
        if unit == 'h': return datetime.now(timezone.utc) - timedelta(hours=val)
    
    try:
        return parse_iso_to_utc(date_str)
    except:
        pass

    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try: return datetime.strptime(date_str, fmt).replace(tzinfo=timezone.utc)
        except: continue
    raise argparse.ArgumentTypeError(f"Invalid date: {date_str}")

def main():
    parser = argparse.ArgumentParser(description="Singularity Session Engine (v6.0)")
    parser.add_argument("--symbol", type=str, default=None, help="Trading pair (e.g. BTCUSDT)")
    parser.add_argument("--email", action="store_true", help="Enable high-conviction email alerts")
    
    # 2. Backtest Configuration Group
    bt_group = parser.add_argument_group("Backtest Options")
    bt_group.add_argument("--timestamp", "-ts", type=str, help="Precise historical timestamp")
    bt_group.add_argument("--start", type=parse_date, help="Start date (YYYY-MM-DD or T-30d)")
    bt_group.add_argument("--end", type=parse_date, default="now", help="End date (YYYY-MM-DD or now)")
    bt_group.add_argument("--samples", type=int, default=None, help="Number of historical samples")
    bt_group.add_argument("--sampling-mode", choices=["spaced", "sniper"], default="sniper")

    
    from src.utils.pipeline_utils import add_data_path_argument
    add_data_path_argument(parser)
    
    args = parser.parse_args()
    
    # Mode Detection
    if getattr(args, 'start', None):
        args.mode = "backtest"
        if not args.path: args.path = "data/backtest"
    else:
        args.mode = "prod"
        if not args.path: args.path = "data/prod"

    # Sanity checks
    if args.mode == "backtest" and not args.start:
        parser.error("--start is required for backtest mode.")

    controller = SessionController(args)
    controller.run()

if __name__ == "__main__":
    main()
