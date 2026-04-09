import numpy as np
import logging
from typing import Dict, List, Any, Optional
from scipy.ndimage import gaussian_filter1d
from scipy.signal import find_peaks
from src.infrastructure.exchange.models import KlineData, OpenInterestData, RatioData

# Initialize project-standard logger
from src.utils.logger_utils import setup_logger
logger = setup_logger(__name__)

class LiquidationRadar:
    """The Synthetic Liquidation Synthesizer.
    
    Reverse-engineers retail 'traps' using OHLCV, Open Interest, and Taker Flow 
    to localize theoretical liquidation clusters (Structural Magnets).
    """

    def __init__(self, 
                 volume_moving_average_period: int, 
                 volume_surge_vs_ma_ratio: float,
                 max_liquidation_clusters: int,
                 long_taker_threshold: float,
                 short_taker_threshold: float,
                 liquid_projection_50x: float,
                 liquid_projection_25x: float,
                 weight_25x: float,
                 gaussian_sigma: float,
                 grid_bins: int,
                 grid_padding_ratio: float):
        self.volume_moving_average_period = volume_moving_average_period
        self.volume_surge_vs_ma_ratio = volume_surge_vs_ma_ratio
        self.max_liquidation_clusters = max_liquidation_clusters
        self.long_taker_threshold = long_taker_threshold
        self.short_taker_threshold = short_taker_threshold
        self.liquid_projection_50x = liquid_projection_50x
        self.liquid_projection_25x = liquid_projection_25x
        self.weight_25x = weight_25x
        self.gaussian_sigma = gaussian_sigma
        self.grid_bins = grid_bins
        self.grid_padding_ratio = grid_padding_ratio

    def synthesize_clusters(self, 
                             klines: List[KlineData], 
                             oi_history: List[OpenInterestData], 
                             taker_history: List[RatioData]) -> Dict[str, List[Dict[str, Any]]]:
        """
        Synthesizes theoretical long and short liquidation clusters from order flow proxies.
        """
        try:
            if not klines or not oi_history or not taker_history:
                return {"long_liquidation": [], "short_liquidation": []}

            # 1. 提取数值序列并对齐时间 (假设输入已经按时间排序)
            volumes = np.array([k.volume for k in klines])
            closes = np.array([k.close for k in klines])
            
            # 对齐 OI 和 Taker 数据 (简单基于索引对齐，因为 collect 逻辑保证了窗口一致性)
            min_len = min(len(klines), len(oi_history), len(taker_history))
            volumes = volumes[-min_len:]
            closes = closes[-min_len:]
            oi_vals = np.array([o.open_interest for o in oi_history])[-min_len:]
            taker_ratios = np.array([t.long_short_ratio for t in taker_history])[-min_len:]

            # 2. 计算派生指标
            vol_ma = self._calculate_sma(volumes, self.volume_moving_average_period)
            # OI Delta (当前值 - 前一值)
            oi_deltas = np.diff(oi_vals, prepend=oi_vals[0])
            
            # 3. 识别累积节点 (Accumulation Nodes)
            # 条件：成交量激增且 OI 增加 (意味着新的对手盘正在入场并被锁定)
            accumulation_mask = (volumes > vol_ma * self.volume_surge_vs_ma_ratio) & (oi_deltas > 0)
            
            long_points = []
            short_points = []
            
            for i in range(min_len):
                if not accumulation_mask[i]:
                    continue
                
                entry_price = closes[i]
                weight = oi_deltas[i]
                
                # 方向判定 (Dominant Taker)
                if taker_ratios[i] > self.long_taker_threshold: # 多头主动性强
                    # 投影做多者的爆仓位
                    long_points.append({"price": entry_price * (1.0 - self.liquid_projection_50x), "weight": weight}) # 50x
                    long_points.append({"price": entry_price * (1.0 - self.liquid_projection_25x), "weight": weight * self.weight_25x}) # 25x
                elif taker_ratios[i] < self.short_taker_threshold: # 空头主动性强
                    short_points.append({"price": entry_price * (1.0 + self.liquid_projection_50x), "weight": weight}) # 50x
                    short_points.append({"price": entry_price * (1.0 + self.liquid_projection_25x), "weight": weight * self.weight_25x}) # 25x

            return {
                "long_liquidation": self._cluster_points(long_points),
                "short_liquidation": self._cluster_points(short_points)
            }

        except Exception as e:
            logger.error(f"LiquidationRadar synthesis failed: {e}", exc_info=True)
            return {"long_liquidation": [], "short_liquidation": []}

    def _calculate_sma(self, data: np.ndarray, period: int) -> np.ndarray:
        if len(data) < period:
            return np.full_like(data, np.mean(data))
        ret = np.cumsum(data, dtype=float)
        ret[period:] = ret[period:] - ret[:-period]
        return ret / period

    def _cluster_points(self, points: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """使用高斯平滑对离散的爆仓点进行密度聚合。"""
        if not points:
            return []
            
        prices = [p["price"] for p in points]
        weights = [p["weight"] for p in points]
        
        # 定义价格网格 (粒度由 grid_bins 决定)
        # 使用 grid_padding_ratio (默认 0.05) 来定义边界，防止平滑截断
        min_p = min(prices) * (1.0 - self.grid_padding_ratio)
        max_p = max(prices) * (1.0 + self.grid_padding_ratio)
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
