import os
import pandas as pd
import numpy as np
from scipy.ndimage import gaussian_filter1d
import matplotlib
matplotlib.use('Agg')  # Non-interactive backend
import matplotlib.pyplot as plt
import matplotlib.patches as patches
import mplfinance as mpf
from dataclasses import dataclass
from typing import Dict, List, Any, Optional, Union
from src.utils.datetime_utils import format_timestamp_for_filename, get_current_utc_time

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
    value_area_color: str
    liq_long_color: str
    liq_short_color: str
    current_price_color: str
    volume_profile_width_ratio: float
    volume_profile_smoothing_sigma: float
    volume_profile_color: str
    volume_profile_alpha: float
    chart_main_panel_weight: int
    chart_volume_panel_weight: int
    render_dpi: int
    # v7.0 Synthetic Radar Aesthetics
    liq_band_height_ratio: float
    liq_max_alpha: float
    liq_min_alpha: float
    liq_legacy_alpha_factor: float
    liq_legacy_min_alpha: float
    liq_legacy_max_alpha: float


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
                        'type': 'resistance'
                    })
                
            if len(valley_indices) >= 3:
                for i in range(1, 3):
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
    def __init__(self, output_dir: str, up_color: str, down_color: str, bg_color: str, 
                 poc_color: str, value_area_color: str, 
                 liq_long_color: str, liq_short_color: str, current_price_color: str,
                 volume_profile_width_ratio: float,
                 render_dpi: int, volume_profile_smoothing_sigma: float, volume_profile_color: str,
                 volume_profile_alpha: float,
                 chart_main_panel_weight: int, chart_volume_panel_weight: int,
                 liq_band_height_ratio: float, liq_max_alpha: float, liq_min_alpha: float,
                 liq_legacy_alpha_factor: float, liq_legacy_min_alpha: float, liq_legacy_max_alpha: float):
        self.config = ChartConfig(
            up_color=up_color,
            down_color=down_color,
            bg_color=bg_color,
            poc_color=poc_color,
            value_area_color=value_area_color,
            liq_long_color=liq_long_color,
            liq_short_color=liq_short_color,
            current_price_color=current_price_color,
            volume_profile_width_ratio=volume_profile_width_ratio, 
            volume_profile_smoothing_sigma=volume_profile_smoothing_sigma,
            volume_profile_color=volume_profile_color,
            volume_profile_alpha=volume_profile_alpha,
            chart_main_panel_weight=chart_main_panel_weight,
            chart_volume_panel_weight=chart_volume_panel_weight,
            render_dpi=render_dpi,
            liq_band_height_ratio=liq_band_height_ratio,
            liq_max_alpha=liq_max_alpha,
            liq_min_alpha=liq_min_alpha,
            liq_legacy_alpha_factor=liq_legacy_alpha_factor,
            liq_legacy_min_alpha=liq_legacy_min_alpha,
            liq_legacy_max_alpha=liq_legacy_max_alpha
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
                       liquidations: Union[List, Dict], time_interval: str) -> str:
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
            
            # 1. Prepare Horizontal Levels (v6.67: Reverted to native hlines API)
            poc = profile_data.get("poc", 0)
            vah = profile_data.get("vah", 0)
            val = profile_data.get("val", 0)
            
            hlines = dict(
                hlines=[poc, vah, val], 
                colors=[self.config.poc_color, self.config.value_area_color, self.config.value_area_color], 
                linestyle=['-', '--', '--'], 
                linewidths=[1.0, 1.0, 1.0] # POC (1.5), VAH/VAL (1.0)
            )

            # 2. Main Plot (Candles + Volume)
            fig, axlist = mpf.plot(
                plot_df, 
                type='candle', 
                volume=True, 
                panel_ratios=(self.config.chart_main_panel_weight, self.config.chart_volume_panel_weight),
                style=self._get_mpf_style(), 
                title=f"{symbol} - {time_interval} ({plot_df.index[0].strftime('%Y-%m-%d %H:%M')} -> {plot_df.index[-1].strftime('%Y-%m-%d %H:%M')})",
                hlines=hlines,
                savefig=dict(fname=filepath, dpi=self.config.render_dpi, bbox_inches='tight'),
                returnfig=True,
                show_nontrading=False          # Focus strictly on market periods
            )
            
            try:
                # 3. Axis Cleanup (Hide left/top spines for modern TradingView feel)
                # axlist[0] = Price Panel, axlist[2] = Volume Panel (standard mpf stacking)
                for i, ax in enumerate(axlist):
                    # v6.50 Hardening: Completely hide X-axis for zero-clutter focus
                    ax.xaxis.set_visible(False)
                    
                    # Hide left/top spines
                    ax.spines['left'].set_visible(False)
                    ax.spines['top'].set_visible(False)
                    ax.spines['right'].set_color(self.config.value_area_color)
                    ax.spines['bottom'].set_color(self.config.value_area_color)
                    
                    # Force price ticks to right only
                    ax.yaxis.set_ticks_position('right')

                    # v6.51 Hardening: Distinguish Price from Volume to prevent scale confusion
                    if i == 0:
                        ax.set_ylabel('Price', color=self.config.value_area_color, fontsize=9, fontweight='bold')
                        ax.yaxis.set_label_position('right')
                    elif i == 2: # Volume panel usually at index 2
                        ax.set_ylabel('Vol', color=self.config.value_area_color, fontsize=9, fontweight='bold')
                        ax.yaxis.set_label_position('right')

                main_ax = axlist[0]
                
                # 3. Current Price Tracker (v6.75: Thin dashed line for immediate context)
                current_price = plot_df['Close'].iloc[-1]
                main_ax.axhline(
                    y=current_price, 
                    color=self.config.current_price_color,      # Configurable via global_config.yaml
                    linestyle='--',                             # Hardcoded v6.81
                    linewidth=0.5,                              # Hardcoded v6.81
                    alpha=0.8,                                  # Hardcoded v6.81
                    zorder=11                                   # Above everything
                )

                # 4. Overlay Volume Profile Histogram
                if "profile_data" in profile_data:
                    self._overlay_volume_profile(main_ax, plot_df, profile_data["profile_data"])
    
                # 4. Overlay Liquidation Zones
                if liquidations:
                    self._overlay_liquidations(main_ax, plot_df, liquidations)
    
                # 5. Overlay Trendlines
                trendlines = self.extractor.detect_trendlines(df)
                for line in trendlines:
                    color = self.config.down_color if line['type'] == 'resistance' else self.config.up_color
                    main_ax.plot(line['x'], line['y'], color=color, linestyle='--', linewidth=1.0, alpha=0.8)
    
                # 6. OCR Text Hard Injection (Minimalist Right-Side Identifier)
                # v6.65: Labels are right-aligned to the last candle, but price numbers 
                # are removed to keep the footprint extremely small and non-obstructive.
                x_pos = len(plot_df) + 1  # Standard shift to the right of the price action
                
                
                label_style = dict(
                    fontsize=8, 
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
                        color=self.config.value_area_color,
                        **label_style
                    )
                    
                # Value Area Low (VAL)
                if val > 0:
                    main_ax.text(
                        x_pos, val, "VAL", 
                        color=self.config.value_area_color,
                        **label_style
                    )

                # Finalize and Save
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
        # v6.71 Experiment: Pure Unfiltered Profile
        # User requested to see the effect of no clipping at all. 
        # Note: This will cause auto-scaling of the Y-axis to the full profile range.
        visible_profile = profile
        
        if not visible_profile:
            return

        # 转换为 numpy 数组以支持高效的向量化计算和滤波
        p_vals = np.array([p['price'] for p in visible_profile])
        v_vals = np.array([p['volume'] for p in visible_profile])
        
        max_v = max(v_vals) if len(v_vals) > 0 else 1

        # Normalize width relative to total candle count
        norm_v = (v_vals / max_v) * (len(df) * self.config.volume_profile_width_ratio)
        
        # --- 高斯平滑视觉层 (Gaussian Smoothing Visual Layer) ---
        # sigma 控制平滑度。数值越大越平滑（抹平细节），数值越小越保留原始锯齿。
        # 对于 300 桶的分辨率，sigma 设为 2.0 到 3.0 是视觉呈现的黄金甜点。
        smoothed_v = gaussian_filter1d(norm_v, sigma=self.config.volume_profile_smoothing_sigma)
        
        # 使用 fill_betweenx 画出一个完美的、毫无缝隙的平滑几何多边形
        ax.fill_betweenx(
            y=p_vals, 
            x1=0,                  # 多边形的左边界（贴紧 Y 轴）
            x2=smoothed_v,         # 多边形的右边界（经过高斯平滑的轮廓）
            color=self.config.volume_profile_color, 
            alpha=self.config.volume_profile_alpha, 
            zorder=3,              # Middle layer: Above Liquidations, below Candles
            linewidth=0,           # 绝对禁止外边框，防止抗锯齿干扰
            edgecolor='none'       # 彻底关闭边缘颜色
        )

    def _overlay_liquidations(self, ax: plt.Axes, df: pd.DataFrame, liquidations: Union[List, Dict]):
        """Draws semi-transparent liquidation heat bands (Supports both raw lists and synthetic dicts)."""
        min_p, max_p = df['Low'].min(), df['High'].max()
        # v7.0 Visual Hardening: Parametric band height
        band_height = (max_p - min_p) * self.config.liq_band_height_ratio
        
        # Determine format
        if isinstance(liquidations, dict):
            # v7.0: Synthetic Bifurcated Format (Radar Output)
            long_targets = liquidations.get('long_liquidation', [])
            short_targets = liquidations.get('short_liquidation', [])
            
            # Draw Longs (Traps)
            for liq in long_targets:
                p = liq['price']
                if min_p <= p <= max_p:
                    # v7.0 Parametric Alpha Scaling
                    alpha = min(max(liq['intensity'] * self.config.liq_max_alpha, self.config.liq_min_alpha), self.config.liq_max_alpha)
                    ax.add_patch(patches.Rectangle(
                        (0, p - (band_height / 2)), len(df), band_height, 
                        color=self.config.liq_long_color, alpha=alpha, zorder=0
                    ))
            
            # Draw Shorts (Squeezes)
            for liq in short_targets:
                p = liq['price']
                if min_p <= p <= max_p:
                    # v7.0 Parametric Alpha Scaling
                    alpha = min(max(liq['intensity'] * self.config.liq_max_alpha, self.config.liq_min_alpha), self.config.liq_max_alpha)
                    ax.add_patch(patches.Rectangle(
                        (0, p - (band_height / 2)), len(df), band_height, 
                        color=self.config.liq_short_color, alpha=alpha, zorder=0
                    ))

# Alias for backward compatibility if needed, though agents should use the Facade.
ChartGenerator = ChartVisualRenderer
