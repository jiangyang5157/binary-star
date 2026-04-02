import os
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional, Tuple, Union

import pandas as pd

from src.infrastructure.binance.client import BinanceFuturesClient
from src.analyzer.volume_profile import VolumeProfileAnalyzer, VolumeProfileConfig
from src.analyzer.market_regime import MarketRegimeAnalyzer, MarketRegimeConfig
from src.analyzer.chart_generator import ChartGenerator
from src.utils.pipeline_utils import safe_format
from src.utils.datetime_utils import (
    get_current_utc_time, format_datetime, FILE_TIMESTAMP_FORMAT, 
    to_iso_zulu, get_interval_seconds
)
from src.utils.path_utils import resolve_project_root
from src.utils.json_utils import convert_to_json_string, save_json

# Initialize project-standard logger
from src.utils.logger_utils import setup_logger
logger = setup_logger(__name__)

@dataclass(frozen=True)
class TimeframeConfig:
    """Encapsulates timeframe parameters for market data fetching."""
    time_interval: str
    lookback_candles: int

@dataclass(frozen=True)
class MarketObserverConfig:
    """Type-safe configuration for the MarketObserver."""
    macro_context: TimeframeConfig
    micro_context: TimeframeConfig
    vp_value_area_width: float
    vp_price_bucket_count: int
    order_flow_lookback_hours: float
    atr_period: int
    bb_period: int
    bb_std_dev: float
    kc_period: int
    kc_multiplier: float
    vol_ma_period: int
    max_liquidation_events_to_fetch: int
    max_liquidation_events_for_context: int
    max_high_volume_node_count: int
    max_low_volume_node_count: int
    high_volume_node_detection_threshold: float
    low_volume_node_detection_threshold: float
    min_node_gap_price: int
    top_structural_node_count: int
    trend_intensity_lookback_hours: float
    wick_skewness_period: int
    liquidation_cluster_atr_multiplier: float
    liquidation_cluster_fallback_percentage: float
    funding_rate_lookback_hours: float
    volatility_intensity_lookback_hours: int
    regime_trend_threshold: float
    regime_volatility_baseline_ratio: float
    regime_volatility_expansion_ratio: float
    regime_volatility_extreme_ratio: float
    regime_volume_breakout_threshold: float
    regime_long_short_imbalance_ratio: float
    regime_poc_gravity_atr_distance: float
    regime_vacuum_risk_score: float
    regime_wick_skewness_exhaustion: float
    regime_trend_intensity_strong: float
    regime_min_rr_ranging: float
    regime_min_rr_trending: float
    regime_volume_baseline_ratio: float
    regime_squeeze_threshold: float
    regime_balanced_atr_multiplier: float
    regime_cvd_slope_threshold: float
    max_liquidation_clusters: int
    wick_skew_fallback: float
    max_tool_iterations: int

    @classmethod
    def from_dict(cls, cfg: Dict[str, Any]) -> "MarketObserverConfig":
        """Factory method to create config from a nested dictionary."""
        shared = cfg.get('agent_model_shared_config', {})
        sampling = cfg['analysis_window']
        topography = cfg['topography_parameters']
        regime = cfg['regime_parameters']
        
        macro = sampling['macro_context']
        micro = sampling['micro_context']
        
        return cls(
            max_tool_iterations=int(shared.get('max_tool_iterations', 5)),
            macro_context=TimeframeConfig(
                time_interval=str(macro['time_interval']), 
                lookback_candles=int(macro['lookback_candles'])
            ),
            micro_context=TimeframeConfig(
                time_interval=str(micro['time_interval']), 
                lookback_candles=int(micro['lookback_candles'])
            ),
            funding_rate_lookback_hours=float(sampling['funding_rate_lookback_hours']),
            order_flow_lookback_hours=float(sampling['order_flow_lookback_hours']),
            trend_intensity_lookback_hours=float(sampling['trend_intensity_lookback_hours']),
            volatility_intensity_lookback_hours=int(sampling['volatility_intensity_lookback_hours']),
            
            vp_value_area_width=float(topography['volume_profile_value_area_width']),
            vp_price_bucket_count=int(topography['volume_profile_price_bucket_count']),
            vol_ma_period=int(topography['volume_moving_average_period']),
            max_high_volume_node_count=int(topography['max_high_volume_node_count']),
            max_low_volume_node_count=int(topography['max_low_volume_node_count']),
            high_volume_node_detection_threshold=float(topography['high_volume_node_detection_threshold']),
            low_volume_node_detection_threshold=float(topography['low_volume_node_detection_threshold']),
            min_node_gap_price=int(topography['min_price_gap_between_nodes']),
            top_structural_node_count=int(topography['top_structural_node_count']),
            atr_period=int(topography['average_true_range_period']),
            bb_period=int(topography['bollinger_bands_period']),
            bb_std_dev=float(topography['bollinger_bands_std_dev']),
            kc_period=int(topography['keltner_channels_period']),
            kc_multiplier=float(topography['keltner_channels_multiplier']),
            wick_skewness_period=int(topography['wick_skewness_period']),
            wick_skew_fallback=float(topography['wick_skew_fallback']),
            max_liquidation_clusters=int(topography['max_liquidation_clusters']),
            max_liquidation_events_to_fetch=int(topography['max_liquidation_events_to_fetch']),
            max_liquidation_events_for_context=int(topography['max_liquidation_events_for_context']),
            liquidation_cluster_atr_multiplier=float(topography['liquidation_cluster_atr_multiplier']),
            liquidation_cluster_fallback_percentage=float(topography['liquidation_cluster_fallback_percentage']),
            
            # Regime Parameters (Strategic Knobs)
            regime_trend_threshold=float(regime['trend_intensity_threshold']),
            regime_volatility_baseline_ratio=float(regime['volatility_baseline_ratio']),
            regime_volatility_expansion_ratio=float(regime['volatility_expansion_ratio']),
            regime_volatility_extreme_ratio=float(regime['volatility_extreme_ratio']),
            regime_volume_breakout_threshold=float(regime['volume_breakout_threshold']),
            regime_long_short_imbalance_ratio=float(regime['long_short_imbalance_ratio']),
            regime_poc_gravity_atr_distance=float(regime['poc_gravity_atr_distance']),
            regime_vacuum_risk_score=float(regime['vacuum_risk_score']),
            regime_wick_skewness_exhaustion=float(regime['wick_skewness_exhaustion']),
            regime_trend_intensity_strong=float(regime['trend_intensity_strong']),
            regime_min_rr_ranging=float(regime['min_rr_ranging']),
            regime_min_rr_trending=float(regime['min_rr_trending']),
            regime_volume_baseline_ratio=float(regime['volume_baseline_ratio']),
            regime_squeeze_threshold=float(regime['squeeze_threshold']),
            regime_balanced_atr_multiplier=float(regime['balanced_atr_multiplier']),
            regime_cvd_slope_threshold=float(regime['cvd_slope_threshold'])
        )

    @property
    def taker_vol_delta_lookback(self) -> int:
        """Calculates candle count for tactical window (default 1h)."""
        secs = get_interval_seconds(self.micro_context.time_interval)
        return max(1, int(self.order_flow_lookback_hours * 3600 / secs))

    @property
    def trend_lookback(self) -> int:
        """Calculates candle count for structural window (default 24h)."""
        secs = get_interval_seconds(self.macro_context.time_interval)
        return max(1, int(self.trend_intensity_lookback_hours * 3600 / secs))

