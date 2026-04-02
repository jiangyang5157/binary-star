#!/usr/bin/env python3
import os
import sys
import argparse
from datetime import datetime, timezone
from typing import Optional

# Setup paths
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.infrastructure.binance.client import BinanceFuturesClient
from src.analyzer.chart_generator import ChartGenerator
from src.analyzer.topography_engine import ObserverAgent, ObserverConfig
from src.utils.pipeline_utils import load_config, add_data_root_argument, resolve_data_root
from src.utils.datetime_utils import parse_iso_to_utc, get_current_utc_time
from src.utils.logger_utils import setup_logger

logger = setup_logger("StandaloneObserver")

def main():
    parser = argparse.ArgumentParser(description="Binary Star Observer - Standalone Topography Mapping")
    parser.add_argument("--symbol", type=str, default="BTCUSDT", help="Symbol to observe (e.g., BTCUSDT)")
    parser.add_argument("--ts", type=str, help="ISO timestamp for historical snapshot (e.g., 2024-03-12T10:00:00). Defaults to current time.")
    add_data_root_argument(parser)

    args = parser.parse_args()

    # 1. Resolve Data Environment
    data_root = args.data_root or resolve_data_root(args.env_shortcut)
    if not data_root:
        logger.error("Error: --data_root or environment shortcut (e.g., prod, live) must be provided.")
        sys.exit(1)
    logger.info(f"Environment Initialized. Path: {data_root}")

    # 2. Parse Timestamp
    target_ts: datetime = get_current_utc_time()
    if args.ts:
        try:
            target_ts = parse_iso_to_utc(args.ts)
            logger.info(f"Historical Mode: Capturing market topography at {target_ts.isoformat()}")
        except ValueError as e:
            logger.error(f"Invalid timestamp format: {e}. Use ISO 8601 (e.g., YYYY-MM-DDTHH:MM:SS)")
            sys.exit(1)
    else:
        logger.info(f"Real-time Mode: Capturing latest market topography.")

    # 3. Initialize Shared Infrastructure
    config = load_config()
    obs_config = ObserverConfig.from_dict(config)
    
    # Injected dependencies
    binance_client = BinanceFuturesClient()
    
    # ChartGenerator requires an initial output_dir
    img_dir = os.path.join(data_root, "klines")
    chart_gen = ChartGenerator(output_dir=img_dir)

    try:
        # 4. Instantiate and Execute Observer
        observer = ObserverAgent(
            config=obs_config,
            symbol=args.symbol,
            data_root=data_root,
            binance_client=binance_client,
            chart_generator=chart_gen
        )

        observation = observer.observe(timestamp=target_ts, data_root=data_root)

        if "error" in observation:
            logger.error(f"Observation failed: {observation.get('details')}")
            sys.exit(1)

        logger.info(f"Successfully captured topography for {args.symbol}")
        print(f"\n[TOPOGRAPHY CAPTURED]")
        print(f"Price: {observation.get('quantitative_metrics', {}).get('price_dynamics', {}).get('current_price')}")
        print(f"File: {data_root}/observations/ (See most recent)")

    except Exception as e:
        logger.error(f"Critical execution error: {e}", exc_info=True)
        sys.exit(1)
    finally:
        binance_client.close()

if __name__ == "__main__":
    main()
