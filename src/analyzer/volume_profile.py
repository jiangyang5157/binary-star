import pandas as pd
import numpy as np
from dataclasses import dataclass
from typing import List, Dict, Any
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
    atr_period: int                   # Window for Average True Range calculation
    max_volume_node_count: int                # Maximum structural nodes (HVN/LVN) to return
    high_volume_node_detection_threshold: float            # Prominence threshold for HVN detection
    low_volume_node_detection_threshold: float            # Prominence threshold for LVN detection
    min_node_gap_atr: float           # ATR multiplier for dynamic node separation
    ranging_width_atr: float          # ATR multiplier for state classification
    resolution_bins: int = 300        # Number of horizontal price buckets (fixed, not a strategy knob)

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
        Uses Range-Based Distribution and Contiguous Value Area Expansion.
        """
        if df.empty:
            return {}

        min_p, max_p = df['low'].min(), df['high'].max()
        num_bins = self.config.resolution_bins
        price_bins = np.linspace(min_p, max_p, num_bins + 1)
        v_profile = np.zeros(num_bins)
        
        # 1. Range-Based Volume Distribution (Vectorized — Fixes Wick Cut-off)
        low_bin = np.digitize(df['low'].values, price_bins) - 1
        high_bin = np.digitize(df['high'].values, price_bins) - 1
        low_bin = np.clip(low_bin, 0, num_bins - 1)
        high_bin = np.clip(high_bin, 0, num_bins - 1)
        num_covered = high_bin - low_bin + 1
        vol_per_bin = df['volume'].values / num_covered

        # Scatter-add: build flat index/value arrays for np.add.at
        indices = np.concatenate([np.arange(lo, hi + 1) for lo, hi in zip(low_bin, high_bin)])
        values = np.repeat(vol_per_bin, num_covered)
        np.add.at(v_profile, indices, values)

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
                
        vah = price_bins[va_idx_max + 1]  # upper edge of the highest VA bin
        val = price_bins[va_idx_min]
        
        # Audit log to trace VP data generation
        logger.debug(
            f"distribution complete | bins={num_bins} | total_vol={total_vol:.2f} | "
            f"max_vol_per_bin={v_profile.max():.2f} | "
            f"va_bins={va_idx_max - va_idx_min + 1}"
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

    def find_nodes(self, profile_result: Dict[str, Any], atr: float) -> Dict[str, List[Dict[str, Any]]]:
        """
        Identifies High Volume Nodes (peaks) and Low Volume Nodes (valleys).
        Uses dynamic ATR-based distancing for cross-asset scale invariance.
        """
        data = profile_result.get("profile_data", [])
        if not data or atr <= 0:
            return {"hvn": [], "lvn": []}
            
        vols = np.array([float(d['volume']) for d in data])
        prices = np.array([float(d['price']) for d in data])
        max_v = vols.max() if vols.size > 0 else 1.0
        
        # Calculate Dynamic Bin Distance
        # bin_width = (max_p - min_p) / num_bins
        # However, we can also derive it from the price array if it's evenly spaced
        price_range = prices.max() - prices.min()
        if price_range <= 0:
            bin_dist = 1
        else:
            bin_width = price_range / len(prices)
            bin_dist = max(1, int((atr * self.config.min_node_gap_atr) / bin_width))

        logger.debug(f"significant node | ATR={atr:.2f} | gap_ATR={self.config.min_node_gap_atr} | bin_dist={bin_dist}")

        # Detect HVNs (Local Maxima)
        h_peaks, _ = find_peaks(vols, 
                                prominence=max_v * self.config.high_volume_node_detection_threshold, 
                                distance=bin_dist)
        
        hvns = sorted([
            {"price": round(float(prices[i]), 2), "strength": round(float(vols[i] / max_v), 3)}
            for i in h_peaks
        ], key=lambda x: x['strength'], reverse=True)
        
        # Detect LVNs (Local Minima / Liquid Vacuums)
        l_valleys, _ = find_peaks(-vols, 
                                  prominence=max_v * self.config.low_volume_node_detection_threshold, 
                                  distance=bin_dist)
        
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
        Initializes the analyzer. Strictly requires a VolumeProfileConfig object.
        """
        if "config" in kwargs and isinstance(kwargs["config"], VolumeProfileConfig):
            self.config = kwargs["config"]
        else:
            raise ValueError("VolumeProfileAnalyzer: 'config' argument must be a VolumeProfileConfig instance.")
            
        self.preprocessor = MarketDataPreprocessor()
        self.engine = VolumeProfileEngine(self.config)
        self.node_finder = SignificantNodeFinder(self.config)

    def process_klines(self, klines_data: List[KlineData]) -> pd.DataFrame:
        """Entry point for data cleaning and feature engineering."""
        return self.preprocessor.prepare_dataframe(klines_data, self.config.atr_period)

    def calculate_profile(self, df: pd.DataFrame) -> Dict[str, Any]:
        """Entry point for volume distribution analysis."""
        return self.engine.compute_profile(df)

    def find_significant_nodes(self, profile_result: Dict[str, Any], atr: float) -> Dict[str, List[Dict[str, Any]]]:
        """Entry point for identifying structural support/resistance levels."""
        return self.node_finder.find_nodes(profile_result, atr=atr)

    def analyze(self, klines_data: List[KlineData]) -> Dict[str, Any]:
        """
        Full analysis pipeline: Preprocessing -> Profile calculation -> Node discovery.
        """
        if not klines_data:
            logger.warning("no kline data for Volume Profile analysis")
            return {
                "poc": 0.0, "vah": 0.0, "val": 0.0, 
                "hvn": [], "lvn": [], "market_regime": "UNKNOWN"
            }
            
        df = self.process_klines(klines_data)
        atr_val = df['atr'].iloc[-1] if not df.empty and 'atr' in df.columns else 0.0
        atr = float(atr_val) if pd.notna(atr_val) and atr_val > 0 else 0.0
        profile = self.calculate_profile(df)
        nodes = self.find_significant_nodes(profile, atr=atr)
        
        # Merge results
        result = profile.copy()
        result.update(nodes)
        
        return result