@dataclass
class RawMarketData:
    """Holds raw datum collected during an observation cycle."""
    macro_klines: List[List[Any]] = field(default_factory=list)
    micro_klines: List[List[Any]] = field(default_factory=list)
    macro_oi: Optional[Dict[str, Any]] = None
    micro_oi: Optional[Dict[str, Any]] = None
    macro_ls: List[Dict[str, Any]] = field(default_factory=list)
    micro_ls: List[Dict[str, Any]] = field(default_factory=list)
    current_oi: Optional[Dict[str, Any]] = None
    liquidations: List[Dict[str, Any]] = field(default_factory=list)
    funding_rate: List[Dict[str, Any]] = field(default_factory=list)

@dataclass
class ProcessedMarketMetrics:
    """Container for calculated market indicators and topological profiles."""
    price_dynamics: Dict[str, Any]
    structural_anchors: Dict[str, Any]
    volume_profile: Dict[str, Any]
    market_regime: Dict[str, Any]
    sentiment_signals: Dict[str, Any]

class MarketDataLoader:
    """Handles high-fidelity data collection from remote exchange endpoints."""
    def __init__(self, binance_client: BinanceFuturesClient, config: MarketObserverConfig):
        self.client = binance_client
        self.config = config

    def collect(self, symbol: str, at_time: datetime) -> RawMarketData:
        """Fetches a synchronized snapshot of technical and psychological market data."""
        ts_ms = int(at_time.timestamp() * 1000)
        cfg = self.config
        
        # Calculate delta for historical OI to ensure we get a point before the target time
        oi_delta = self._get_interval_delta(cfg.macro_context.time_interval)
        historical_ts_ms = ts_ms - int(oi_delta.total_seconds() * 1000)

        # Calculate liquidation window based on micro analysis duration
        micro_delta = self._get_interval_delta(cfg.micro_context.time_interval)
        liq_lookback_ms = int(micro_delta.total_seconds() * cfg.micro_context.lookback_candles * 1000)
        liq_start_ts_ms = ts_ms - liq_lookback_ms

        return RawMarketData(
            macro_klines=self.client.fetch_historical_klines(symbol, cfg.macro_context.time_interval, cfg.macro_context.lookback_candles, endTime=ts_ms) or [],
            micro_klines=self.client.fetch_historical_klines(symbol, cfg.micro_context.time_interval, cfg.micro_context.lookback_candles, endTime=ts_ms) or [],
            macro_oi=self.client.fetch_open_interest(symbol, cfg.macro_context.time_interval, endTime=historical_ts_ms),
            micro_oi=self.client.fetch_open_interest(symbol, cfg.micro_context.time_interval, endTime=historical_ts_ms),
            macro_ls=self.client.fetch_long_short_ratio(symbol, cfg.macro_context.time_interval, limit=1, endTime=ts_ms) or [],
            micro_ls=self.client.fetch_long_short_ratio(symbol, cfg.micro_context.time_interval, limit=1, endTime=ts_ms) or [],
            current_oi=self.client.fetch_open_interest(symbol, cfg.micro_context.time_interval, endTime=ts_ms),
            liquidations=self.client.fetch_liquidations(symbol, limit=cfg.max_liquidation_events_to_fetch, startTime=liq_start_ts_ms, endTime=ts_ms) or [],
            funding_rate=self.client.fetch_funding_rate(symbol, limit=100, startTime=ts_ms - (int(cfg.funding_rate_lookback_hours) * 60 * 60 * 1000), endTime=ts_ms) or []
        )

    def _get_interval_delta(self, interval: str) -> timedelta:
        """Converts Binance interval strings to timedeltas."""
        return timedelta(seconds=get_interval_seconds(interval))

