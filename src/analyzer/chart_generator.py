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
from typing import Dict, List, Any, Optional
from src.utils.datetime_utils import format_timestamp_for_filename, get_current_utc_time
from src.utils.market_utils import parse_liquidation_data

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
    grid_color: str
    poc_color: str
    value_area_color: str
    liq_buy_color: str
    liq_sell_color: str
    volume_profile_width_ratio: float
    volume_profile_smoothing_sigma: float
    volume_profile_color: str
    volume_profile_alpha: float
    chart_main_panel_weight: int
    chart_volume_panel_weight: int
    render_dpi: int


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
    def __init__(self, output_dir: str, up_color: str, down_color: str, bg_color: str, 
                 grid_color: str, poc_color: str, value_area_color: str, 
                 liq_buy_color: str, liq_sell_color: str, volume_profile_width_ratio: float, 
                 render_dpi: int, volume_profile_smoothing_sigma: float, volume_profile_color: str,
                 volume_profile_alpha: float,
                 chart_main_panel_weight: int, chart_volume_panel_weight: int):
        self.config = ChartConfig(
            up_color=up_color,
            down_color=down_color,
            bg_color=bg_color,
            grid_color=grid_color,
            poc_color=poc_color,
            value_area_color=value_area_color,
            liq_buy_color=liq_buy_color,
            liq_sell_color=liq_sell_color,
            volume_profile_width_ratio=volume_profile_width_ratio, 
            volume_profile_smoothing_sigma=volume_profile_smoothing_sigma,
            volume_profile_color=volume_profile_color,
            volume_profile_alpha=volume_profile_alpha,
            chart_main_panel_weight=chart_main_panel_weight,
            chart_volume_panel_weight=chart_volume_panel_weight,
            render_dpi=render_dpi
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
                linewidths=[1.5, 1.0, 1.0] # POC (1.5), VAH/VAL (1.0)
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
                    ax.spines['right'].set_color(self.config.grid_color)
                    ax.spines['bottom'].set_color(self.config.grid_color)
                    
                    # Force price ticks to right only
                    ax.yaxis.set_ticks_position('right')

                    # v6.51 Hardening: Distinguish Price from Volume to prevent scale confusion
                    if i == 0:
                        ax.set_ylabel('Price', color=self.config.grid_color, fontsize=9, fontweight='bold')
                        ax.yaxis.set_label_position('right')
                    elif i == 2: # Volume panel usually at index 2
                        ax.set_ylabel('Vol', color=self.config.grid_color, fontsize=9, fontweight='bold')
                        ax.yaxis.set_label_position('right')

                main_ax = axlist[0]

                # 4. Overlay Volume Profile Histogram
                if "profile_data" in profile_data:
                    self._overlay_volume_profile(main_ax, plot_df, profile_data["profile_data"])
    
                # 4. Overlay Liquidation Zones
                if liquidations:
                    self._overlay_liquidations(main_ax, plot_df, liquidations)
    
                # 5. Overlay Trendlines
                trendlines = self.extractor.detect_trendlines(df) # Use original df with lowercase columns
                for line in trendlines:
                    main_ax.plot(line['x'], line['y'], color=line['color'], linestyle='--', linewidth=1.5, alpha=0.9)
    
                # 6. OCR Text Hard Injection (Minimalist Right-Side Identifier)
                # v6.65: Labels are right-aligned to the last candle, but price numbers 
                # are removed to keep the footprint extremely small and non-obstructive.
                x_pos = len(plot_df) - 1
                bbox_alpha = 0.8
                
                label_style = dict(
                    fontsize=8, 
                    fontweight='bold', 
                    color='white',
                    ha='right',      # Right-aligned to price action
                    va='center',
                    zorder=2         # Background layer (candles draw on top)
                )
                
                # Point of Control (POC)
                if poc > 0:
                    main_ax.text(
                        x_pos, poc, f"POC: {poc:,.2f}", 
                        bbox=dict(facecolor=self.config.poc_color, alpha=bbox_alpha, edgecolor='none', boxstyle='round,pad=0.2'),
                        **label_style
                    )
                
                # Value Area High (VAH)
                if vah > 0:
                    main_ax.text(
                        x_pos, vah, f"VAH: {vah:,.2f}", 
                        bbox=dict(facecolor=self.config.value_area_color, alpha=bbox_alpha, edgecolor='none', boxstyle='round,pad=0.2'),
                        **label_style
                    )
                    
                # Value Area Low (VAL)
                if val > 0:
                    main_ax.text(
                        x_pos, val, f"VAL: {val:,.2f}", 
                        bbox=dict(facecolor=self.config.value_area_color, alpha=bbox_alpha, edgecolor='none', boxstyle='round,pad=0.2'),
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
        if not profile:
            return

        min_p, max_p = df['Low'].min(), df['High'].max()
        
        # Filter profile data to visible range
        visible_profile = [p for p in profile if min_p <= p['price'] <= max_p]
        
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
            zorder=1, 
            linewidth=0,           # 绝对禁止外边框，防止抗锯齿干扰
            edgecolor='none'       # 彻底关闭边缘颜色
        )

    def _overlay_liquidations(self, ax: plt.Axes, df: pd.DataFrame, liquidations: List[Dict[str, Any]]):
        """Draws semi-transparent liquidation heat bands."""
        min_p, max_p = df['Low'].min(), df['High'].max()
        band_height = (max_p - min_p) * 0.015
        
        for liq in liquidations:
            try:
                parsed = parse_liquidation_data(liq)
                price = parsed['price']
                if not (min_p <= price <= max_p):
                    continue
                    
                side = parsed['side']
                color = self.config.liq_buy_color if side == 'BUY' else self.config.liq_sell_color
                
                # Dynamic alpha based on quantity
                qty = parsed['qty']
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
