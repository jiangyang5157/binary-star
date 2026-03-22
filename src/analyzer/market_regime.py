import pandas as pd
import numpy as np
from typing import Dict, Any

class MarketRegimeAnalyzer:
    """
    Analyzes market volatility regimes and trends.
    Focuses on Volatility Squeeze (BB vs KC) and Trend Intensity.
    """
    def __init__(self, bb_window: int, bb_std: float, kc_window: int, kc_mult: float, vol_ma_window: int, trend_intensity_threshold: float):
        self.bb_window = bb_window
        self.bb_std = bb_std
        self.kc_window = kc_window
        self.kc_mult = kc_mult
        self.vol_ma_window = vol_ma_window
        self.trend_intensity_threshold = trend_intensity_threshold

    def analyze(self, df: pd.DataFrame) -> Dict[str, Any]:
        """
        Calculates Squeeze and Regime metrics.
        """
        if df.empty or len(df) < self.bb_window:
            return {
                "volatility_regime": "UNKNOWN",
                "squeeze_factor": 0.0,
                "market_regime": "UNKNOWN",
                "trend_intensity": 0.0,
                "skewness": 0.0
            }

        # 1. Bollinger Bands
        sma = df['close'].rolling(window=self.bb_window).mean()
        std = df['close'].rolling(window=self.bb_window).std()
        df['bb_upper'] = sma + (self.bb_std * std)
        df['bb_lower'] = sma - (self.bb_std * std)
        df['bb_width'] = df['bb_upper'] - df['bb_lower']

        # 2. Keltner Channels (using ATR)
        # Assuming 'tr' is already in df from VolumeProfileAnalyzer or calculate it here
        if 'tr' not in df.columns:
            high_low = df['high'] - df['low']
            high_cp = np.abs(df['high'] - df['close'].shift())
            low_cp = np.abs(df['low'] - df['close'].shift())
            df['tr'] = np.maximum(high_low, np.maximum(high_cp, low_cp))
        
        atr = df['tr'].rolling(window=self.kc_window).mean()
        df['kc_upper'] = sma + (self.kc_mult * atr)
        df['kc_lower'] = sma - (self.kc_mult * atr)
        df['kc_width'] = df['kc_upper'] - df['kc_lower']

        # 3. Squeeze Detection (TTM Squeeze logic)
        # Squeeze is ON if BB is completely inside KC
        latest = df.iloc[-1]
        is_squeeze = (latest['bb_upper'] < latest['kc_upper']) and (latest['bb_lower'] > latest['kc_lower'])
        
        # Squeeze Factor: How tight is the BB relative to KC?
        # If < 1.0, it's squeezing. The smaller, the tighter.
        squeeze_factor = latest['bb_width'] / latest['kc_width'] if latest['kc_width'] > 0 else 1.0

        # 4. Market Regime (Trend vs Range)
        # Simple method: use ADX-like logic or Price Correlation
        # Let's use a 14-period ADX calculation if possible, or simpler: 
        # Trend Intensity = Abs(Price Change) / Sum(Abs(Individual Price Changes)) over window
        window = 14
        price_diff = df['close'].diff()
        abs_price_diff = price_diff.abs()
        total_change = df['close'].iloc[-1] - df['close'].iloc[-window] if len(df) >= window else 0
        sum_abs_changes = abs_price_diff.rolling(window=window).sum().iloc[-1]
        
        trend_intensity = abs(total_change) / sum_abs_changes if sum_abs_changes > 0 else 0.0
        
        market_regime = "TRENDING" if trend_intensity > self.trend_intensity_threshold else "RANGING"
        if is_squeeze:
            volatility_regime = "SQUEEZE"
        else:
            # Check if we just exited a squeeze (expansion)
            prev_squeeze = (df.iloc[-2]['bb_upper'] < df.iloc[-2]['kc_upper']) if len(df) > 1 else False
            volatility_regime = "EXPANSION" if prev_squeeze else "NORMAL"

        # 5. Skewness (Wick Analysis)
        # Ratio of upper wicks to lower wicks in the last few bars
        skewness = 0.0
        if all(col in df.columns for col in ['open', 'high', 'low', 'close']):
            recent = df.tail(5)
            upper_wicks = (recent['high'] - np.maximum(recent['open'], recent['close'])).sum()
            lower_wicks = (np.minimum(recent['open'], recent['close']) - recent['low']).sum()
            # Avoid division by zero
            skewness = (upper_wicks - lower_wicks) / (upper_wicks + lower_wicks + 1e-9)

        # 6. Volume Breakout Ratio (V3)
        current_vol_ratio = 1.0
        if 'volume' in df.columns:
            df['vol_ma'] = df['volume'].rolling(window=self.vol_ma_window).mean()
            df['volume_breakout_ratio'] = df['volume'] / (df['vol_ma'] + 1e-9)
            df['volume_breakout_ratio'] = df['volume_breakout_ratio'].fillna(1.0)
            current_vol_ratio = df['volume_breakout_ratio'].iloc[-1]

        return {
            "volatility_regime": volatility_regime,
            "squeeze_factor": round(float(squeeze_factor), 4),
            "market_regime": market_regime,
            "trend_intensity": round(float(trend_intensity), 4),
            "skewness": round(float(skewness), 4),
            "volume_breakout_ratio": round(float(current_vol_ratio), 2)
        }
