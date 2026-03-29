#!/usr/bin/env python3
import os
import sys
import argparse
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional, List, Any

# Setup paths
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from strategist import StrategistOrchestrator
from src.utils.agent_utils import load_global_config
from src.utils.logger_utils import setup_logger
from src.infrastructure.binance.client import BinanceFuturesClient
from src.utils.backtest_utils import MarketRegimeAnalyzer, SpacedSampler, RegimeSampler

class BacktestOrchestrator:
    """
    SOLID-compliant orchestrator for historical market backtesting.
    Focuses on strategy generation across sampled historical snapshots.
    """
    def __init__(self, data_root: str, sampling_count: int, sampling_mode: str):
        self.data_root = data_root
        self.sampling_count = sampling_count
        self.sampling_mode = sampling_mode.lower()
        
        # Setup persistent logging in the data_root
        log_path = os.path.join(data_root, "backtest.log")
        self.logger = setup_logger("BacktestOrchestrator", log_file=log_path)
        
        # Load system defaults
        global_cfg = load_global_config()
        self.symbol = global_cfg['system']['default_symbol']
        
        self.fetcher = BinanceFuturesClient()
        self.analyzer = MarketRegimeAnalyzer()

    def execute_simulation(self, start_date: datetime, end_date: datetime):
        """
        Coordinates the backtesting loop: 
        1. Fetch Regime Data -> 2. Sample Timestamps -> 3. Execute Strategies.
        """
        self.logger.info(f"=== Initializing Backtest for {self.symbol} ===")
        self.logger.info(f"Range: {start_date} to {end_date}")
        self.logger.info(f"Sampling: {self.sampling_count} points via {self.sampling_mode} mode")

        # 1. Fetch historical daily klines for regime detection
        # We fetch enough data to cover the start and end, plus buffer for indicators
        delta = end_date - start_date
        days_needed = delta.days + 60 # Buffer for EMA21/Vol calculation
        
        klines = self.fetcher.fetch_historical_klines(
            symbol=self.symbol,
            interval="1d",
            limit=min(days_needed, 1000), # Binance limit
            endTime=int(end_date.timestamp() * 1000)
        )
        
        if not klines:
            self.logger.error("Failed to fetch klines for market analysis. Aborting.")
            return

        # 2. Analyze Regimes and Sample Timestamps
        df_regimes = self.analyzer.classify_regimes(klines)
        # Filter again by strictly requested range
        df_range = df_regimes[
            (df_regimes['timestamp'] >= start_date) & 
            (df_regimes['timestamp'] <= end_date)
        ]

        if self.sampling_mode == "regime":
            sampler = RegimeSampler()
        else:
            sampler = SpacedSampler()

        target_timestamps = sampler.sample(df_range, self.sampling_count)
        self.logger.info(f"Finalized {len(target_timestamps)} sampling points.")

        # 3. Running the Strategist Loop (Strategy-Only)
        # We reuse the existing StrategistOrchestrator to ensure logic parity
        agent_orchestrator = StrategistOrchestrator(symbol=self.symbol, data_root=self.data_root)
        
        for i, dt in enumerate(target_timestamps, 1):
            self.logger.info(f"\n--- Simulation Snapshot {i}/{len(target_timestamps)}: {dt} ---")
            try:
                # Programs the strategist to think it is at 'dt'
                agent_orchestrator.execute_pipeline(timestamp_str=dt.isoformat())
                self.logger.info(f"Successfully generated strategy for {dt}")
            except Exception as e:
                self.logger.error(f"Simulation failed for {dt}: {e}")

        self.logger.info(f"\n=== Backtest Complete: {len(target_timestamps)} strategies generated ===")
        self.logger.info(f"Results archived in: {os.path.join(self.data_root, 'strategies')}")

def parse_date(date_str: Any) -> datetime:
    """Supports flexible date parsing: YYYY-MM-DD, T-Nd/T-Nh, 'now', or existing datetime."""
    if isinstance(date_str, datetime):
        return date_str
    if not date_str or (isinstance(date_str, str) and date_str.lower() == "now"):
        return datetime.now(timezone.utc)
    
    # 1. Handle relative formats like T-30d
    if date_str.upper().startswith("T-"):
        try:
            val = int(date_str[2:-1])
            unit = date_str[-1].lower()
            if unit == 'd':
                return datetime.now(timezone.utc) - timedelta(days=val)
            elif unit == 'h':
                return datetime.now(timezone.utc) - timedelta(hours=val)
        except ValueError:
            pass

    # 2. Handle absolute ISO/Standard formats
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(date_str, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
            
    raise argparse.ArgumentTypeError(f"Invalid date format: '{date_str}'. Expected YYYY-MM-DD or T-30d.")

def main():
    parser = argparse.ArgumentParser(description="Professional Crypto Backtest Simulator")
    parser.add_argument("--symbol", type=str, help="Trading symbol (default: BTCUSDT)")
    parser.add_argument("--start", type=parse_date, required=True, help="Start date (YYYY-MM-DD or T-30d)")
    parser.add_argument("--end", type=parse_date, required=True, help="End date (YYYY-MM-DD or now)")
    
    from src.utils.agent_utils import add_data_root_argument, resolve_data_root
    add_data_root_argument(parser)
    
    parser.add_argument("--sampling", type=int, required=True, help="Total number of samples to backtest")
    parser.add_argument("--mode", type=str, choices=["regime", "spaced"], required=True, 
                        help="Sampling mode: regime (stratified) or spaced (even)")

    args = parser.parse_args()
    
    # Resolve data_root
    data_root = args.data_root or resolve_data_root(args.env_shortcut)
    if not data_root:
        print("Error: --data_root or environment shortcut (e.g., prod, live) must be provided.")
        sys.exit(1)
        
    global_cfg = load_global_config()
    symbol = args.symbol or global_cfg['system']['default_symbol']
    
    # Temporal context resolution
    try:
        start_dt = args.start
        end_dt = args.end
        
        if start_dt >= end_dt:
            print("Error: Start date must be before end date.")
            sys.exit(1)
            
        orchestrator = BacktestOrchestrator(
            data_root=data_root,
            sampling_count=args.sampling,
            sampling_mode=args.mode
        )
        orchestrator.execute_simulation(start_dt, end_dt)
        
    except Exception as e:
        print(f"Backtest failed to initialize: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
