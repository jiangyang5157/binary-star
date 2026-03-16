import os
import pandas as pd
import mplfinance as mpf
import matplotlib.pyplot as plt
import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)

class ChartGenerator:
    """
    Generates Candlestick charts with Volume Profile overlays using mplfinance.
    These charts are saved as images to be fed directly into Gemini Multimodal AI.
    """
    def __init__(self, output_dir: str = "data/images"):
        self.output_dir = output_dir
        os.makedirs(self.output_dir, exist_ok=True)

    def generate_chart(self, symbol: str, df: pd.DataFrame, profile_data: Dict[str, Any], filename_suffix: str = "4h") -> str:
        """
        Plots the OHLCV chart and draws horizontal lines for POC, VAH, and VAL.
        Saves the resulting PNG to the output directory.
        """
        # mplfinance requires column names to be strictly Open, High, Low, Close, Volume
        plot_df = df.rename(columns={
            "open": "Open",
            "high": "High",
            "low": "Low",
            "close": "Close",
            "volume": "Volume"
        })
        
        # We need to drop NA and ensure the index is DateTimeIndex (handled in VolumeProfileAnalyzer)
        
        # Extract Profile stats
        poc = profile_data.get("poc", 0)
        vah = profile_data.get("vah", 0)
        val = profile_data.get("val", 0)

        # Style the chart: Dark theme is often better for AI contrast and looks cooler!
        mc = mpf.make_marketcolors(up='g', down='r', edge='inherit', wick='inherit', volume='in')
        s  = mpf.make_mpf_style(marketcolors=mc, gridstyle=':', y_on_right=True)

        # Draw horizontal lines for Volume Profile
        # Colors: POC = Red (important), VAH/VAL = Blue/Cyan
        hlines = dict(
            hlines=[poc, vah, val], 
            colors=['#ff0000', 'y', 'y'], # POC is red, VAH/VAL are now yellow
            linestyle=['-', '-', '-'],    # All lines are now solid
            linewidths=[2, 1.5, 1.5]
        )

        filepath = os.path.join(self.output_dir, f"{symbol}_{filename_suffix}_chart.png")

        try:
            logger.info(f"Generating chart for {symbol} to {filepath}")
            # mpf.plot is a powerful wrapper for matplotlib.
            # It handles the OHLC candlesticks and the volume bars automatically.
            mpf.plot(
                plot_df, 
                type='candle', 
                volume=True, 
                style=s, 
                title=f"{symbol} - {filename_suffix} (POC: {poc:.2f})",
                hlines=hlines, # Overlaying our Volume Profile levels (POC, VAH, VAL)
                savefig=dict(fname=filepath, dpi=150, bbox_inches='tight'),
                warn_too_much_data=1000
            )
            return filepath
        except Exception as e:
            logger.error(f"Failed to generate chart for {symbol}: {e}")
            return ""
