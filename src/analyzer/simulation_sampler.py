import pandas as pd
import numpy as np
import logging
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
from abc import ABC, abstractmethod

from src.utils.logger_utils import setup_logger

logger = setup_logger(__name__)

class SimpleRegimeClassifier:
    """
    Analyzes historical price data to classify market conditions (regimes).
    Uses EMA and Volatility to distinguish between Bull/Bear and High/Low Volatility states.
    """
    def __init__(self, ema_period: int, volatility_period: int, warmup_multiplier: float):
        self.ema_period = ema_period
        self.volatility_period = volatility_period
        self.warmup_multiplier = warmup_multiplier

    def warmup_candles(self) -> int:
        """Returns the number of candles needed for indicator convergence."""
        return int(max(self.ema_period, self.volatility_period) * self.warmup_multiplier)

    def classify_regimes(self, klines: List[List[Any]]) -> pd.DataFrame:
        """
        Processes raw Binance klines into a DataFrame with regime classifications.
        """
        if not klines:
            logger.error("No klines provided for regime analysis.")
            return pd.DataFrame()

        df = pd.DataFrame(klines, columns=[
            'timestamp', 'open', 'high', 'low', 'close', 'volume',
            'close_time', 'qav', 'num_trades', 'taker_base_vol', 'taker_quote_vol', 'ignore'
        ])
        
        # Convert types
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms', utc=True)
        df['close'] = df['close'].astype(float)
        
        # 1. Trend Detection: Price vs EMA21
        df['ema'] = df['close'].ewm(span=self.ema_period, adjust=False).mean()
        
        # 2. Volatility Detection: Rolling Standard Deviation of Returns
        df['returns'] = df['close'].pct_change()
        df['volatility'] = df['returns'].rolling(window=self.volatility_period).std()
        
        median_vol = df['volatility'].median()
        
        def _get_regime(row):
            if pd.isna(row['ema']) or pd.isna(row['volatility']):
                return "UNKNOWN"
            
            trend = "BULL" if row['close'] > row['ema'] else "BEAR"
            vol = "HIGH_VOL" if row['volatility'] > median_vol else "LOW_VOL"
            return f"{trend}_{vol}"
            
        df['regime'] = df.apply(_get_regime, axis=1)
        
        # Filter out unknown rows to ensure clean sampling
        return df[df['regime'] != "UNKNOWN"].copy()

class Sampler(ABC):
    """Abstract base class for sampling historical timestamps."""
    def __init__(self):
        pass

    @abstractmethod
    def sample(self, df: pd.DataFrame, count: int) -> List[datetime]:
        pass



class SpacedSampler(Sampler):
    """Samples timestamps evenly across the provided date range."""
    def sample(self, df: pd.DataFrame, count: int) -> List[datetime]:
        if df.empty or count <= 0:
            return []
        
        if len(df) <= count:
            logger.warning(f"Requested {count} samples but only {len(df)} available. Returning all.")
            raw_dates = df['timestamp'].tolist()
        else:
            indices = np.linspace(0, len(df) - 1, count, dtype=int)
            raw_dates = df.iloc[indices]['timestamp'].tolist()
            
        return raw_dates

class RegimeSampler(Sampler):
    """
    Performs stratified random sampling based on market regimes.
    Ensures proportional representation of different market conditions.
    """
    def __init__(self):
        pass

    def sample(self, df: pd.DataFrame, count: int) -> List[datetime]:
        if df.empty or count <= 0:
            return []

        regimes = df['regime'].unique()
        if len(regimes) == 0:
            return []

        # Proportional allocation
        counts_per_regime = df['regime'].value_counts()
        total_available = len(df)
        
        # Calculate target samples per regime while ensuring we hit exactly 'count'
        # Formula: (regime_size / total_size) * target_count
        raw_allocations = (counts_per_regime / total_available) * count
        allocations = raw_allocations.round().astype(int)
        
        # Adjust for rounding errors to hit exactly 'count'
        current_sum = allocations.sum()
        remainder = count - current_sum
        
        if remainder != 0:
            # Add/subtract from the largest regime(s)
            adjustment_indices = raw_allocations.sort_values(ascending=False).index
            for i in range(abs(remainder)):
                idx = adjustment_indices[i % len(adjustment_indices)]
                allocations[idx] += (1 if remainder > 0 else -1)

        target_dates = []
        for regime, n_samples in allocations.items():
            if n_samples <= 0:
                continue
            
            regime_subset = df[df['regime'] == regime]
            # Safety: don't sample more than available in this regime
            n_to_pick = min(len(regime_subset), n_samples)
            
            sampled = regime_subset.sample(n=n_to_pick, random_state=42) # Deterministic for auditability
            target_dates.extend(sampled['timestamp'].tolist())

        # Sort chronologically for better simulation flow
        return sorted(target_dates)
