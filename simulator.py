import os
import logging
import pandas as pd
import numpy as np
from datetime import datetime, timedelta, timezone
from main import run_agent_a, load_config
from reviewer_main import run_reviewer_pipeline
from src.data_fetcher.binance_client import BinanceDataFetcher

# Setup logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("Simulator")

class MarketSimulator:
    """
    Backtesting simulator that identifies market regimes and runs 
    the Trader/Reviewer agents through historical snapshots.
    """
    def __init__(self, symbol: str = "BTCUSDT", sampling_count: int = 15):
        self.symbol = symbol
        self.sampling_count = sampling_count
        self.config = load_config()
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
        
        # Simple trend detection: Price vs 20-day Moving Average
        df['ma20'] = df['close'].rolling(window=20).mean()
        df['volatility'] = df['close'].pct_change().rolling(window=20).std()
        
        def classify(row):
            if pd.isna(row['ma20']): return "unknown"
            trend = "Bull" if row['close'] > row['ma20'] else "Bear"
            vol = "HighVol" if row['volatility'] > df['volatility'].median() else "LowVol"
            return f"{trend}_{vol}"
            
        df['regime'] = df.apply(classify, axis=1)
        return df

    def run_simulation(self, days_back: int = 365, start_date: datetime = None, end_date: datetime = None):
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

        # Sample dates from each regime to ensure diversity
        regimes = df['regime'].unique()
        samples_per_regime = max(1, self.sampling_count // len(regimes))
        
        target_dates = []
        for r in regimes:
            if r == "unknown": continue
            regime_df = df[df['regime'] == r]
            if not regime_df.empty:
                # Take a random sample or spaced sample
                subset = regime_df.sample(min(len(regime_df), samples_per_regime))
                target_dates.extend(subset['timestamp'].tolist())

        logger.info(f"Selected {len(target_dates)} historical points for simulation.")

        for dt in sorted(target_dates):
            logger.info(f"\n--- SIMULATING SNAPSHOT: {dt} ---")
            
            # 1. Run Trader Agent
            timestamp_str = dt.strftime("%Y%m%d_%H%M%S")
            pred_filename = f"{self.symbol}_prediction_{timestamp_str}.json"
            
            try:
                run_agent_a(override_timestamp=dt)
                
                # 2. Run Reviewer (Simulate N days in the future)
                future_dt = dt + timedelta(days=14)
                logger.info(f"Fast-forwarding to {future_dt} for review...")
                
                run_reviewer_pipeline(target_files=[pred_filename], override_now=future_dt, force=True)
                
            except Exception as e:
                logger.error(f"Simulation step failed for {dt}: {e}")

        logger.info("\n=== Simulation Complete ===")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Crypto Market Regime Backtesting Simulator")
    parser.add_argument("--symbol", type=str, default="BTCUSDT", help="Symbol to test")
    parser.add_argument("--days", type=int, default=365, help="Number of days to look back (default 365)")
    parser.add_argument("--sampling", type=int, default=20, help="Total number of points to sample (default 20)")
    parser.add_argument("--start", type=str, help="Start date (YYYY-MM-DD), overrides --days")
    parser.add_argument("--end", type=str, help="End date (YYYY-MM-DD), defaults to now")
    
    args = parser.parse_args()
    
    start_dt = None
    if args.start:
        start_dt = datetime.strptime(args.start, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        
    end_dt = None
    if args.end:
        end_dt = datetime.strptime(args.end, "%Y-%m-%d").replace(tzinfo=timezone.utc)

    sim = MarketSimulator(symbol=args.symbol, sampling_count=args.sampling)
    sim.run_simulation(days_back=args.days, start_date=start_dt, end_date=end_dt)
