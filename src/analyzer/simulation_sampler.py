import pandas as pd
import numpy as np
from datetime import datetime
from typing import List, Tuple
from abc import ABC, abstractmethod

from src.utils.logger_utils import setup_logger

logger = setup_logger(__name__)

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

class SniperSampler(Sampler):
    """
    Intelligence-Led Sampler.
    
    Instead of random buckets, it scans the historical range for 
    'Noteworthy' events (Squeezes, CVD extremes, Volatility Ignition) 
    using the Sniper Wake-Up Matrix.
    """
    def __init__(self, symbol: str):
        super().__init__()
        self.symbol = symbol
        # Lazy imports to avoid circular dependencies
        from src.sniper.scout import SniperScout
        from src.sniper.trigger import SniperTrigger
        
        self.scout = SniperScout(symbol)
        self.trigger = SniperTrigger()

    def sample(self, df: pd.DataFrame, count: int) -> List[datetime]:
        """
        Scans the historical timeline for asymmetry and picks the most noteworthy points.
        """
        if df.empty or count <= 0:
            return []

        logger.info(f"SniperSampler: Scanning {len(df)} candidate points for noteworthy events...")
        
        noteworthy_points: List[Tuple[datetime, str, str]] = []
        prev_metrics = None
        
        for index, row in df.iterrows():
            dt = row['timestamp']
            
            try:
                # 1. Scout the historical moment
                res = self.scout.scout(at_time=dt)
                if not res.metrics:
                    continue
                
                # 2. Evaluate for 'Interest'
                is_noteworthy, event_type, reason = self.trigger.evaluate(res.metrics, prev_metrics)
                
                if is_noteworthy:
                    logger.info(f"SniperSampler: Found noteworthy event at {dt}: [{event_type}] {reason}")
                    noteworthy_points.append((dt, event_type, reason))
                    # Reset the trigger cooldown state in memory for sampling 
                    self.trigger.last_trigger_time = None 
                
                prev_metrics = res.metrics
                
            except Exception as e:
                logger.error(f"SniperSampler: Error at {dt}: {e}")
                continue

        if not noteworthy_points:
            logger.warning("SniperSampler: No noteworthy events found in range. Falling back to spaced sampling.")
            return SpacedSampler().sample(df, count)

        # Proportional Sampling across event types
        event_df = pd.DataFrame(noteworthy_points, columns=['timestamp', 'type', 'reason'])
        
        if len(event_df) <= count:
            return event_df['timestamp'].tolist()
        
        # Stratified sample by event type
        sampled_rows = event_df.groupby('type', group_keys=False).apply(
            lambda x: x.sample(n=min(len(x), max(1, int(len(x) / len(event_df) * count))))
        )
        
        if len(sampled_rows) < count:
            remaining = event_df[~event_df.index.isin(sampled_rows.index)]
            fill_count = min(len(remaining), count - len(sampled_rows))
            if fill_count > 0:
                sampled_rows = pd.concat([sampled_rows, remaining.sample(fill_count)])

        return sorted(sampled_rows['timestamp'].tolist())
