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

    def identify_regimes(self, days_back: int = 365) -> pd.DataFrame:
        """
        Fetches daily data and classifies periods into Bull/Bear/Sideways.
        """
        logger.info(f"Analyzing past {days_back} days for market regimes...")
        klines = self.fetcher.fetch_historical_klines(
            symbol=self.symbol,
            interval="1d",
            limit=days_back
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

    def run_simulation(self):
        """
        Main simulation loop.
        """
        df = self.identify_regimes()
        if df.empty: return

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
            # Note: run_agent_a saves the file. We need to capture the filename it produces.
            # Filename format: BTCUSDT_prediction_YYYYMMDD_HHMMSS.json
            timestamp_str = dt.strftime("%Y%m%d_%H%M%S")
            pred_filename = f"{self.symbol}_prediction_{timestamp_str}.json"
            
            try:
                run_agent_a(override_timestamp=dt)
                
                # 2. Run Reviewer (Simulate N days in the future)
                future_dt = dt + timedelta(days=14)
                logger.info(f"Fast-forwarding to {future_dt} for review...")
                
                run_reviewer_pipeline(target_files=[pred_filename], override_now=future_dt)
                
            except Exception as e:
                logger.error(f"Simulation step failed for {dt}: {e}")

        logger.info("\n=== Simulation Complete ===")

if __name__ == "__main__":
    sim = MarketSimulator(sampling_count=10) # Start small for testing
    sim.run_simulation()
