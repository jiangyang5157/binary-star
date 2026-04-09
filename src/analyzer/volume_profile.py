import pandas as pd
import numpy as np
import logging
from dataclasses import dataclass
from typing import List, Dict, Any, Optional
from scipy.signal import find_peaks

# Initialize project-standard logger
from src.utils.logger_utils import setup_logger
logger = setup_logger(__name__)

@dataclass(frozen=True)
class VolumeProfileConfig:
    """
    Configuration parameters for Volume Profile analysis.
    """
    value_area_ratio: float           # Percentage of volume to include in Value Area (configured via topography_parameters)
    resolution_bins: int              # Number of horizontal price buckets
    atr_period: int                   # Window for Average True Range calculation
    max_volume_node_count: int                # Maximum structural nodes (HVN/LVN) to return
    high_volume_node_detection_threshold: float            # Prominence threshold for HVN detection
    low_volume_node_detection_threshold: float            # Prominence threshold for LVN detection
    min_node_distance: int            # Minimum bin separation between nodes
    ranging_width_atr: float          # ATR multiplier for state classification

@dataclass(frozen=True)
class VolumeNode:
    """
    Represents a significant horizontal price level.
    """
    price: float
    strength: float                   # Relative strength/vacuum score (0.0 to 1.0)

from src.infrastructure.exchange.models import KlineData

class MarketDataPreprocessor:
    """
    Handles cleaning and enrichment of raw kline data.
    """
    @staticmethod
    def prepare_dataframe(klines_data: List[KlineData], atr_period: int) -> pd.DataFrame:
        """
        Converts domain KlineData objects into a technical-ready DataFrame.
        """
        if not klines_data: return pd.DataFrame()
        
        df = pd.DataFrame([vars(k) for k in klines_data])
        
        df["open_time"] = pd.to_datetime(df["open_time"], unit="ms")
        df.set_index("open_time", inplace=True)
        
        # Calculate ATR for volatility context
        h_l = df['high'] - df['low']
        h_cp = np.abs(df['high'] - df['close'].shift())
        l_cp = np.abs(df['low'] - df['close'].shift())
        tr = np.maximum(h_l, np.maximum(h_cp, l_cp))
        df['atr'] = tr.rolling(window=atr_period).mean()
        
        # Typical price for Volume-at-Price distribution estimation
        df['typical_price'] = (df['high'] + df['low'] + df['close']) / 3
        
        return df

class VolumeProfileEngine:
    """
    Mathematical engine for horizontal volume distribution.
    """
    def __init__(self, config: VolumeProfileConfig):
        self.config = config

    def compute_profile(self, df: pd.DataFrame) -> Dict[str, Any]:
        """
        Computes the volume profile distribution and key fair-value benchmarks.
        v7.2: Uses Range-Based Distribution and Contiguous Value Area Expansion.
        """
        if df.empty:
            return {}

        min_p, max_p = df['low'].min(), df['high'].max()
        num_bins = self.config.resolution_bins
        price_bins = np.linspace(min_p, max_p, num_bins + 1)
        v_profile = np.zeros(num_bins)
        
        # 1. Range-Based Volume Distribution (Fixes Wick Cut-off)
        for _, row in df.iterrows():
            low, high, vol = row['low'], row['high'], row['volume']
            # Find which bins the candle covers
            bin_start = np.digitize(low, price_bins) - 1
            bin_end = np.digitize(high, price_bins) - 1
            
            # Clip to valid range
            bin_start = max(0, min(num_bins - 1, bin_start))
            bin_end = max(0, min(num_bins - 1, bin_end))
            
            num_covered = bin_end - bin_start + 1
            vol_per_bin = vol / num_covered
            v_profile[bin_start : bin_end + 1] += vol_per_bin

        # 2. Point of Control (POC)
        poc_idx = np.argmax(v_profile)
        poc_price = price_bins[poc_idx]
        
        # 3. Contiguous Value Area (VA) Expansion from POC
        total_vol = v_profile.sum()
        target_va_vol = total_vol * self.config.value_area_ratio
        
        va_idx_min = poc_idx
        va_idx_max = poc_idx
        current_va_vol = v_profile[poc_idx]
        
        # Expand until target volume reached
        while current_va_vol < target_va_vol:
            # Check neighbors
            vol_above = 0
            if va_idx_max + 1 < num_bins:
                vol_above = v_profile[va_idx_max + 1]
                # Look 2 bins ahead for smoother expansion if available
                if va_idx_max + 2 < num_bins:
                    vol_above += v_profile[va_idx_max + 2]
            
            vol_below = 0
            if va_idx_min - 1 >= 0:
                vol_below = v_profile[va_idx_min - 1]
                if va_idx_min - 2 >= 0:
                    vol_below += v_profile[va_idx_min - 2]
            
            if vol_above >= vol_below and va_idx_max + 1 < num_bins:
                va_idx_max += 1
                current_va_vol += v_profile[va_idx_max]
            elif va_idx_min - 1 >= 0:
                va_idx_min -= 1
                current_va_vol += v_profile[va_idx_min]
            else:
                break # No more bins to expand into
                
        vah = price_bins[va_idx_max]
        val = price_bins[va_idx_min]
        
        # v7.2 Audit log to trace VP data generation
        logger.debug(
            f"VolumeProfileEngine: Distribution Complete. "
            f"Bins: {num_bins}, Total Vol: {total_vol:.2f}, "
            f"Max Vol/Bin: {v_profile.max():.2f}, "
            f"VA Bins: {va_idx_max - va_idx_min + 1}"
        )
        
        # Prepare profile data for reporting
        profile_data = []
        for i in range(num_bins):
            if v_profile[i] > 0:
                profile_data.append({"price": float(price_bins[i]), "volume": float(v_profile[i])})
                
        return {
            "poc": float(poc_price),
            "vah": float(vah),
            "val": float(val),
            "profile_data": profile_data
        }

