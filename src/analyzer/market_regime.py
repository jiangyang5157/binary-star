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
    volatility_regime: str            # SQUEEZE, EXPANSION, NORMAL, or UNKNOWN
    squeeze_factor: float             # Ratio of BB width to KC width
    market_regime: str                # TRENDING, RANGING, or UNKNOWN
    trend_intensity: float            # Quantitative score of trend strength
    wick_skewness_lookback: float     # Bias in candle wicks (bullish/bearish asymmetry)
    vol_breakout: float               # Current volume relative to moving average

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

        # 2. Keltner Channels (using ATR)
        if 'tr' not in df.columns:
            h_l = df['high'] - df['low']
            h_cp = np.abs(df['high'] - df['close'].shift())
            l_cp = np.abs(df['low'] - df['close'].shift())
            df['tr'] = np.maximum(h_l, np.maximum(h_cp, l_cp))
        
        atr = df['tr'].rolling(window=self.config.keltner_window).mean()
        df['kc_upper'] = sma + (self.config.keltner_multiplier * atr)
        df['kc_lower'] = sma - (self.config.keltner_multiplier * atr)
        df['kc_width'] = df['kc_upper'] - df['kc_lower']

        # 3. Efficiency Ratio (Trend Intensity)
        # Abs(Total Price Change) / Sum(Abs(Individual Price Changes))
        lookback = self.config.trend_lookback
        price_diff = df['close'].diff()
        total_change = df['close'].iloc[-1] - df['close'].iloc[-lookback] if len(df) >= lookback else 0
        sum_abs_changes = price_diff.abs().rolling(window=lookback).sum().iloc[-1]
        df['trend_intensity'] = abs(total_change) / (sum_abs_changes + 1e-9)

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
        
        # 1. Squeeze Analysis (TTM Squeeze Logic)
        is_squeeze = (latest['bb_upper'] < latest['kc_upper']) and (latest['bb_lower'] > latest['kc_lower'])
        squeeze_factor = latest['bb_width'] / (latest['kc_width'] + 1e-9)
        
        if is_squeeze:
            vol_regime = "SQUEEZE"
        else:
            prev_squeeze = (df.iloc[-2]['bb_upper'] < df.iloc[-2]['kc_upper']) if len(df) > 1 else False
            vol_regime = "EXPANSION" if prev_squeeze else "NORMAL"

        # 2. Trend vs Range
        market_regime = "TRENDING" if latest['trend_intensity'] > self.config.trend_intensity_threshold else "RANGING"

        # 3. Wick Skewness (Bullish/Bearish Asymmetry)
        skewness = 0.0
        if all(col in df.columns for col in ['open', 'high', 'low', 'close']):
            recent = df.tail(self.config.wick_skewness_period)
            up_wicks = (recent['high'] - np.maximum(recent['open'], recent['close'])).sum()
            lo_wicks = (np.minimum(recent['open'], recent['close']) - recent['low']).sum()
            skewness = (up_wicks - lo_wicks) / (up_wicks + lo_wicks + 1e-9)

        # 4. Volume Breakout
        vol_ratio = 1.0
        if 'volume' in df.columns:
            vol_ma = df['volume'].rolling(window=self.config.volume_ma_window).mean()
            vol_ratio = latest['volume'] / (vol_ma.iloc[-1] + 1e-9)

        return RegimeResult(
            volatility_regime=vol_regime,
            squeeze_factor=round(float(squeeze_factor), 4),
            market_regime=market_regime,
            trend_intensity=round(float(latest['trend_intensity']), 4),
            wick_skewness_lookback=round(float(skewness), 4),
            vol_breakout=round(float(vol_ratio), 2)
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
                volume_ma_window=int(kwargs['vol_ma_window']),
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
            return asdict(RegimeResult("UNKNOWN", 1.0, "UNKNOWN", 0.0, 0.0, 1.0))

        processed_df = self.engine.calculate_indicators(df.copy())
        result = self.classifier.classify_regime(processed_df)
        return asdict(result)
