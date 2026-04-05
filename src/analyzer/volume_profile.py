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
    max_high_volume_node_count: int                # Maximum High Volume Nodes to return
    max_low_volume_node_count: int                # Maximum Low Volume Nodes to return
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

class MarketDataPreprocessor:
    """
    Handles cleaning and enrichment of raw kline data.
    """
    @staticmethod
    def prepare_dataframe(klines_data: List[List[Any]], atr_period: int) -> pd.DataFrame:
        """
        Converts raw Binance klines into a technical-ready DataFrame.
        """
        # Binance Kline format: [Time, O, H, L, C, V, CloseTime, QVol, Trades, TakerBase, TakerQuote, Ignore]
        df = pd.DataFrame(klines_data, columns=[
            "open_time", "open", "high", "low", "close", "volume", 
            "close_time", "quote_volume", "trades", "taker_buy_base", 
            "taker_buy_quote", "ignore"
        ])
        
        # Convert to numeric
        numeric_cols = ["open", "high", "low", "close", "volume", "taker_buy_base"]
        for col in numeric_cols:
            df[col] = pd.to_numeric(df[col], errors='coerce')
            
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
        """
        if df.empty:
            return {}

        min_p, max_p = df['low'].min(), df['high'].max()
        price_bins = np.linspace(min_p, max_p, self.config.resolution_bins + 1)
        
        # Binning and aggregation
        df['bin'] = np.digitize(df['typical_price'], price_bins)
        profile = df.groupby('bin')['volume'].sum().reset_index()
        profile['price'] = profile['bin'].apply(lambda x: price_bins[x-1] if x > 0 else price_bins[0])
        
        # Point of Control (POC) - Peak Activity
        poc_idx = profile['volume'].idxmax()
        poc_price = profile.loc[poc_idx, 'price']
        
        # Value Area (VA) - Core Trading Range (e.g., 70% of volume)
        total_vol = profile['volume'].sum()
        target_va_vol = total_vol * self.config.value_area_ratio
        
        sorted_profile = profile.sort_values(by='volume', ascending=False)
        cumulative_vol = 0
        va_prices = []
        for _, row in sorted_profile.iterrows():
            cumulative_vol += row['volume']
            va_prices.append(row['price'])
            if cumulative_vol >= target_va_vol:
                break
                
        vah = max(va_prices) if va_prices else poc_price
        val = min(va_prices) if va_prices else poc_price
        
        # Balanced/Imbalanced State (VA Width vs ATR-Macro)
        # Note: We assume the profile's 'atr' for the latest bar is passed or accessible.
        # But since we are in the engine, we just return the anchors and let the facade handle regime.
        
        return {
            "poc": poc_price,
            "vah": vah,
            "val": val,
            "profile_data": profile[['price', 'volume']].to_dict('records')
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
            "hvn": hvns[:self.config.max_high_volume_node_count],
            "lvn": lvns[:self.config.max_low_volume_node_count]
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
                resolution_bins=int(kwargs['vol_profile_bins']),
                atr_period=int(kwargs['atr_window']),
                max_high_volume_node_count=int(kwargs['max_high_volume_node_count']),
                max_low_volume_node_count=int(kwargs['max_low_volume_node_count']),
                high_volume_node_detection_threshold=float(kwargs['high_volume_node_detection_threshold']),
                low_volume_node_detection_threshold=float(kwargs['low_volume_node_detection_threshold']),
                min_node_distance=int(kwargs['node_min_separation']),
                ranging_width_atr=float(kwargs['ranging_width_atr'])
            )
            
        self.preprocessor = MarketDataPreprocessor()
        self.engine = VolumeProfileEngine(self.config)
        self.node_finder = SignificantNodeFinder(self.config)

    def process_klines(self, klines_data: List[List[Any]]) -> pd.DataFrame:
        """Entry point for data cleaning and feature engineering."""
        return self.preprocessor.prepare_dataframe(klines_data, self.config.atr_period)

    def calculate_profile(self, df: pd.DataFrame) -> Dict[str, Any]:
        """Entry point for volume distribution analysis."""
        return self.engine.compute_profile(df)

    def find_significant_nodes(self, profile_result: Dict[str, Any]) -> Dict[str, List[Dict[str, Any]]]:
        """Entry point for identifying structural support/resistance levels."""
        return self.node_finder.find_nodes(profile_result)

    def analyze(self, klines_data: List[List[Any]]) -> Dict[str, Any]:
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
