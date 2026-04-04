import os
import logging
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use('Agg')  # Non-interactive backend
import matplotlib.pyplot as plt
import matplotlib.patches as patches
import mplfinance as mpf
from dataclasses import dataclass
from typing import Dict, List, Any, Optional
from src.utils.datetime_utils import format_timestamp_for_filename, get_current_utc_time

# Initialize project-standard logger
from src.utils.logger_utils import setup_logger
logger = setup_logger(__name__)

@dataclass(frozen=True)
class ChartConfig:
    """
    Configuration and styling tokens for chart generation.
    """
    up_color: str = '#26a69a'       # Teal
    down_color: str = '#ef5350'     # Coral
    bg_color: str = '#131722'       # Dark TradingView style
    grid_color: str = '#333333'
    poc_color: str = '#ff9800'      # Orange
    va_color: str = '#fbc02d'       # Gold
    liq_buy_color: str = '#00ff88'  # Neon Green
    liq_sell_color: str = '#ff3366' # Neon Pink
    volume_chart_scaling: float = 0.20 # 20% of axis width
    dpi: int = 180

class TechnicalFeatureExtractor:
    """
    Handles detection of visual technical structures (e.g., Trendlines).
    """
    @staticmethod
    def detect_trendlines(df: pd.DataFrame, window: int = 5) -> List[Dict[str, Any]]:
        """
        Detects fractal highs and lows to generate trendline segments.
        """
        try:
            # Detect local peaks (highs) and valleys (lows)
            highs = df['high'].rolling(window=window, center=True).max() == df['high']
            lows = df['low'].rolling(window=window, center=True).min() == df['low']
            
            peak_indices = np.where(highs)[0]
            valley_indices = np.where(lows)[0]
            
            trendlines = []
            # Use last 3 peaks/valleys to draw recent structure
            if len(peak_indices) >= 3:
                for i in range(1, 3):
                    p1, p2 = peak_indices[-(i+1)], peak_indices[-i]
                    trendlines.append({
                        'x': [p1, p2], 
                        'y': [df['high'].iloc[p1], df['high'].iloc[p2]], 
                        'color': '#2a9d8f'
                    })
                
            if len(valley_indices) >= 3:
                for i in range(1, 3):
                    v1, v2 = valley_indices[-(i+1)], valley_indices[-i]
                    trendlines.append({
                        'x': [v1, v2], 
                        'y': [df['low'].iloc[v1], df['low'].iloc[v2]], 
                        'color': '#2a9d8f'
                    })
            
            return trendlines
        except Exception as e:
            logger.warning(f"Trendline detection failed: {e}")
            return []

class ChartStorageManager:
    """
    Handles filename generation and filesystem interactions.
    """
    def __init__(self, output_dir: str):
        self.output_dir = output_dir
        os.makedirs(self.output_dir, exist_ok=True)

    def generate_filepath(self, symbol: str, time_interval: str, timestamp: Optional[str] = None) -> str:
        """
        Generates a standard filename: {symbol}_{time_interval}_klines_{ts_readable}.png
        """
        if timestamp:
            ts_readable = format_timestamp_for_filename(timestamp)
        else:
            # Fallback to current UTC if no timestamp provided
            ts_readable = format_timestamp_for_filename(get_current_utc_time().isoformat())
            
        filename = f"{symbol}_klines_{time_interval}_{ts_readable}.png"
        return os.path.join(self.output_dir, filename)

