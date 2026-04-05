import pandas as pd
import numpy as np
import logging
from dataclasses import dataclass, asdict
from typing import Dict, Any, Optional

# Initialize project-standard logger
from src.utils.logger_utils import setup_logger
logger = setup_logger(__name__)

@dataclass(frozen=True)
class MarketRegimeConfig:
    """
    Configuration parameters for Market Regime analysis.
    """
    bollinger_window: int             # Period for Bollinger Bands
    bollinger_std_dev: float           # Standard deviation for Bollinger Bands
    keltner_window: int               # Period for Keltner Channels
    keltner_multiplier: float          # ATR multiplier for Keltner Channels
    volume_ma_window: int              # Window for volume moving average
    trend_intensity_threshold: float            # Threshold for trend intensity classification
    trend_lookback: int                      # Lookback for efficiency ratio
    wick_skewness_period: int                # Lookback for wick analysis

@dataclass(frozen=True)
class RegimeResult:
    """
    Structured output of the market regime analysis.
    """
    squeeze_factor: float             # Ratio of BB width to KC width
    trend_intensity: float            # Signed Efficiency Ratio [-1, 1]. +ve = Bullish, -ve = Bearish
    wick_skewness_lookback: float     # Bias in candle wicks (bullish/bearish asymmetry)
    volume_participation_ratio: float      # Current volume relative to moving average

class IndicatorEngine:
    """
    Isolated engine for technical indicator calculations.
    """
    def __init__(self, config: MarketRegimeConfig):
        self.config = config

    def calculate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Calculates core indicators: Bollinger Bands, Keltner Channels, and Trend Intensity.
        """
        # 1. Bollinger Bands
        sma = df['close'].rolling(window=self.config.bollinger_window).mean()
        std = df['close'].rolling(window=self.config.bollinger_window).std()
        df['bb_upper'] = sma + (self.config.bollinger_std_dev * std)
        df['bb_lower'] = sma - (self.config.bollinger_std_dev * std)
        df['bb_width'] = df['bb_upper'] - df['bb_lower']

        # 2. Keltner Channels (独立 EMA 中心线 + ATR 通道)
        if 'tr' not in df.columns:
            h_l = df['high'] - df['low']
            h_cp = np.abs(df['high'] - df['close'].shift())
            l_cp = np.abs(df['low'] - df['close'].shift())
            df['tr'] = np.maximum(h_l, np.maximum(h_cp, l_cp))
        
        atr = df['tr'].rolling(window=self.config.keltner_window).mean()
        kc_ema = df['close'].ewm(span=self.config.keltner_window, adjust=False).mean()
        df['kc_upper'] = kc_ema + (self.config.keltner_multiplier * atr)
        df['kc_lower'] = kc_ema - (self.config.keltner_multiplier * atr)
        df['kc_width'] = df['kc_upper'] - df['kc_lower']

        # 3. Efficiency Ratio (Trend Intensity) - Signed, Vectorized
        # Net Displacement / Path Length. Positive = Bullish, Negative = Bearish.
        lookback = self.config.trend_lookback
        net_change = df['close'].diff(periods=lookback)
        sum_abs_changes = df['close'].diff().abs().rolling(window=lookback).sum()
        df['trend_intensity'] = net_change / (sum_abs_changes + 1e-9)

        return df

class RegimeClassifier:
    """
    Logic engine for classifying market states based on indicators.
    """
    def __init__(self, config: MarketRegimeConfig):
        self.config = config

    def classify_regime(self, df: pd.DataFrame) -> RegimeResult:
        """
        Interprets indicator values into meaningful market regimes.
        """
        latest = df.iloc[-1]
        
        # 1. Squeeze Analysis (Ratio Based)
        squeeze_factor = latest['bb_width'] / (latest['kc_width'] + 1e-9)
        
        # 2. Wick Skewness (Bullish/Bearish Asymmetry)
        skewness = 0.0
        if all(col in df.columns for col in ['open', 'high', 'low', 'close']):
            recent = df.tail(self.config.wick_skewness_period)
            up_wicks = (recent['high'] - np.maximum(recent['open'], recent['close'])).sum()
            lo_wicks = (np.minimum(recent['open'], recent['close']) - recent['low']).sum()
            skewness = (up_wicks - lo_wicks) / (up_wicks + lo_wicks + 1e-9)

        # 3. Volume Participation (Relative to MA)
        volume_participation_ratio = 1.0
        if 'volume' in df.columns:
            volume_ma = df['volume'].rolling(window=self.config.volume_ma_window).mean()
            volume_participation_ratio = latest['volume'] / (volume_ma.iloc[-1] + 1e-9)

        return RegimeResult(
            squeeze_factor=float(squeeze_factor),
            trend_intensity=float(latest['trend_intensity']),
            wick_skewness_lookback=float(skewness),
            volume_participation_ratio=float(volume_participation_ratio)
        )

class MarketRegimeAnalyzer:
    """
    Facade for Market Regime analysis.
    Orchestrates technical indicators and classification.
    """
    def __init__(self, **kwargs):
        """
        Initializes the analyzer. Supports individual arguments for backward compatibility.
        """
        if len(kwargs) == 1 and isinstance(next(iter(kwargs.values())), MarketRegimeConfig):
            self.config = next(iter(kwargs.values()))
        else:
            # Map legacy names to new config structure (strictly)
            self.config = MarketRegimeConfig(
                bollinger_window=int(kwargs['bb_window']),
                bollinger_std_dev=float(kwargs['bb_std']),
                keltner_window=int(kwargs['kc_window']),
                keltner_multiplier=float(kwargs['kc_mult']),
                volume_ma_window=int(kwargs['volume_ma_window']),
                trend_intensity_threshold=float(kwargs['trend_intensity_threshold']),
                trend_lookback=int(kwargs['trend_lookback']),
                wick_skewness_period=int(kwargs['wick_skewness_period'])
            )
            
        self.engine = IndicatorEngine(self.config)
        self.classifier = RegimeClassifier(self.config)

    def analyze(self, df: pd.DataFrame) -> Dict[str, Any]:
        """
        Entry point for market regime analysis.
        """
        if df.empty or len(df) < self.config.bollinger_window:
            logger.warning("Insufficient data for Market Regime analysis.")
            return asdict(RegimeResult(1.0, 0.0, 0.0, 1.0))

        processed_df = self.engine.calculate_indicators(df.copy())
        result = self.classifier.classify_regime(processed_df)
        return asdict(result)