class MarketMetricsRefiner:
    """Processes raw data into actionable technical and semantic metrics."""
    def __init__(self, config: MarketObserverConfig, vp_analyzer: VolumeProfileAnalyzer, regime_analyzer: MarketRegimeAnalyzer):
        self.config = config
        self.vp = vp_analyzer
        self.regime = regime_analyzer

    def refine(self, raw: RawMarketData) -> ProcessedMarketMetrics:
        """Orchestrates the refined calculation of all market dimensions."""
        m_df = self.vp.process_klines(raw.macro_klines)
        n_df = self.vp.process_klines(raw.micro_klines)
        
        # Calculate ATR-Macro here to pass down for high-fidelity clustering
        atr_macro = m_df['atr'].iloc[-1] if 'atr' in m_df.columns and not m_df.empty else 0
        current_price = m_df['close'].iloc[-1] if not m_df.empty else 0
        
        profile = self.vp.calculate_profile(m_df)
        nodes = self.vp.find_significant_nodes(profile)
        regime_data = self.regime.analyze(m_df)
        
        return ProcessedMarketMetrics(
            price_dynamics=self._derive_price_dynamics(m_df, n_df),
            structural_anchors=self._derive_anchors(m_df, profile),
            volume_profile=self._refine_topography(profile, nodes, atr_macro, current_price),
            market_regime=regime_data,
            sentiment_signals=self._derive_sentiment(raw, atr_macro)
        )

    def _derive_price_dynamics(self, m_df: pd.DataFrame, n_df: pd.DataFrame) -> Dict[str, Any]:
        last = m_df.iloc[-1]
        h, l, c = last['high'], last['low'], last['close']
        wick_skew = (c - l) / (h - l) if (h - l) > 0 else self.config.wick_skew_fallback
        
        atr_m = m_df['atr'].iloc[-1]
        atr_n = n_df['atr'].iloc[-1]
        
        # 1. Vol-Ratio (Micro vs Macro)
        ratio = get_interval_seconds(self.config.macro_context.time_interval) / get_interval_seconds(self.config.micro_context.time_interval)
        volatility_ratio = atr_n / (atr_m / ratio) if atr_m > 0 else 1.0
        
        # 2. Volatility Intensity (Current Macro ATR vs Historical Average)
        # We use a lookback from config for the average-of-average
        avg_atr_lookback = min(self.config.volatility_intensity_lookback_hours, len(m_df))
        mean_historical_atr = m_df['atr'].tail(avg_atr_lookback).mean()
        vol_intensity = (atr_m / mean_historical_atr) if mean_historical_atr > 0 else 1.0
        
        return {
            "current_price": c,
            "atr_macro": round(atr_m, 2) if isinstance(atr_m, float) else atr_m,
            "atr_micro": round(atr_n, 2) if isinstance(atr_n, float) else atr_n,
            "latest_wick_skew": f"{wick_skew:.2f}",
            "volatility_ratio": f"{volatility_ratio:.2f}",
            "volatility_intensity_index": f"{vol_intensity:.2f}" # > 1.0 means current volatility is expanding beyond its own average
        }

    def _derive_anchors(self, df: pd.DataFrame, profile: Dict[str, Any]) -> Dict[str, Any]:
        price = df['close'].iloc[-1]
        atr = df['atr'].iloc[-1]
        def to_atr(val):
            return f"{((price - val) / atr):.2f}" if val and atr else None

        return {
            "poc_dist_atr": to_atr(profile.get('poc')),
            "vah_dist_atr": to_atr(profile.get('vah')),
            "val_dist_atr": to_atr(profile.get('val'))
        }

    def _refine_topography(self, profile: Dict[str, Any], nodes: Dict[str, List], atr_macro: float, current_price: float) -> Dict[str, Any]:
        """
        Constructs a physically accurate map of volume nodes relative to CURRENT PRICE (not POC).
        This eliminates 'physical contradictions' where support nodes appear above the current price.
        """
        poc = profile.get('poc', 0)
        limit = self.config.top_structural_node_count
        all_nodes = [{**n, "type": "HVN"} for n in nodes.get('hvn', [])] + [{**n, "type": "LVN"} for n in nodes.get('lvn', [])]
        
        # Determine structural_state (BALANCED/IMBALANCED)
        vah = profile.get('vah', 0)
        val = profile.get('val', 0)
        va_width = vah - val
        
        # Consistent with VolumeProfileAnalyzer logic: Balanced if VA width < Multiplier * ATR
        state = "BALANCED" if va_width < (atr_macro * self.config.regime_balanced_atr_multiplier) else "IMBALANCED"
        if va_width == 0: state = "INITIALIZING"
        
        # TOPOLOGICAL VALIDATOR: Slice relative to CURRENT PRICE to ensure logic consistency for the Strategist
        anchors_above = sorted([n for n in all_nodes if n['price'] > current_price], key=lambda x: x['price'])[:limit]
        anchors_below = sorted([n for n in all_nodes if n['price'] < current_price], key=lambda x: x['price'], reverse=True)[:limit]

        return {
            "poc": poc, "vah": vah, "val": val,
            "structural_state": state,
            "anchors_above": anchors_above,
            "anchors_below": anchors_below
        }

    def _derive_sentiment(self, raw: RawMarketData, atr_macro: float) -> Dict[str, Any]:
        cvd_current = 0.0
        cvd_prev = 0.0
        
        if raw.micro_klines:
            lookback = self.config.taker_vol_delta_lookback
            # Current window
            curr_window = raw.micro_klines[-lookback:]
            for k in curr_window:
                v, tb = float(k[5]), float(k[9])
                cvd_current += (tb - (v - tb))
            
            # Previous window (for slope)
            if len(raw.micro_klines) >= lookback * 2:
                prev_window = raw.micro_klines[-(lookback*2):-lookback]
                for k in prev_window:
                    v, tb = float(k[5]), float(k[9])
                    cvd_prev += (tb - (v - tb))
        
        cvd_slope = "STABLE"
        if cvd_current > cvd_prev + self.config.regime_cvd_slope_threshold: cvd_slope = "UPWARD"
        elif cvd_current < cvd_prev - self.config.regime_cvd_slope_threshold: cvd_slope = "DOWNWARD"

        cur_oi = float(raw.current_oi.get('openInterest', 0)) if raw.current_oi else 0
        def oi_delta(hist):
            if not hist: return None
            h_val = float(hist.get('openInterest', 0))
            return f"{(((cur_oi - h_val) / h_val) * 100):+.2f}%" if h_val > 0 else None

        return {
            "oi_nominal": cur_oi,
            "oi_delta_macro": oi_delta(raw.macro_oi),
            "oi_delta_micro": oi_delta(raw.micro_oi),
            "long_short_ratio_macro": raw.macro_ls[0].get('longShortRatio') if raw.macro_ls else None,
            "long_short_ratio_micro": raw.micro_ls[0].get('longShortRatio') if raw.micro_ls else None,
            "net_taker_delta": f"{cvd_current:.4f}",
            "cvd_trend": cvd_slope,
            "funding_rate": raw.funding_rate[-1].get('fundingRate') if raw.funding_rate else None,
            "liquidation_clusters": self._parse_liquidations_to_clusters(raw.liquidations, atr_macro)
        }

    def _parse_liquidations_to_clusters(self, liqs: List[Dict], atr_macro: float) -> Optional[Dict[str, Any]]:
        """Groups raw liquidations into price clusters for identifying liquidity magnets."""
        if not liqs: return None
        
        # 1. Price Bucket (Dynamic ATR Resolution vs % Fallback)
        prices = [float(l.get('price', 0)) for l in liqs]
        if not prices: return None
        
        avg_p = sum(prices) / len(prices)
        
        if atr_macro > 0:
            # Use 0.25 ATR (default) as resolution for high-fidelity clustering
            bucket_size = atr_macro * self.config.liquidation_cluster_atr_multiplier
        else:
            # Fallback to % of price if ATR is missing (e.g. 0.5%)
            bucket_size = avg_p * self.config.liquidation_cluster_fallback_percentage
        
        clusters = {}
        for l in liqs:
            p = float(l.get('price', 0))
            bucket = round(p / bucket_size) * bucket_size
            key = f"{bucket:.2f}"
            if key not in clusters:
                clusters[key] = {"total_qty": 0, "count": 0, "side": l.get('side')}
            clusters[key]["total_qty"] += float(l.get('qty', 0))
            clusters[key]["count"] += 1
            
        # 2. Return top clusters by volume
        sorted_clusters = sorted(clusters.items(), key=lambda x: x[1]['total_qty'], reverse=True)
        return {k: v for k, v in sorted_clusters[:self.config.max_liquidation_clusters]}
