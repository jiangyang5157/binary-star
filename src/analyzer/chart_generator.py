import os
import pandas as pd
import numpy as np
from scipy.ndimage import gaussian_filter1d
import matplotlib
matplotlib.use('Agg')  # Non-interactive backend
import matplotlib.pyplot as plt
import matplotlib.patches as patches
import mplfinance as mpf
import matplotlib.collections as mcoll
from matplotlib.ticker import MaxNLocator
from dataclasses import dataclass
from typing import Dict, List, Any, Optional, Union
from src.utils.datetime_utils import format_timestamp_for_filename

# Initialize project-standard logger
from src.utils.logger_utils import setup_logger
logger = setup_logger(__name__)

@dataclass(frozen=True)
class ChartConfig:
    """
    Configuration and styling tokens for chart generation.
    """
    up_color: str
    down_color: str
    bg_color: str
    poc_color: str
    vah_val_color: str
    current_price_color: str
    volume_profile_width_ratio: float
    volume_profile_smoothing_sigma: float
    volume_profile_color: str
    volume_profile_alpha: float
    chart_main_panel_weight: int
    chart_volume_panel_weight: int
    render_dpi: int
    # Synthetic Radar Aesthetics
    liquidation_cluster_atr_multiplier: float
    liq_max_alpha: float
    liq_min_alpha: float
    liq_legacy_alpha_factor: float
    liq_legacy_min_alpha: float
    liq_legacy_max_alpha: float
    chart_trendline_peak_count: int # Structural Persistence
    chart_trendline_window: int     # Fractal Sensitivity