class SignificantNodeFinder:
    """
    Isolates peak/vulnerability detection logic.
    """
    def __init__(self, config: VolumeProfileConfig):
        self.config = config

    def find_nodes(self, profile_result: Dict[str, Any]) -> Dict[str, List[Dict[str, Any]]]:
        """
        Identifies High Volume Nodes (peaks) and Low Volume Nodes (valleys).
        """
        data = profile_result.get("profile_data", [])
        if not data:
            return {"hvn": [], "lvn": []}
            
        vols = np.array([float(d['volume']) for d in data])
        prices = np.array([float(d['price']) for d in data])
        max_v = vols.max() if vols.size > 0 else 1.0
        
        # Detect HVNs (Local Maxima)
        h_peaks, _ = find_peaks(vols, 
                                prominence=max_v * self.config.high_volume_node_detection_threshold, 
                                distance=self.config.min_node_distance)
        
        hvns = sorted([
            {"price": round(float(prices[i]), 2), "strength": round(float(vols[i] / max_v), 3)}
            for i in h_peaks
        ], key=lambda x: x['strength'], reverse=True)
        
        # Detect LVNs (Local Minima / Liquid Vacuums)
        l_valleys, _ = find_peaks(-vols, 
                                  prominence=max_v * self.config.low_volume_node_detection_threshold, 
                                  distance=self.config.min_node_distance)
        
        lvns = sorted([
            {"price": round(float(prices[i]), 2), "vacuum_score": round(float(vols[i] / max_v), 3)}
            for i in l_valleys
        ], key=lambda x: x['vacuum_score'])
        
        return {
            "hvn": hvns[:self.config.max_volume_node_count],
            "lvn": lvns[:self.config.max_volume_node_count]
        }

class VolumeProfileAnalyzer:
    """
    Facade class for Volume Profile analysis.
    Orchestrates pre-processing, profile computation, and node discovery.
    """
    def __init__(self, **kwargs):
        """
        Initializes the analyzer. Supports individual arguments for backward compatibility
        with agents, or a VolumeProfileConfig object.
        """
        if len(kwargs) == 1 and isinstance(next(iter(kwargs.values())), VolumeProfileConfig):
            self.config = next(iter(kwargs.values()))
        else:
            # Map legacy names to new config structure (strictly)
            self.config = VolumeProfileConfig(
                value_area_ratio=float(kwargs['value_area_pct']),
                resolution_bins=int(kwargs['volume_profile_price_bucket_count']),
                atr_period=int(kwargs['atr_window']),
                max_volume_node_count=int(kwargs['max_volume_node_count']),
                high_volume_node_detection_threshold=float(kwargs['high_volume_node_detection_threshold']),
                low_volume_node_detection_threshold=float(kwargs['low_volume_node_detection_threshold']),
                min_node_distance=int(kwargs['node_min_separation']),
                ranging_width_atr=float(kwargs['ranging_width_atr'])
            )
            
        self.preprocessor = MarketDataPreprocessor()
        self.engine = VolumeProfileEngine(self.config)
        self.node_finder = SignificantNodeFinder(self.config)

    def process_klines(self, klines_data: List[KlineData]) -> pd.DataFrame:
        """Entry point for data cleaning and feature engineering."""
        return self.preprocessor.prepare_dataframe(klines_data, self.config.atr_period)

    def calculate_profile(self, df: pd.DataFrame) -> Dict[str, Any]:
        """Entry point for volume distribution analysis."""
        return self.engine.compute_profile(df)

    def find_significant_nodes(self, profile_result: Dict[str, Any]) -> Dict[str, List[Dict[str, Any]]]:
        """Entry point for identifying structural support/resistance levels."""
        return self.node_finder.find_nodes(profile_result)

    def analyze(self, klines_data: List[KlineData]) -> Dict[str, Any]:
        """
        Full analysis pipeline: Preprocessing -> Profile calculation -> Node discovery.
        """
        if not klines_data:
            logger.warning("No kline data provided for Volume Profile analysis.")
            return {
                "poc": 0.0, "vah": 0.0, "val": 0.0, 
                "hvn": [], "lvn": [], "market_regime": "UNKNOWN"
            }
            
        df = self.process_klines(klines_data)
        profile = self.calculate_profile(df)
        nodes = self.find_significant_nodes(profile)
        
        # Merge results
        result = profile.copy()
        result.update(nodes)
        
        return result