class ChartVisualRenderer:
    """
    Core engine for rendering candlestick charts with logical overlays.
    """
    def __init__(self, output_dir: str, volume_chart_scaling: float, dpi: int):
        self.config = ChartConfig(volume_chart_scaling=volume_chart_scaling, dpi=dpi)
        self.storage = ChartStorageManager(output_dir)
        self.extractor = TechnicalFeatureExtractor()

    def _prepare_plot_df(self, df: pd.DataFrame) -> pd.DataFrame:
        """Standardizes DataFrame columns for mplfinance."""
        return df.rename(columns={
            "open": "Open", "high": "High", "low": "Low", 
            "close": "Close", "volume": "Volume"
        })

    def _get_mpf_style(self):
        """Creates the professional high-contrast style."""
        mc = mpf.make_marketcolors(
            up=self.config.up_color, 
            down=self.config.down_color, 
            edge='inherit', 
            wick='inherit', 
            volume='in'
        )
        return mpf.make_mpf_style(
            marketcolors=mc, 
            gridstyle='--', 
            gridcolor=self.config.grid_color, 
            y_on_right=True, 
            facecolor=self.config.bg_color
        )

    def generate_chart(self, symbol: str, df: pd.DataFrame, profile_data: Dict[str, Any], 
                       liquidations: Optional[List[Dict[str, Any]]] = None, time_interval: str = "1h") -> str:
        """
        Orchestrates the generation of an enhanced candlestick chart.
        """
        if df.empty:
            logger.error(f"Cannot generate chart for {symbol}: DataFrame is empty.")
            return ""

        plot_df = self._prepare_plot_df(df)
        filepath = self.storage.generate_filepath(symbol, time_interval, profile_data.get("timestamp"))
        
        # 1. Prepare Horizontal Levels (Volume Profile)
        poc = profile_data.get("poc", 0)
        vah = profile_data.get("vah", 0)
        val = profile_data.get("val", 0)
        
        hlines = dict(
            hlines=[poc, vah, val], 
            colors=[self.config.poc_color, self.config.va_color, self.config.va_color], 
            linestyle=['-', '--', '--'], 
            linewidths=[2.5, 1.5, 1.5]
        )

        try:
            logger.info(f"Rendering chart: {symbol} [{time_interval}] -> {filepath}")
            
            # 2. Main Plot (Candles + Volume)
            # returnfig=True creates a Matplotlib Figure that MUST be closed manually
            fig, axlist = mpf.plot(
                plot_df, 
                type='candle', 
                volume=True, 
                style=self._get_mpf_style(), 
                title=f"{symbol} - {time_interval} (Volume Profile AR)",
                hlines=hlines,
                savefig=dict(fname=filepath, dpi=self.config.dpi, bbox_inches='tight'),
                returnfig=True
            )
            
            try:
                main_ax = axlist[0]
                
                # 3. Overlay Volume Profile Histogram
                if "profile_data" in profile_data:
                    self._overlay_volume_profile(main_ax, plot_df, profile_data["profile_data"])
    
                # 4. Overlay Liquidation Zones
                if liquidations:
                    self._overlay_liquidations(main_ax, plot_df, liquidations)
    
                # 5. Overlay Trendlines
                trendlines = self.extractor.detect_trendlines(df) # Use original df with lowercase columns
                for line in trendlines:
                    main_ax.plot(line['x'], line['y'], color=line['color'], linestyle='--', linewidth=1.5, alpha=0.9)
    
                # Finalize and Save
                fig.savefig(filepath, dpi=self.config.dpi, bbox_inches='tight')
            finally:
                # CRITICAL: Always close the figure to prevent memory accumulation
                plt.close(fig)
                
            return filepath
        except Exception as e:
            logger.error(f"Chart generation failed for {symbol}: {e}")
            return ""

    def _overlay_volume_profile(self, ax: plt.Axes, df: pd.DataFrame, profile: List[Dict[str, Any]]):
        """Draws the Volume-at-Price histogram on the price axis."""
        min_p, max_p = df['Low'].min(), df['High'].max()
        p_vals = [p['price'] for p in profile if min_p <= p['price'] <= max_p]
        v_vals = [p['volume'] for p in profile if min_p <= p['price'] <= max_p]
        
        if v_vals:
            max_v = max(v_vals)
            norm_v = [(v / max_v) * (len(df) * self.config.volume_chart_scaling) for v in v_vals]
            bin_height = (max_p - min_p) / 50 * 0.8
            ax.barh(p_vals, norm_v, height=bin_height, color='#787b86', alpha=0.4, zorder=1)

    def _overlay_liquidations(self, ax: plt.Axes, df: pd.DataFrame, liquidations: List[Dict[str, Any]]):
        """Draws semi-transparent liquidation heat bands."""
        min_p, max_p = df['Low'].min(), df['High'].max()
        band_height = (max_p - min_p) * 0.015
        
        for liq in liquidations:
            try:
                # Handle both REST (price/side/qty) and WebSocket (p/S/q) keys
                price = float(liq.get('price') or liq.get('p', 0))
                if not (min_p <= price <= max_p):
                    continue
                    
                side = (liq.get('side') or liq.get('S', 'BUY')).upper()
                color = self.config.liq_buy_color if side == 'BUY' else self.config.liq_sell_color
                
                # Dynamic alpha based on quantity
                qty = float(liq.get('qty') or liq.get('origQty') or liq.get('q', 1))
                alpha = min(max(qty / 5.0, 0.10), 0.40)
                
                rect = patches.Rectangle(
                    (0, price - (band_height / 2)), 
                    len(df), 
                    band_height, 
                    color=color, 
                    alpha=alpha, 
                    zorder=0
                )
                ax.add_patch(rect)
            except (ValueError, TypeError):
                continue

# Alias for backward compatibility if needed, though agents should use the Facade.
ChartGenerator = ChartVisualRenderer
