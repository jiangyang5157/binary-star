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
            if len(peak_indices) >= 3:
                # Plot last 2 segments (3 peaks)
                for i in range(1, 3):
                    p1, p2 = peak_indices[-(i+1)], peak_indices[-i]
                    trendlines.append({'x': [p1, p2], 'y': [df['High'].iloc[p1], df['High'].iloc[p2]], 'color': '#ff3366'})
                
            if len(valley_indices) >= 3:
                # Plot last 2 segments (3 valleys)
                for i in range(1, 3):
                    v1, v2 = valley_indices[-(i+1)], valley_indices[-i]
                    trendlines.append({'x': [v1, v2], 'y': [df['Low'].iloc[v1], df['Low'].iloc[v2]], 'color': '#00ff88'})
            
            return trendlines
        except Exception as e:
            logger.warning(f"Failed to detect trendlines: {e}")
            return []

    def generate_chart(self, symbol: str, df: pd.DataFrame, profile_data: Dict[str, Any], 
                       liquidations: Optional[List[Dict[str, Any]]] = None, filename_suffix: str = "") -> str:
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

        # 1. Professional & High-Contrast Colors (AI Optimized)
        # Up: Teal (#26a69a), Down: Coral (#ef5350) - Distinct for computer vision.
        mc = mpf.make_marketcolors(up='#26a69a', down='#ef5350', edge='inherit', wick='inherit', volume='in')
        s  = mpf.make_mpf_style(marketcolors=mc, gridstyle='--', gridcolor='#333333', y_on_right=True, facecolor='#131722') # Dark Theme

        # 2. Key Levels (POC, VAH, VAL)
        # POC is Bright Orange for peak visibility; VAH/VAL are Gold.
        hlines = dict(
            hlines=[poc, vah, val], 
            colors=['#ff9800', '#fbc02d', '#fbc02d'], 
            linestyle=['-', '--', '--'], 
            linewidths=[2.5, 1.5, 1.5]
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
                savefig=dict(fname=filepath, dpi=180, bbox_inches='tight'), # Higher DPI for AI
                warn_too_much_data=1000,
                returnfig=True
            )
            
            try:
                ax = axlist[0] # Main Candle Axis
                vol_ax = axlist[2] # Volume Axis
                
                # ... [Rest of the plotting logic remains same but inside try]
                # 3. Plot Volume Profile (VAP) Histogram on the left side
                if "profile_data" in profile_data:
                    profile = profile_data["profile_data"]
                    min_p, max_p = plot_df['Low'].min(), plot_df['High'].max()
                    
                    p_vals = [p['price'] for p in profile if min_p <= p['price'] <= max_p]
                    v_vals = [p['volume'] for p in profile if min_p <= p['price'] <= max_p]
                    
                    if v_vals:
                        max_v = max(v_vals)
                        norm_v = [(v / max_v) * (len(plot_df) * 0.18) for v in v_vals]
                        bin_height = (max_p - min_p) / 50 * 0.8
                        ax.barh(p_vals, norm_v, height=bin_height, color='#787b86', alpha=0.5, zorder=1, align='center')

                # 4. Plot Liquidation Zones
                if liquidations:
                    min_p, max_p = plot_df['Low'].min(), plot_df['High'].max()
                    price_range = max_p - min_p
                    band_height = price_range * 0.015
                    
                    for liq in liquidations:
                        try:
                            price = float(liq.get('p', 0))
                            side = liq.get('S', 'BUY') 
                            if min_p <= price <= max_p:
                                color = '#00ff88' if side == 'BUY' else '#ff3366' 
                                q = float(liq.get('q', 1))
                                calculated_alpha = min(max(q / 5, 0.12), 0.45)
                                rect = patches.Rectangle((0, price - (band_height / 2)), len(plot_df), band_height, color=color, alpha=calculated_alpha, zorder=0)
                                ax.add_patch(rect)
                        except: continue

                # 5. Plot detected Trendlines
                lines = self._get_trendlines(plot_df)
                for line in lines:
                    ax.plot(line['x'], line['y'], color='#2a9d8f', linestyle='--', linewidth=1.5, alpha=0.9)

                # Re-save the modified figure
                fig.savefig(filepath, dpi=180, bbox_inches='tight')
            finally:
                plt.close(fig)
            
            return filepath
        except Exception as e:
            logger.error(f"Failed to generate enhanced chart for {symbol}: {e}")
            return ""