class TechnicalFeatureExtractor:
    """
    Handles detection of visual technical structures (e.g., Trendlines).
    """
    @staticmethod
    def detect_trendlines(df: pd.DataFrame, peak_count: int, window: int) -> List[Dict[str, Any]]:
        """
        Detects fractal highs and lows to generate trendline segments.
        peak_count is now configurable from global_config.
        """
        try:
            # Detect local peaks (highs) and valleys (lows)
            highs = df['high'].rolling(window=window, center=True).max() == df['high']
            lows = df['low'].rolling(window=window, center=True).min() == df['low']
            
            peak_indices = np.where(highs)[0]
            valley_indices = np.where(lows)[0]
            
            trendlines = []
            # Use last peak_count peaks/valleys to draw historical structure
            if len(peak_indices) >= peak_count:
                for i in range(1, peak_count):
                    p1, p2 = peak_indices[-(i+1)], peak_indices[-i]
                    trendlines.append({
                        'x': [p1, p2], 
                        'y': [df['high'].iloc[p1], df['high'].iloc[p2]], 
                        'type': 'resistance'
                    })
                
            if len(valley_indices) >= peak_count:
                for i in range(1, peak_count):
                    v1, v2 = valley_indices[-(i+1)], valley_indices[-i]
                    trendlines.append({
                        'x': [v1, v2], 
                        'y': [df['low'].iloc[v1], df['low'].iloc[v2]], 
                        'type': 'support'
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
        if not timestamp:
            raise ValueError("ChartStorage: Timestamp is mandatory for deterministic filename generation.")
        
        ts_readable = format_timestamp_for_filename(timestamp)
            
        filename = f"{symbol}_klines_{time_interval}_{ts_readable}.png"
        return os.path.join(self.output_dir, filename)

class ChartVisualRenderer:
    """
    Core engine for rendering candlestick charts with logical overlays.
    """
    def __init__(self, output_dir: str, up_color: str, down_color: str, bg_color: str, 
                 poc_color: str, vah_val_color: str, 
                 current_price_color: str,
                 volume_profile_width_ratio: float,
                 render_dpi: int, volume_profile_smoothing_sigma: float, volume_profile_color: str,
                 volume_profile_alpha: float,
                 chart_main_panel_weight: int, chart_volume_panel_weight: int,
                 liquidation_cluster_atr_multiplier: float, liq_max_alpha: float, liq_min_alpha: float,
                 liq_legacy_alpha_factor: float, liq_legacy_min_alpha: float, liq_legacy_max_alpha: float,
                 chart_trendline_peak_count: int,
                 chart_trendline_window: int):
        self.config = ChartConfig(
            up_color=up_color,
            down_color=down_color,
            bg_color=bg_color,
            poc_color=poc_color,
            vah_val_color=vah_val_color,
            current_price_color=current_price_color,
            volume_profile_width_ratio=volume_profile_width_ratio, 
            volume_profile_smoothing_sigma=volume_profile_smoothing_sigma,
            volume_profile_color=volume_profile_color,
            volume_profile_alpha=volume_profile_alpha,
            chart_main_panel_weight=chart_main_panel_weight,
            chart_volume_panel_weight=chart_volume_panel_weight,
            render_dpi=render_dpi,
            liquidation_cluster_atr_multiplier=liquidation_cluster_atr_multiplier,
            liq_max_alpha=liq_max_alpha,
            liq_min_alpha=liq_min_alpha,
            liq_legacy_alpha_factor=liq_legacy_alpha_factor,
            liq_legacy_min_alpha=liq_legacy_min_alpha,
            liq_legacy_max_alpha=liq_legacy_max_alpha,
            chart_trendline_peak_count=chart_trendline_peak_count,
            chart_trendline_window=chart_trendline_window
        )
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
            ohlc = 'inherit', 
            volume='inherit'
        )
        return mpf.make_mpf_style(
            marketcolors=mc, 
            gridstyle='none', 
            y_on_right=True, 
            facecolor=self.config.bg_color
        )

    def generate_chart(self, symbol: str, df: pd.DataFrame, profile_data: Dict[str, Any], 
                       liquidations: Union[List, Dict], time_interval: str, atr: Optional[float] = None) -> str:
        """
        Orchestrates the generation of an enhanced candlestick chart.
        """
        if df.empty:
            logger.error(f"Cannot generate chart for {symbol}: DataFrame is empty.")
            return ""

        plot_df = self._prepare_plot_df(df)
        filepath = self.storage.generate_filepath(symbol, time_interval, profile_data.get("timestamp"))
        
        try:
            logger.info(f"Rendering chart: {symbol} [{time_interval}] -> {filepath}")
            
            # 1. Prepare Horizontal Levels
            poc = profile_data.get("poc", 0)
            vah = profile_data.get("vah", 0)
            val = profile_data.get("val", 0)
            
            hlines = dict(
                hlines=[poc, vah, val], 
                colors=[self.config.poc_color, self.config.vah_val_color, self.config.vah_val_color], 
                linestyle=['-', '--', '--'], 
                linewidths=[1.0, 1.0, 1.0] # POC (1.5), VAH/VAL (1.0)
            )

            # 2. Calculate Adaptive Y-Limits
            candle_min = plot_df['Low'].min()
            candle_max = plot_df['High'].max()
            y_min, y_max = candle_min, candle_max
            
            # Collect ALL structural targets that MUST be visible (Topography + Liquidations)
            targets = [poc, vah, val]
            if isinstance(liquidations, dict):
                for side in ['long_liquidation', 'short_liquidation']:
                    targets.extend([l['price'] for l in liquidations.get(side, [])])
            
            # Sanity Guard & Scale Expansion
            curr_p = plot_df['Close'].iloc[-1]
            # Filter for valid, non-zero prices and within 20% relative distance to prevent warping
            valid_targets = [p for p in targets if p > 0 and abs(p - curr_p) / curr_p < 0.2]
            
            if valid_targets:
                y_min = min(y_min, min(valid_targets))
                y_max = max(y_max, max(valid_targets))
            
            # Apply Structural Padding (5% buffer) so bands don't touch the chart border
            y_range = y_max - y_min
            if y_range > 0:
                y_min -= y_range * 0.05
                y_max += y_range * 0.05

            # 3. Main Plot (Candles + Volume + Dynamic Scaling)
            fig, axlist = mpf.plot(
                plot_df, 
                type='candle', 
                volume=True, 
                panel_ratios=(self.config.chart_main_panel_weight, self.config.chart_volume_panel_weight),
                style=self._get_mpf_style(), 
                title=f"{symbol} | {time_interval}",
                hlines=hlines,
                ylim=(y_min, y_max),           # Enforce the adaptive topographical range
                returnfig=True,
                show_nontrading=False,          # Focus strictly on market periods
                scale_width_adjustment=dict(volume=0.7) # Thinner pillars for better separation
            )
            
            try:
                # 3. Axis Cleanup (Hide left/top spines for modern TradingView feel)
                # axlist[0] = Price Panel, axlist[2] = Volume Panel (standard mpf stacking)
                for i, ax in enumerate(axlist):
                    # Hardening: Completely hide X-axis for zero-clutter focus
                    ax.xaxis.set_visible(False)
                    
                    # Hide left/top spines
                    ax.spines['left'].set_visible(False)
                    ax.spines['top'].set_visible(False)
                    ax.spines['right'].set_color(self.config.vah_val_color)
                    ax.spines['bottom'].set_color(self.config.vah_val_color)
                    
                    # Force price ticks to right only
                    ax.yaxis.set_ticks_position('right')

                    # Hardening: Distinguish Price from Volume to prevent scale confusion
                    # Aesthetic: Inherit tick color for panel labels to maintain structural consistency
                    tick_label_color = ax.yaxis.get_ticklabels()[0].get_color() if ax.yaxis.get_ticklabels() else self.config.vah_val_color
                    
                    if i == 0:
                        ax.set_ylabel('')
                        ax.yaxis.set_label_position('right')
                        # Aesthetic: Remove the horizontal separator line for modern look
                        ax.spines['bottom'].set_visible(False)
                        # Hardening: Lock price tick density to 6 for consistent scale feel
                        ax.yaxis.set_major_locator(MaxNLocator(nbins=6, integer=False))
                    elif i == 2: # Volume panel usually at index 2
                        ax.set_ylabel('')
                        ax.yaxis.set_label_position('right')
                        
                        # Anti-Overlap: Lock density to 3 bins
                        ax.yaxis.set_major_locator(MaxNLocator(nbins=3, prune='upper', integer=True))
                        
                        # Logic: Surgical targeting to only affect data bars...
                        for child in ax.get_children():
                            # Skip the axis background patch itself
                            if child is ax.patch:
                                continue
                                
                            # target only Rectangles (standard bars) or Collections (dense clusters)
                            if isinstance(child, (patches.Rectangle, mcoll.PolyCollection, mcoll.LineCollection)):
                                if hasattr(child, 'set_linewidth'):
                                    child.set_linewidth(0)
                                if hasattr(child, 'set_edgecolor'):
                                    child.set_edgecolor('none')
                                if hasattr(child, 'set_alpha'):
                                    child.set_alpha(0.8) # Mute pillar brightness only
                                if hasattr(child, 'set_antialiased'):
                                    child.set_antialiased(False)

                main_ax = axlist[0]
                
                # 4. Current Price Tracker
                current_price = plot_df['Close'].iloc[-1]
                main_ax.axhline(
                    y=current_price, 
                    color=self.config.current_price_color,      # Configurable via global_config.yaml
                    linestyle='--',                             # Hardcoded
                    linewidth=0.5,                              # Increased for visibility
                    alpha=0.8,                                  # Increased
                    zorder=11                                   # Above everything
                )

                # 4. Overlay Volume Profile Histogram
                if "profile_data" in profile_data:
                    self._overlay_volume_profile(main_ax, plot_df, profile_data["profile_data"])
    
                # 4. Overlay Liquidation Zones
                if liquidations:
                    self._overlay_liquidations(main_ax, plot_df, liquidations, atr=atr)
    
                # 5. Overlay Trendlines
                trendlines = self.extractor.detect_trendlines(
                    df, 
                    peak_count=self.config.chart_trendline_peak_count,
                    window=self.config.chart_trendline_window
                )
                for line in trendlines:
                    color = self.config.down_color if line['type'] == 'resistance' else self.config.up_color
                    main_ax.plot(line['x'], line['y'], color=color, linestyle='--', linewidth=1.0, alpha=0.8, zorder=4)
    
                # 6. OCR Text Hard Injection (Minimalist Right-Side Identifier)
                # Labels are right-aligned to the last candle, but price numbers 
                # are removed to keep the footprint extremely small and non-obstructive.
                x_pos = len(plot_df) + 1  # Standard shift to the right of the price action
                
                
                label_style = dict(
                    fontsize=7, 
                    fontweight='bold', 
                    ha='left',      # Move to the right margin (outside candles)
                    va='center',
                    zorder=12        # Top layer for readability
                )
                
                # Point of Control (POC)
                if poc > 0:
                    main_ax.text(
                        x_pos, poc, "POC", 
                        color=self.config.poc_color,
                        **label_style
                    )
                
                # Value Area High (VAH)
                if vah > 0:
                    main_ax.text(
                        x_pos, vah, "VAH", 
                        color=self.config.vah_val_color,
                        **label_style
                    )
                    
                # Value Area Low (VAL)
                if val > 0:
                    main_ax.text(
                        x_pos, val, "VAL", 
                        color=self.config.vah_val_color,
                        **label_style
                    )

                # Finalize and Save
                fig.subplots_adjust(hspace=0.03)  # Add subtle vertical padding between panels
                fig.savefig(filepath, dpi=self.config.render_dpi, bbox_inches='tight')
            finally:
                # CRITICAL: Always close the figure to prevent memory accumulation
                plt.close(fig)
                
            return filepath
        except Exception as e:
            logger.error(f"Chart generation failed for {symbol}: {e}")
            return ""

    def _overlay_volume_profile(self, ax: plt.Axes, df: pd.DataFrame, profile: List[Dict[str, Any]]):
        """Draws the Volume-at-Price histogram as a smooth Gaussian area on the price axis."""
        # Experiment: Pure Unfiltered Profile
        # User requested to see the effect of no clipping at all. 
        # Note: This will cause auto-scaling of the Y-axis to the full profile range.
        visible_profile = profile
        
        if not visible_profile:
            return

        # 转换为 numpy 数组以支持高效的向量化计算和滤波
        p_vals = np.array([p['price'] for p in visible_profile])
        v_vals = np.array([p['volume'] for p in visible_profile])
        
        # Hardening: Prevent division by zero if all visible volumes are zero
        max_v = max(v_vals) if len(v_vals) > 0 and max(v_vals) > 0 else 1

        # Normalize width relative to total candle count
        norm_v = (v_vals / max_v) * (len(df) * self.config.volume_profile_width_ratio)
        
        # --- Gaussian Smoothing Visual Layer ---
        # Conditionally apply smoothing. Setting sigma=0 now bypasses the filter to show 'Raw Profile'.
        if self.config.volume_profile_smoothing_sigma > 0:
            smoothed_v = gaussian_filter1d(norm_v, sigma=self.config.volume_profile_smoothing_sigma)
        else:
            smoothed_v = norm_v
        
        # 使用 fill_betweenx 画出一个完美的、毫无缝隙的平滑几何多边形
        ax.fill_betweenx(
            y=p_vals, 
            x1=0,                  # 多边形的左边界（贴紧 Y 轴）
            x2=smoothed_v,         # 多边形的右边界（经过高斯平滑的轮廓）
            color=self.config.volume_profile_color, 
            alpha=self.config.volume_profile_alpha, 
            zorder=1,              # Bottom layer: Just above Liquidations (z=0)
            linewidth=0,           # 绝对禁止外边框，防止抗锯齿干扰
            edgecolor='none'       # 彻底关闭边缘颜色
        )

    def _overlay_liquidations(self, ax: plt.Axes, df: pd.DataFrame, liquidations: Union[List, Dict], atr: Optional[float] = None):
        """Draws semi-transparent liquidation heat bands based on ATR physics."""
        # Visual Hardening: Strict ATR-only logic (Zero-Default Fallback)
        band_height = atr * self.config.liquidation_cluster_atr_multiplier
        
        # Determine format
        if isinstance(liquidations, dict):
            # Synthetic Bifurcated Format (Radar Output)
            long_targets = liquidations.get('long_liquidation', [])
            short_targets = liquidations.get('short_liquidation', [])
            
            # Draw Longs (Traps)
            for liq in long_targets:
                p = liq['price']
                # Reusing up_color for Long Traps (Support)
                alpha = min(max(liq['intensity'] * self.config.liq_max_alpha, self.config.liq_min_alpha), self.config.liq_max_alpha)
                ax.add_patch(patches.Rectangle(
                    (0, p - (band_height / 2)), len(df), band_height, 
                    facecolor=self.config.up_color, alpha=alpha, zorder=0,
                    linewidth=0, edgecolor='none'
                ))
            
            # Draw Shorts (Squeezes)
            for liq in short_targets:
                p = liq['price']
                # Reusing down_color for Short Squeezes (Resistance)
                alpha = min(max(liq['intensity'] * self.config.liq_max_alpha, self.config.liq_min_alpha), self.config.liq_max_alpha)
                ax.add_patch(patches.Rectangle(
                    (0, p - (band_height / 2)), len(df), band_height, 
                    facecolor=self.config.down_color, alpha=alpha, zorder=0,
                    linewidth=0, edgecolor='none'
                ))

# Alias for backward compatibility if needed, though agents should use the Facade.
ChartGenerator = ChartVisualRenderer
