import os
import pandas as pd
import mplfinance as mpf
import matplotlib.pyplot as plt
import matplotlib.patches as patches
import numpy as np
import logging
from typing import Dict, List, Any, Optional

logger = logging.getLogger(__name__)

class ChartGenerator:
    """
    Generates Candlestick charts with Visual AR (Augmented Reality) enhancements:
    - Volume Profile (POC, VAH, VAL)
    - Liquidation Zones (Heatmap bands)
    - Trendlines (Automated structure detection)
    """
    def __init__(self, output_dir: str = "data/images"):
        self.output_dir = output_dir
        os.makedirs(self.output_dir, exist_ok=True)

    def _get_trendlines(self, df: pd.DataFrame, window: int = 5) -> List[Dict[str, Any]]:
        """
        Detects fractal highs and lows to generate trendlines.
        """
        try:
            # Find local peaks/valleys
            highs = df['High'].rolling(window=window, center=True).max() == df['High']
            lows = df['Low'].rolling(window=window, center=True).min() == df['Low']
            
            peak_indices = np.where(highs)[0]
            valley_indices = np.where(lows)[0]
            
            trendlines = []
            if len(peak_indices) >= 2:
                # Last two peaks
                p1, p2 = peak_indices[-2], peak_indices[-1]
                trendlines.append({'x': [p1, p2], 'y': [df['High'].iloc[p1], df['High'].iloc[p2]], 'color': 'red'})
                
            if len(valley_indices) >= 2:
                # Last two valleys
                v1, v2 = valley_indices[-2], valley_indices[-1]
                trendlines.append({'x': [v1, v2], 'y': [df['Low'].iloc[v1], df['Low'].iloc[v2]], 'color': 'green'})
            
            return trendlines
        except Exception as e:
            logger.warning(f"Failed to detect trendlines: {e}")
            return []

    def generate_chart(self, symbol: str, df: pd.DataFrame, profile_data: Dict[str, Any], 
                       liquidations: List[Dict[str, Any]] = None, filename_suffix: str = "4h") -> str:
        """
        Plots the OHLCV chart with POC levels, Liquidation Zones, and Trendlines.
        """
        plot_df = df.rename(columns={
            "open": "Open",
            "high": "High",
            "low": "Low",
            "close": "Close",
            "volume": "Volume"
        })
        
        poc = profile_data.get("poc", 0)
        vah = profile_data.get("vah", 0)
        val = profile_data.get("val", 0)

        mc = mpf.make_marketcolors(up='g', down='r', edge='inherit', wick='inherit', volume='in')
        s  = mpf.make_mpf_style(marketcolors=mc, gridstyle=':', y_on_right=True)

        hlines = dict(
            hlines=[poc, vah, val], 
            colors=['#ff0000', '#DAA520', '#DAA520'], 
            linestyle=['-', '-', '-'], 
            linewidths=[2, 1.5, 1.5]
        )

        if "timestamp" in profile_data:
            ts_readable = profile_data["timestamp"].replace(":", "").replace("-", "").replace("T", "_").split(".")[0]
            filename = f"{symbol}_{filename_suffix}_{ts_readable}_chart.png"
        else:
            filename = f"{symbol}_{filename_suffix}_chart.png"
            
        filepath = os.path.join(self.output_dir, filename)

        try:
            logger.info(f"Generating Enhanced Visual AR chart for {symbol} to {filepath}")
            
            # Use returnfig=True to get the figure and axes for manual overlays
            fig, axlist = mpf.plot(
                plot_df, 
                type='candle', 
                volume=True, 
                style=s, 
                title=f"{symbol} - {filename_suffix} (POC: {poc:.2f})",
                hlines=hlines,
                savefig=dict(fname=filepath, dpi=150, bbox_inches='tight'),
                warn_too_much_data=1000,
                returnfig=True
            )
            
            # The main OHLC ax is usually axlist[0]
            ax = axlist[0]
            
            # 1. Plot Liquidation Zones as translucent bands
            if liquidations:
                # Filter liquidations within price range of the chart
                min_p, max_p = plot_df['Low'].min(), plot_df['High'].max()
                price_range = max_p - min_p
                # Band thickness is 1% of total chart range for visibility
                band_height = price_range * 0.015
                
                for liq in liquidations:
                    try:
                        price = float(liq.get('p', 0))
                        # BUY means a short was liquidated (Support effect), SELL means a long was liquidated (Resistance effect)
                        side = liq.get('S', 'BUY') 
                        
                        if min_p <= price <= max_p:
                            color = '#00ff00' if side == 'BUY' else '#ff0000' # Bright Green/Red
                            # Alpha varies between 0.05 and 0.3 based on quantity
                            q = float(liq.get('q', 1))
                            calculated_alpha = min(max(q / 5, 0.08), 0.3)
                            
                            rect = patches.Rectangle(
                                (0, price - (band_height / 2)), 
                                len(plot_df), 
                                band_height, 
                                color=color, 
                                alpha=calculated_alpha, 
                                zorder=0
                            )
                            ax.add_patch(rect)
                    except: continue

            # 2. Plot detected Trendlines
            lines = self._get_trendlines(plot_df)
            for line in lines:
                ax.plot(line['x'], line['y'], color=line['color'], linestyle='--', linewidth=1.5, alpha=0.7)

            # Re-save the modified figure
            fig.savefig(filepath, dpi=150, bbox_inches='tight')
            plt.close(fig) # Prevent memory leaks
            
            return filepath
        except Exception as e:
            logger.error(f"Failed to generate enhanced chart for {symbol}: {e}")
            return ""