class MarketObserver:
    """
    Elite Market Topographer & Observer.
    
    Coordinates high-fidelity telemetry collection without AI dependency.
    Provides a 'Single Source of Truth' for downstream strategy agents.
    """

    def __init__(
        self, 
        config: MarketObserverConfig, 
        symbol: str, 
        data_root: str,
        binance_client: BinanceFuturesClient,
        chart_generator: ChartGenerator
    ):
        """
        Initializes the Observer as a high-fidelity topographical engine.
        Now uses Dependency Injection for production-grade testing and auth isolation.
        """
        self.symbol = symbol
        self.data_root = data_root
        self.config = config
        
        # Core Dependencies (Injected)
        self._binance = binance_client
        self._vp_analyzer = self._init_vp()
        self._regime_analyzer = self._init_regime()
        self._charting = chart_generator
        
        # Internal Sub-components
        self.loader = MarketDataLoader(self._binance, self.config)
        self.refiner = MarketMetricsRefiner(self.config, self._vp_analyzer, self._regime_analyzer)

    def observe(self, timestamp: Optional[datetime] = None, data_root: Optional[str] = None, persist: bool = True) -> Dict[str, Any]:
        """Executes a full topographical observation cycle."""
        at_time = timestamp or get_current_utc_time()
        logger.info(f"MarketObserver: Starting mapping for {self.symbol} at {at_time}")

        # 1. Data Collection
        raw = self.loader.collect(self.symbol, at_time)
        
        # --- Data Quality Fuse ---
        macro_threshold = int(self.config.macro_context.lookback_candles * 0.9)
        if len(raw.macro_klines) < macro_threshold:
            logger.error(f"MarketObserver: Data Integrity Failure. Macro Klines count ({len(raw.macro_klines)}) < threshold ({macro_threshold})")
            return {"error": "Data Integrity Failure", "details": "Insufficient macro market telemetry."}

        # 2. Metric Refinement
        metrics = self.refiner.refine(raw)

        # 3. Visual Assets
        snapshots = self._generate_snapshots(raw, metrics, data_root or self.data_root, at_time)
            
        # 4. Packaging & Persistence
        observation = self._package_observation(metrics, snapshots, at_time)
        
        if persist:
            self._persist_observation(observation, data_root or self.data_root)
        
        return observation

    def _persist_observation(self, observation: Dict[str, Any], data_root: str):
        """Saves the market observation JSON and its HTML counterpart to the audits shelf."""
        try:
            obs_dir = os.path.join(data_root, "market")
            os.makedirs(obs_dir, exist_ok=True)
            
            # Format: SYMBOL_market_TIMESTAMP
            import re
            m = re.search(r"(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})", observation['timestamp'])
            ts_str = f"{m.group(1)}{m.group(2)}{m.group(3)}_{m.group(4)}{m.group(5)}{m.group(6)}" if m else datetime.now().strftime("%Y%m%d_%H%M%S")
                
            # 1. Save JSON Record
            json_filename = f"{self.symbol}_market_{ts_str}.json"
            json_path = os.path.join(obs_dir, json_filename)
            save_json(observation, json_path)
            
            logger.info(f"MarketObserver: Market JSON Record persisted to {json_path}")
        except Exception as e:
            logger.error(f"MarketObserver: Failed to persist observation: {e}")

    def _generate_snapshots(self, raw: RawMarketData, metrics: ProcessedMarketMetrics, data_root: str, at_time: datetime) -> Dict[str, str]:
        img_dir = os.path.join(data_root, "klines")
        self._charting.storage.output_dir = img_dir # Direct access to manager if needed or use Facade setter
        
        ctx = {**metrics.volume_profile, "timestamp": format_datetime(at_time, FILE_TIMESTAMP_FORMAT)}
        m_df = self._vp_analyzer.process_klines(raw.macro_klines)
        n_df = self._vp_analyzer.process_klines(raw.micro_klines)
        
        return {
            "macro_snapshot": self._charting.generate_chart(self.symbol, m_df, ctx, raw.liquidations, time_interval=self.config.macro_context.time_interval),
            "micro_snapshot": self._charting.generate_chart(self.symbol, n_df, ctx, raw.liquidations, time_interval=self.config.micro_context.time_interval)
        }

    def _synthesize_topographic_summary(self, metrics: Any) -> str:
        """Compresses complex price geometry into a single tactical summary string."""
        try:
            m = metrics.__dict__ if hasattr(metrics, "__dict__") else metrics
            pd = m.get("price_dynamics", {})
            vp = m.get("volume_profile", {})
            atr = float(pd.get("atr_macro", 1.0))
            price = float(pd.get("current_price", 0))
            
            summary = []
            # 1. Structural Proximity
            val = float(vp.get("val", 0))
            vah = float(vp.get("vah", 0))
            val_dist = (price - val) / atr if atr > 0 else 0
            vah_dist = (price - vah) / atr if atr > 0 else 0
            
            if abs(val_dist) < 1.0: summary.append(f"Price pivoting at VAL ({val_dist:.2f} ATR).")
            elif abs(vah_dist) < 1.0: summary.append(f"Price pivoting at VAH ({vah_dist:.2f} ATR).")
            
            # 2. Nearest Friction (HVN)
            all_anchors = vp.get("anchors_above", []) + vp.get("anchors_below", [])
            hvns = [a for a in all_anchors if a.get("type") == "HVN"]
            if hvns:
                nearest_hvn = min(hvns, key=lambda x: abs(x["price"] - price))
                hvn_dist = (nearest_hvn["price"] - price) / atr if atr > 0 else 0
                summary.append(f"Nearest Friction: HVN at {nearest_hvn['price']:.2f} ({hvn_dist:.2f} ATR).")
            
            # 3. Nearest Vacuum (LVN)
            lvns = [a for a in all_anchors if a.get("type") == "LVN"]
            if lvns:
                nearest_lvn = min(lvns, key=lambda x: abs(x["price"] - price))
                lvn_dist = (nearest_lvn["price"] - price) / atr if atr > 0 else 0
                summary.append(f"Nearest Vacuum: LVN at {nearest_lvn['price']:.2f} ({lvn_dist:.2f} ATR).")

            return " ".join(summary)
        except Exception as e:
            return f"Topography synthesis limited: {e}"

    def _analyze_cvd_dynamics(self, metrics: Any) -> str:
        """Analyzes CVD-Price correlation to detect passive absorption vs aggressive discovery."""
        try:
            m = metrics.__dict__ if hasattr(metrics, "__dict__") else metrics
            sent = m.get("sentiment_signals", {})
            regime = m.get("market_regime", {})
            
            cvd_trend = sent.get("cvd_trend", "UNKNOWN")
            price_regime = regime.get("price_trend_regime", "UNKNOWN")
            taker_delta = float(sent.get("net_taker_delta", 0))
            
            if cvd_trend == "DOWNWARD" and "BULLISH" in str(price_regime):
                return "[PASSIVE_ABSORPTION]: Bids are absorbing aggressive selling. Bullish Divergence."
            elif cvd_trend == "UPWARD" and "BEARISH" in str(price_regime):
                return "[PASSIVE_ABSORPTION]: Offers are absorbing aggressive buying. Bearish Divergence."
            elif (cvd_trend == "DOWNWARD" and "BEARISH" in str(price_regime)) and taker_delta < -500:
                return "[AGGRESSIVE_DISCOVERY]: High-conviction selling confirmed by CVD slope."
            elif (cvd_trend == "UPWARD" and "BULLISH" in str(price_regime)) and taker_delta > 500:
                return "[AGGRESSIVE_DISCOVERY]: High-conviction buying confirmed by CVD slope."
            
            return f"CVD Sentiment is {cvd_trend}. No major divergence detected."
        except Exception as e:
            return f"CVD dynamics analysis limited: {e}"

    def _package_observation(self, metrics: Any, charts: Dict[str, str], at_time: datetime) -> Dict[str, Any]:
        return {
            "symbol": self.symbol,
            "timestamp": format_datetime(at_time, FILE_TIMESTAMP_FORMAT),
            "analytical_parameters": {
                "macro_timeframe": {
                    "interval": self.config.macro_context.time_interval,
                    "interval_minutes": int(get_interval_seconds(self.config.macro_context.time_interval) / 60),
                    "limit": self.config.macro_context.lookback_candles
                },
                "micro_timeframe": {
                    "interval": self.config.micro_context.time_interval,
                    "interval_minutes": int(get_interval_seconds(self.config.micro_context.time_interval) / 60),
                    "limit": self.config.micro_context.lookback_candles
                },
                "lookback_windows": {
                    "order_flow_lookback_hours": self.config.order_flow_lookback_hours,
                    "trend_intensity_lookback_hours": self.config.trend_intensity_lookback_hours,
                    "liquidation_window_hours": round((get_interval_seconds(self.config.micro_context.time_interval) * self.config.micro_context.lookback_candles) / 3600, 1)
                }
            },
            "visual_assets": charts,
            "tactical_summary": {
                "topography": self._synthesize_topographic_summary(metrics),
                "cvd_dynamics": self._analyze_cvd_dynamics(metrics)
            },
            "quantitative_metrics": metrics.__dict__
        }

    def _init_vp(self) -> VolumeProfileAnalyzer:
        cfg = self.config
        vp_cfg = VolumeProfileConfig(
            value_area_ratio=cfg.vp_value_area_width, 
            resolution_bins=cfg.vp_price_bucket_count,
            atr_period=cfg.atr_period, 
            max_high_volume_node_count=cfg.max_high_volume_node_count, 
            max_low_volume_node_count=cfg.max_low_volume_node_count,
            high_volume_node_detection_threshold=cfg.high_volume_node_detection_threshold, 
            low_volume_node_detection_threshold=cfg.low_volume_node_detection_threshold,
            min_node_distance=cfg.min_node_gap_price,
            balanced_atr_multiplier=cfg.regime_balanced_atr_multiplier
        )
        return VolumeProfileAnalyzer(config=vp_cfg)

    def _init_regime(self) -> MarketRegimeAnalyzer:
        cfg = self.config
        rg_cfg = MarketRegimeConfig(
            bollinger_window=cfg.bb_period, 
            bollinger_std_dev=cfg.bb_std_dev,
            keltner_window=cfg.kc_period, 
            keltner_multiplier=cfg.kc_multiplier,
            volume_ma_window=cfg.vol_ma_period, 
            trend_intensity_threshold=self.config.regime_trend_threshold,
            trend_lookback=self.config.trend_lookback,
            wick_skewness_period=self.config.wick_skewness_period
        )
        return MarketRegimeAnalyzer(config=rg_cfg)

    def close(self):
        """Cleanly releases network adapters."""
        if hasattr(self, '_binance'):
            self._binance.close()
