import os
import logging
import pandas as pd
import numpy as np
from datetime import datetime, timedelta, timezone
from typing import List, Optional

# Setup logging BEFORE imports to ensure it is configured correctly
logging.basicConfig(
    level=logging.INFO, 
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("simulator.log"),
        logging.StreamHandler()
    ],
    force=True  # Force configuration even if handlers already exist
)
logger = logging.getLogger("Simulator")

# Now safe to import internal modules
from predictor import run_predictor, load_config
from review import main_review as run_reviewer_pipeline
from src.data_fetcher.binance_client import BinanceDataFetcher

class MarketSimulator:
    """
    Backtesting simulator that identifies market regimes and runs 
    the Predictor/Reviewer agents through historical snapshots.
    """
    def __init__(self, sampling_count: int = 20, sampling_mode: str = "regime"):
        self.config = load_config()
        self.symbol = self.config['symbol']
        self.sampling_count = sampling_count
        self.sampling_mode = sampling_mode
        self.fetcher = BinanceDataFetcher()

    def identify_regimes(self, days_limit: int = 365) -> pd.DataFrame:
        """
        Fetches daily data and classifies periods into Bull/Bear/Sideways.
        """
        logger.info(f"Analyzing past {days_limit} days for market regimes...")
        klines = self.fetcher.fetch_historical_klines(
            symbol=self.symbol,
            interval="1d",
            limit=min(days_limit, 1000) # Binance limit usually 500-1000
        )
        
        if not klines:
            logger.error("Failed to fetch daily klines for regime detection.")
            return pd.DataFrame()

        df = pd.DataFrame(klines, columns=[
            'timestamp', 'open', 'high', 'low', 'close', 'volume',
            'close_time', 'qav', 'num_trades', 'taker_base_vol', 'taker_quote_vol', 'ignore'
        ])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms', utc=True)
        df['close'] = df['close'].astype(float)
        
        # Trend detection: Price vs 21-day Exponential Moving Average (EMA)
        # EMA21 is a widely used Fibonacci-based benchmark for trend health.
        df['ema21'] = df['close'].ewm(span=21, adjust=False).mean()
        df['volatility'] = df['close'].pct_change().rolling(window=21).std()
        
        def classify(row):
            if pd.isna(row['ema21']): return "unknown"
            trend = "Bull" if row['close'] > row['ema21'] else "Bear"
            vol = "HighVol" if row['volatility'] > df['volatility'].median() else "LowVol"
            return f"{trend}_{vol}"
            
        df['regime'] = df.apply(classify, axis=1)
        return df

    def run_simulation(self, days_back: int = 365, start_date: Optional[datetime] = None, end_date: Optional[datetime] = None):
        """
        Main simulation loop.
        """
        # Determine how many daily bars to fetch for regime analysis
        if start_date:
            now = datetime.now(timezone.utc)
            delta = now - start_date
            days_limit = delta.days + 30 # Extra buffer for MA calculation
        else:
            days_limit = days_back + 30

        df = self.identify_regimes(days_limit=days_limit)
        if df.empty: return

        # Filter by start/end if provided
        if start_date:
            df = df[df['timestamp'] >= start_date]
        if end_date:
            df = df[df['timestamp'] <= end_date]
            
        if df.empty:
            logger.warning("No data found in the specified time range.")
            return

        # Determine sampling strategy
        sampling_mode = getattr(self, 'sampling_mode', 'regime')
        target_dates = []

        logger.info(f"Requested sampling count: {self.sampling_count}")
        if sampling_mode == 'spaced':
            # Option A: Spaced Sampling (Equal intervals)
            if len(df) <= self.sampling_count:
                target_dates = df['timestamp'].tolist()
            else:
                indices = np.linspace(0, len(df) - 1, self.sampling_count, dtype=int)
                target_dates = df.iloc[indices]['timestamp'].tolist()
            logger.info(f"Using Spaced Sampling: Picked {len(target_dates)} points evenly across the range.")
        else:
            # Option B: Regime-based Stratified Sampling (Current default)
            regimes = df['regime'].unique()
            samples_per_regime = max(1, self.sampling_count // len(regimes))
            
            for r in regimes:
                if r == "unknown": continue
                regime_df = df[df['regime'] == r]
                if not regime_df.empty:
                    subset = regime_df.sample(min(len(regime_df), samples_per_regime))
                    target_dates.extend(subset['timestamp'].tolist())
            logger.info(f"Using Regime-based Sampling: Selected {len(target_dates)} historical points from {len(regimes)} regimes.")

        logger.info(f"Total samples finalized: {len(target_dates)}")
        
        for i, dt in enumerate(sorted(target_dates), 1):
            logger.info(f"\n--- SIMULATING SNAPSHOT {i}/{len(target_dates)}: {dt} ---")
            
            # 1. Run Predictor Agent
            timestamp_str = dt.strftime("%Y%m%d_%H%M%S")
            pred_filename = f"{self.symbol}_prediction_{timestamp_str}.json"
            
            try:
                run_predictor(override_timestamp=dt)
                logger.info(f"Successfully finished prediction: {pred_filename}")
                
                # 2. Run Reviewer (Simulate N days in the future)
                review_days = self.config['prediction']['prediction_horizon_days']
                future_dt = dt + timedelta(days=review_days)
                logger.info(f"Fast-forwarding to {future_dt} for review...")
                
                run_reviewer_pipeline(target_files=[pred_filename], override_now=future_dt, force=True)
                logger.info(f"Successfully finished review for: {pred_filename}")
                
            except Exception as e:
                logger.error(f"Simulation step failed for {dt}: {e}")

        logger.info("\n=== Simulation Complete ===")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Crypto Market Regime Backtesting Simulator")
    parser.add_argument("--days", type=int, default=30, help="Number of days to look back (default 30)")
    parser.add_argument("--sampling", type=int, default=15, help="Total number of points to sample (default 15)")
    parser.add_argument("--start", type=str, help="Start date (YYYY-MM-DD), overrides --days")
    parser.add_argument("--end", type=str, help="End date (YYYY-MM-DD), defaults to now")
    parser.add_argument("--mode", type=str, choices=["regime", "spaced"], default="regime", help="Sampling mode: regime (stratified random) or spaced (even intervals)")
    
    args = parser.parse_args()
    
    start_dt = None
    if args.start:
        start_dt = datetime.strptime(args.start, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        
    end_dt = None
    if args.end:
        end_dt = datetime.strptime(args.end, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    
    # 30-day sentiment warning
    if start_dt:
        days_ago = (datetime.now(timezone.utc) - start_dt).days
        if days_ago > 30:
            logger.warning("WARNING: Backtest starts > 30 days ago. Sentiment data (OI/LS) will be N/A due to Binance API limits.")

    sim = MarketSimulator(sampling_count=args.sampling, sampling_mode=args.mode)
    sim.run_simulation(days_back=args.days, start_date=start_dt, end_date=end_dt)
