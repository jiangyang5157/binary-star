import numpy as np
from typing import Dict, List, Any
from scipy.ndimage import gaussian_filter1d
from scipy.signal import find_peaks
from src.infrastructure.exchange.models import KlineData, OpenInterestData, RatioData

# Initialize project-standard logger
from src.utils.logger_utils import setup_logger
logger = setup_logger(__name__)

class LiquidationEstimator:
    """The Synthetic Liquidation Synthesizer.
    
    Reverse-engineers retail 'traps' using OHLCV, Open Interest, and Taker Flow 
    to localize theoretical liquidation clusters (Structural Magnets).
    """

    # Physics constants (derived from leverage, not strategy knobs)
    LEVERAGE_50X = 50.0
    LEVERAGE_25X = 25.0
    WEIGHT_25X = 0.6  # relative intensity of 25x clusters vs 50x

    def __init__(self,
                 volume_moving_average_period: int,
                 volume_surge_vs_ma_ratio: float,
                 max_liquidation_clusters: int,
                 long_taker_threshold: float,
                 short_taker_threshold: float,
                 gaussian_sigma: float,
                 grid_bins: int,
                 grid_padding_atr: float,
                 # ── optional overrides for physics constants ──────────
                 liquid_projection_50x: float | None = None,
                 liquid_projection_25x: float | None = None,
                 weight_25x: float | None = None):
        self.volume_moving_average_period = volume_moving_average_period
        self.volume_surge_vs_ma_ratio = volume_surge_vs_ma_ratio
        self.max_liquidation_clusters = max_liquidation_clusters
        self.long_taker_threshold = long_taker_threshold
        self.short_taker_threshold = short_taker_threshold
        # Physics: liquidation distance = 1 / leverage
        self.liquid_projection_50x = liquid_projection_50x or (1.0 / self.LEVERAGE_50X)
        self.liquid_projection_25x = liquid_projection_25x or (1.0 / self.LEVERAGE_25X)
        self.weight_25x = weight_25x if weight_25x is not None else self.WEIGHT_25X
        self.gaussian_sigma = gaussian_sigma
        self.grid_bins = grid_bins
        self.grid_padding_atr = grid_padding_atr

    def synthesize_clusters(self, 
                             klines: List[KlineData], 
                             oi_history: List[OpenInterestData], 
                             taker_history: List[RatioData],
                             current_price: float,
                             atr: float) -> Dict[str, List[Dict[str, Any]]]:
        """
        Synthesizes active long and short liquidation clusters based on order flow proxies.
        Hardening: Syncs filtering with global current_price.
        """
        try:
            if not klines or not oi_history or not taker_history:
                return {"long_liquidation": [], "short_liquidation": []}

            # 0. Define current High/Low range for grid anchoring
            k_highs = [k.high for k in klines]
            k_lows = [k.low for k in klines]
            range_min = min(k_lows)
            range_max = max(k_highs)

            # 1. Align time series
            min_len = min(len(klines), len(oi_history), len(taker_history))
            volumes = np.array([k.volume for k in klines])[-min_len:]
            closes = np.array([k.close for k in klines])[-min_len:]
            oi_vals = np.array([o.open_interest for o in oi_history])[-min_len:]
            taker_ratios = np.array([t.long_short_ratio for t in taker_history])[-min_len:]
            
            logger.debug(f"LiquidationEstimator: Anchored to current_price: {current_price:.2f}")

            # 2. Derived metrics (SMA for surge detection, OI Delta for intent)
            vol_ma = self._calculate_sma(volumes, self.volume_moving_average_period)
            oi_deltas = np.diff(oi_vals, prepend=oi_vals[0])
            
            # 3. Dynamic Accumulation Detection
            accumulation_mask = (volumes > vol_ma * self.volume_surge_vs_ma_ratio) & (oi_deltas > 0)
            
            active_above = [] # Targeted for Short Squeeze (Purple)
            active_below = [] # Targeted for Long Trap (Green)
            
            for i in range(min_len):
                if not accumulation_mask[i]:
                    continue
                
                entry_p = closes[i]
                weight = oi_deltas[i]
                ratio = taker_ratios[i]
                
                # Rule-Based Projection (Based on Taker Dominance)
                if ratio > self.long_taker_threshold: # Taker Long Aggression
                    # Project potential Long Liquidations (Stops are below entry)
                    stops = [entry_p * (1.0 - self.liquid_projection_50x), entry_p * (1.0 - self.liquid_projection_25x)]
                    for s in stops:
                        if s < current_price: # ACTIVE: Still below current price
                            active_below.append({"price": s, "weight": weight})
                        else: # STALE: Price has already dropped through this level
                            logger.debug(f"Radar: Skipping stale LONG stop {s:.2f} (above price {current_price:.2f})")
                            
                elif ratio < self.short_taker_threshold: # Taker Short Aggression
                    # Project potential Short Liquidations (Stops are above entry)
                    stops = [entry_p * (1.0 + self.liquid_projection_50x), entry_p * (1.0 + self.liquid_projection_25x)]
                    for s in stops:
                        if s > current_price: # ACTIVE: Still above current price
                            active_above.append({"price": s, "weight": weight})
                        else: # STALE: Price has already squeezed through this level
                            logger.debug(f"Radar: Skipping stale SHORT stop {s:.2f} (below price {current_price:.2f})")

            # 4. Final Semantic Consolidation (Trigger-Based)
            # Regardless of origin, categorize by current market potential
            # to prevent 'Green above Red' visual paradox.
            final_long = []  # To be colored Green (Below price)
            final_short = [] # To be colored Purple (Above price)
            
            # Combine all active points to re-evaluate their role
            all_active = active_above + active_below
            
            for p in all_active:
                if p["price"] >= current_price:
                    final_short.append(p)
                else:
                    final_long.append(p)

            return {
                "long_liquidation": self._cluster_points(final_long, atr, range_min, range_max),
                "short_liquidation": self._cluster_points(final_short, atr, range_min, range_max)
            }

        except Exception as e:
            logger.error(f"LiquidationEstimator synthesis failed: {e}", exc_info=True)
            return {"long_liquidation": [], "short_liquidation": []}

    def _calculate_sma(self, data: np.ndarray, period: int) -> np.ndarray:
        if len(data) < period:
            return np.full_like(data, np.mean(data))
        ret = np.cumsum(data, dtype=float)
        ret[period:] = ret[period:] - ret[:-period]
        return ret / period

    def _cluster_points(self, points: List[Dict[str, Any]], atr: float, range_min: float, range_max: float) -> List[Dict[str, Any]]:
        """使用高斯平滑对离散的爆仓点进行密度聚合。"""
        if not points:
            return []
            
        prices = [p["price"] for p in points]
        weights = [p["weight"] for p in points]
        
        # 定义价格网格 (粒度由 grid_bins 决定)
        # 使用 grid_padding_atr 而不是 ratio，确保尺度无关性
        grid_min = min(min(prices), range_min)
        grid_max = max(max(prices), range_max)
        
        min_p = grid_min - (self.grid_padding_atr * atr)
        max_p = grid_max + (self.grid_padding_atr * atr)
        grid = np.linspace(min_p, max_p, self.grid_bins)
        density = np.zeros_like(grid)
        
        # 将点映射到网格
        for p, w in zip(prices, weights):
            idx = (np.abs(grid - p)).argmin()
            density[idx] += w
            
        # 高斯平滑
        smoothed = gaussian_filter1d(density, sigma=self.gaussian_sigma)
        
        # 寻找峰值
        peaks, properties = find_peaks(smoothed, height=0)
        peak_heights = properties['peak_heights']
        
        # 整理结果
        results = []
        for i in range(len(peaks)):
            results.append({
                "price": float(round(grid[peaks[i]], 2)),
                "intensity": float(peak_heights[i])
            })
            
        # 排序并取前 N 个 (按配置中的最大集群数限制)
        results.sort(key=lambda x: x["intensity"], reverse=True)
        top_results = results[:self.max_liquidation_clusters]
        
        # 归一化强度
        if top_results:
            max_intensity = top_results[0]["intensity"]
            for r in top_results:
                r["intensity"] = round(r["intensity"] / (max_intensity + 1e-9), 2)
        
        return top_results[:self.max_liquidation_clusters]
