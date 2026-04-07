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
from src.utils.market_utils import parse_liquidation_data, calculate_indicator_warmup
from src.utils.logger_utils import setup_logger

# Initialize project-standard hardened logger
logger = setup_logger(__name__)

@dataclass(frozen=True)
class TimeframeConfig:
    """Encapsulates timeframe parameters for market telemetry.
    
    Attributes:
        time_interval: Binance-standard interval string (e.g., '1h', '15m').
        lookback_candles: Number of historical candles to fetch for context.
    """
    time_interval: str
    lookback_candles: int

@dataclass(frozen=True)
class MarketObserverConfig:
    """Type-safe configuration engine for the MarketObserver.
    
    Attributes:
        macro_context: High-level market topography configuration.
        micro_context: Low-level tactical execution configuration.
        vp_value_area_width: Percentage of volume included in the 'Value Area'.
        trend_intensity_threshold: Minimum intensity for trending status.
        max_tool_iterations: Safety ceiling for neural tool-looping.
    """
    macro_context: TimeframeConfig
    micro_context: TimeframeConfig
    volume_profile_area_ratio: float
    volume_profile_price_bucket_count: int
    order_flow_lookback_hours: float
    atr_period: int
    bb_period: int
    bb_std_dev: float
    kc_period: int
    kc_multiplier: float
    volume_ma_period: int
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
    trend_intensity_threshold: float
    volatility_baseline_ratio: float
    volatility_expansion_ratio: float
    volatility_extreme_ratio: float
    volume_surge_vs_ma_ratio: float
    long_short_imbalance_ratio: float
    poc_gravity_atr_distance: float
    vacuum_risk_score: float
    wick_skewness_exhaustion: float
    trend_intensity_strong: float
    min_rr_ranging: float
    min_rr_trending: float
    min_volume_participation_ratio: float
    squeeze_threshold: float
    ranging_width_atr: float
    cvd_intensity_threshold: float
    cvd_intensity_extreme: float
    funding_extreme_threshold: float
    default_structural_distance_atr: float
    max_liquidation_clusters: int
    wick_skew_fallback: float
    max_tool_iterations: int
    # Visuals (from global_config.yaml)
    volume_profile_width_ratio: float
    volume_profile_smoothing_sigma: float
    volume_profile_color: str
    volume_profile_alpha: float
    chart_main_panel_weight: int
    chart_volume_panel_weight: int
    render_dpi: int
    up_color: str
    down_color: str
    bg_color: str
    grid_color: str
    poc_color: str
    value_area_color: str
    liq_buy_color: str
    liq_sell_color: str
    current_price_color: str
    indicator_warmup_multiplier: float

    @classmethod
    def from_dict(cls, cfg: Dict[str, Any]) -> "MarketObserverConfig":
        """Factory method to transform a raw configuration dict into a type-safe object."""
        shared = cfg.get('agent_model_shared_config', {})
        sampling = cfg['analysis_window']
        topography = cfg['topography_parameters']
        regime = cfg['regime_parameters']
        
        macro = sampling['macro_context']
        micro = sampling['micro_context']
        
        # Backwards Compatibility: Handle renamed keys in historical audit reports
        min_node_gap = topography.get('min_price_gap_between_nodes', topography.get('min_node_gap_price'))
        def_struct_dist = topography.get('default_structural_distance', topography.get('default_structural_distance_atr'))
        
        volume_part_surge = regime.get('volume_surge_vs_ma_ratio', regime.get('volume_breakout_threshold'))
        min_volume_part = regime.get('min_volume_participation_ratio', regime.get('participation_volume_threshold'))
        balancing_width = regime.get('ranging_width_atr', regime.get('balanced_atr_multiplier'))

        return cls(
            indicator_warmup_multiplier=float(cfg.get('analytical', {}).get('indicator_warmup_multiplier')),
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
            
            volume_profile_area_ratio=float(topography['volume_profile_value_area_width']),
            volume_profile_price_bucket_count=int(topography['volume_profile_price_bucket_count']),
            volume_ma_period=int(topography['volume_moving_average_period']),
            max_high_volume_node_count=int(topography['max_high_volume_node_count']),
            max_low_volume_node_count=int(topography['max_low_volume_node_count']),
            high_volume_node_detection_threshold=float(topography['high_volume_node_detection_threshold']),
            low_volume_node_detection_threshold=float(topography['low_volume_node_detection_threshold']),
            min_node_gap_price=int(min_node_gap),
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
            default_structural_distance_atr=float(def_struct_dist),
            
            trend_intensity_threshold=float(regime['trend_intensity_threshold']),
            volatility_baseline_ratio=float(regime['volatility_baseline_ratio']),
            volatility_expansion_ratio=float(regime['volatility_expansion_ratio']),
            volatility_extreme_ratio=float(regime['volatility_extreme_ratio']),
            volume_surge_vs_ma_ratio=float(volume_part_surge),
            long_short_imbalance_ratio=float(regime['long_short_imbalance_ratio']),
            poc_gravity_atr_distance=float(regime['poc_gravity_atr_distance']),
            vacuum_risk_score=float(regime['vacuum_risk_score']),
            wick_skewness_exhaustion=float(regime['wick_skewness_exhaustion']),
            trend_intensity_strong=float(regime['trend_intensity_strong']),
            min_rr_ranging=float(regime['min_rr_ranging']),
            min_rr_trending=float(regime['min_rr_trending']),
            min_volume_participation_ratio=float(min_volume_part),
            squeeze_threshold=float(regime['squeeze_threshold']),
            ranging_width_atr=float(balancing_width),
            cvd_intensity_threshold=float(regime['cvd_intensity_threshold']),
            cvd_intensity_extreme=float(regime['cvd_intensity_extreme']),
            funding_extreme_threshold=float(regime['funding_extreme_threshold']),
            
            # Visuals (from global_config.yaml 'visuals' section)
            volume_profile_width_ratio=float(cfg['visuals']['volume_profile_width_ratio']),
            volume_profile_smoothing_sigma=float(cfg['visuals']['volume_profile_smoothing_sigma']),
            volume_profile_color=str(cfg['visuals']['volume_profile_color']),
            volume_profile_alpha=float(cfg['visuals']['volume_profile_alpha']),
            chart_main_panel_weight=int(cfg['visuals']['chart_main_panel_weight']),
            chart_volume_panel_weight=int(cfg['visuals']['chart_volume_panel_weight']),
            render_dpi=int(cfg['visuals']['render_dpi']),
            up_color=str(cfg['visuals']['up_color']),
            down_color=str(cfg['visuals']['down_color']),
            bg_color=str(cfg['visuals']['bg_color']),
            grid_color=str(cfg['visuals']['grid_color']),
            poc_color=str(cfg['visuals']['poc_color']),
            value_area_color=str(cfg['visuals']['value_area_color']),
            liq_buy_color=str(cfg['visuals']['liq_buy_color']),
            liq_sell_color=str(cfg['visuals']['liq_sell_color']),
            current_price_color=str(cfg['visuals']['current_price_color'])
        )

    @property
    def taker_volume_delta_lookback(self) -> int:
        """Calculates current candle count for order flow analysis."""
        secs = get_interval_seconds(self.micro_context.time_interval)
        return max(1, int(self.order_flow_lookback_hours * 3600 / secs))

    @property
    def trend_lookback(self) -> int:
        """Calculates current candle count for trend analysis."""
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
    liquidations: Optional[List[Dict[str, Any]]] = None
    funding_rate: Optional[List[Dict[str, Any]]] = None

@dataclass
class ProcessedMarketMetrics:
    """Structured container for processed topographical and tactical metrics."""
    price_dynamics: Dict[str, Any]
    structural_anchors: Dict[str, Any]
    volume_profile: Dict[str, Any]
    market_regime: Dict[str, Any]
    sentiment_signals: Dict[str, Any]

class MarketDataLoader:
    """The Telemetry Harvester.
    
    Handles high-fidelity data acquisition from exchange API endpoints, 
    ensuring synchronized snapshots across multiple timeframes.
    """
    
    def __init__(self, binance_client: BinanceFuturesClient, config: MarketObserverConfig):
        """Initializes the loader with shared exchange infrastructure."""
        self.client = binance_client
        self.config = config

    def collect(self, symbol: str, at_time: datetime) -> RawMarketData:
        """Assembles a synchronized snapshot of market datum.
        
        Args:
            symbol: Trading pair code.
            at_time: Target timestamp for the snapshot.
            
        Returns:
            A RawMarketData package containing all harvested telemetry.
        """
        ts_ms = int(at_time.timestamp() * 1000)
        cfg = self.config
        
        macro_oi_delta = self._get_interval_delta(cfg.macro_context.time_interval)
        macro_historical_ts_ms = ts_ms - int(macro_oi_delta.total_seconds() * 1000)

        micro_oi_delta = self._get_interval_delta(cfg.micro_context.time_interval)
        micro_historical_ts_ms = ts_ms - int(micro_oi_delta.total_seconds() * 1000)

        liq_lookback_ms = int(micro_oi_delta.total_seconds() * cfg.micro_context.lookback_candles * 1000)
        liq_start_ts_ms = ts_ms - liq_lookback_ms
        
        # v6.12: Dynamic funding limit to avoid hardcoded bloat
        funding_rate_limit = max(2, int(cfg.funding_rate_lookback_hours / 8) + 2)

        # v6.30: Sentiment Window Anchoring (Macro at Start of Window, Micro at Current)
        macro_ls_delta_ms = int(get_interval_seconds(cfg.macro_context.time_interval) * 1000)
        macro_ls_ts_ms = ts_ms - macro_ls_delta_ms

        return RawMarketData(
            macro_klines=self.client.fetch_historical_klines(symbol, cfg.macro_context.time_interval, cfg.macro_context.lookback_candles, endTime=ts_ms) or [],
            micro_klines=self.client.fetch_historical_klines(symbol, cfg.micro_context.time_interval, cfg.micro_context.lookback_candles, endTime=ts_ms) or [],
            macro_oi=self.client.fetch_open_interest(symbol, cfg.macro_context.time_interval, endTime=macro_historical_ts_ms),
            micro_oi=self.client.fetch_open_interest(symbol, cfg.micro_context.time_interval, endTime=micro_historical_ts_ms),
            macro_ls=self.client.fetch_long_short_ratio(symbol, cfg.macro_context.time_interval, limit=1, endTime=macro_ls_ts_ms) or [],
            micro_ls=self.client.fetch_long_short_ratio(symbol, cfg.micro_context.time_interval, limit=1, endTime=ts_ms) or [],
            current_oi=self.client.fetch_open_interest(symbol, cfg.micro_context.time_interval, endTime=ts_ms),
            liquidations=self.client.fetch_liquidations(symbol, limit=cfg.max_liquidation_events_to_fetch, startTime=liq_start_ts_ms, endTime=ts_ms),
            funding_rate=self.client.fetch_funding_rate(symbol, limit=funding_rate_limit, startTime=ts_ms - (int(cfg.funding_rate_lookback_hours) * 60 * 60 * 1000), endTime=ts_ms)
        )

    def _get_interval_delta(self, interval: str) -> timedelta:
        """Converts human interval strings to timedeltas."""
        return timedelta(seconds=get_interval_seconds(interval))

class MarketMetricsRefiner:
    """The Metric Distiller.
    
    Transforms raw telemetry into actionable topographical and tactical metrics 
    using specialized Volume Profile and Market Regime analysis.
    """
    
    def __init__(self, config: MarketObserverConfig, vp_analyzer: VolumeProfileAnalyzer, regime_analyzer: MarketRegimeAnalyzer):
        """Initializes specialized processing units for topography and dynamics."""
        self.config = config
        self.vp = vp_analyzer
        self.regime = regime_analyzer

    def refine(self, raw: RawMarketData) -> ProcessedMarketMetrics:
        """Orchestrates comprehensive metric distillation.
        
        Args:
            raw: RawMarketData package.
            
        Returns:
            A ProcessedMarketMetrics instance representing the market's current state.
        """
        m_df = self.vp.process_klines(raw.macro_klines)
        n_df = self.vp.process_klines(raw.micro_klines)
        
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
        """Calculates price velocity, wick skewness, and volatility intensity."""
        last = m_df.iloc[-1]
        h, l, c = last['high'], last['low'], last['close']
        wick_skew = (c - l) / (h - l) if (h - l) > 0 else self.config.wick_skew_fallback
        
        atr_m = m_df['atr'].iloc[-1]
        atr_n = n_df['atr'].iloc[-1]
        
        ratio = get_interval_seconds(self.config.macro_context.time_interval) / get_interval_seconds(self.config.micro_context.time_interval)
        volatility_expansion_ratio = atr_n / (atr_m / ratio) if atr_m > 0 else 1.0
        
        avg_atr_lookback = min(self.config.volatility_intensity_lookback_hours, len(m_df))
        mean_historical_atr = m_df['atr'].tail(avg_atr_lookback).mean()
        volatility_intensity_index = (atr_m / mean_historical_atr) if mean_historical_atr > 0 else 1.0
        
        return {
            "current_price": c,
            "atr_macro": atr_m,
            "atr_micro": atr_n,
            "latest_wick_skew": wick_skew,
            "volatility_expansion_ratio": volatility_expansion_ratio,
            "volatility_intensity_index": volatility_intensity_index
        }

    def _derive_anchors(self, df: pd.DataFrame, profile: Dict[str, Any]) -> Dict[str, Any]:
        """Calculates distance to structural anchors (POC/VAH/VAL) in ATR units."""
        price = df['close'].iloc[-1]
        atr = df['atr'].iloc[-1]
        return {
            "poc_dist_atr": (price - profile.get('poc', 0)) / atr if atr else 0,
            "vah_dist_atr": (price - profile.get('vah', 0)) / atr if atr else 0,
            "val_dist_atr": (price - profile.get('val', 0)) / atr if atr else 0
        }

    def _refine_topography(self, profile: Dict[str, Any], nodes: Dict[str, List], atr_macro: float, current_price: float) -> Dict[str, Any]:
        """Identifies significant volume nodes and structural state (Balanced vs Imbalanced)."""
        poc = profile.get('poc', 0)
        limit = self.config.top_structural_node_count
        all_nodes = [{**n, "type": "HVN"} for n in nodes.get('hvn', [])] + [{**n, "type": "LVN"} for n in nodes.get('lvn', [])]
        
        vah = profile.get('vah', 0)
        val = profile.get('val', 0)
        va_width = vah - val
        
        anchors_above = sorted([n for n in all_nodes if n['price'] > current_price], key=lambda x: x['price'])[:limit]
        anchors_below = sorted([n for n in all_nodes if n['price'] < current_price], key=lambda x: x['price'], reverse=True)[:limit]
        
        # Calculate tactical proximity for hard-predicate checks
        hvn_proximities = [abs(n['price'] - current_price) / atr_macro for n in all_nodes if n['type'] == "HVN"]
        lvn_proximities = [abs(n['price'] - current_price) / atr_macro for n in all_nodes if n['type'] == "LVN"]
        
        nearest_hvn_dist_atr = min(hvn_proximities) if hvn_proximities else self.config.default_structural_distance_atr
        nearest_lvn_dist_atr = min(lvn_proximities) if lvn_proximities else self.config.default_structural_distance_atr

        return {
            "poc": poc, "vah": vah, "val": val,
            "va_width_atr": va_width / atr_macro if atr_macro > 0 else 0,
            "nearest_hvn_dist_atr": nearest_hvn_dist_atr,
            "nearest_lvn_dist_atr": nearest_lvn_dist_atr,
            "anchors_above": anchors_above,
            "anchors_below": anchors_below,
            "profile_data": profile.get("profile_data", [])
        }

    def _derive_sentiment(self, raw: RawMarketData, atr_macro: float) -> Dict[str, Any]:
        """Calculates Order Flow, Open Interest delta, and Liquidation Clusters."""
        cvd_current_net = 0.0
        cvd_current_total_vol = 0.0
        cvd_prev_net = 0.0
        
        # 1. Calculate CVD Intensity using standardized volume lookback
        lookback = self.config.taker_volume_delta_lookback
        
        if len(raw.micro_klines) >= lookback:
            curr_window = raw.micro_klines[-lookback:]
            for k in curr_window:
                v, tb = float(k[5]), float(k[9])
                cvd_current_net += (tb - (v - tb))
                cvd_current_total_vol += v
            
        if len(raw.micro_klines) >= lookback * 2:
            prev_window = raw.micro_klines[-(lookback*2):-lookback]
            for k in prev_window:
                v, tb = float(k[5]), float(k[9])
                cvd_prev_net += (tb - (v - tb))
        
        cvd_intensity_ratio = cvd_current_net / (cvd_current_total_vol + 1e-9)

        cur_oi = float(raw.current_oi.get('openInterest', 0)) if raw.current_oi else 0
        def raw_oi_delta(hist):
            if not hist: return 0.0
            h_val = float(hist.get('openInterest', 0))
            return (cur_oi - h_val) / h_val if h_val > 0 else 0.0

        # v6.12: Enhanced sentiment trending
        funding_history = raw.funding_rate
        f_rate = float(funding_history[-1].get('fundingRate', 0)) if funding_history else 0.0
        f_delta = (f_rate - float(funding_history[-2].get('fundingRate', 0))) if funding_history and len(funding_history) >= 2 else 0.0
        
        return {
            "oi_nominal": cur_oi,
            "oi_delta_macro": raw_oi_delta(raw.macro_oi),
            "oi_delta_micro": raw_oi_delta(raw.micro_oi),
            "ls_ratio_macro": float(raw.macro_ls[0].get('longShortRatio', 0)) if raw.macro_ls else 0,
            "ls_ratio_micro": float(raw.micro_ls[0].get('longShortRatio', 0)) if raw.micro_ls else 0,
            "cvd_intensity_ratio": cvd_intensity_ratio,
            "cvd_net_delta": cvd_current_net,
            "cvd_total_volume": cvd_current_total_vol,
            "cvd_lookback_candles": lookback,
            "funding_rate": f_rate,
            "funding_rate_delta": f_delta,
            "liquidation_clusters": self._parse_to_clusters(raw.liquidations, atr_macro)
        }

    def _parse_to_clusters(self, liqs: Optional[List[Dict]], atr_macro: float) -> Optional[Dict[str, Any]]:
        """Groups raw liquidations into high-conviction price clusters."""
        # v6.52 Hardening: Return None specifically if API data is missing (limitation)
        # Distinguishes from [] which means 'Zero Liquidations Found' -> {}
        if liqs is None: return None
        if not liqs: return {}
        # Handle multiple possible key formats for consistency (REST vs WebSocket)
        parsed_liqs = [parse_liquidation_data(l) for l in liqs]
        prices = [p['price'] for p in parsed_liqs if p['price'] > 0]
        if not prices: return {}
        
        avg_p = sum(prices) / len(prices)
        bucket_size = atr_macro * self.config.liquidation_cluster_atr_multiplier if atr_macro > 0 else avg_p * self.config.liquidation_cluster_fallback_percentage
        
        clusters = {}
        for l in parsed_liqs:
            if l['price'] == 0: continue
            p = l['price']
            bucket = round(p / bucket_size) * bucket_size
            key = f"{bucket:.2f}"
            if key not in clusters:
                clusters[key] = {"total_qty": 0, "count": 0, "side": l['side']}
            clusters[key]["total_qty"] += l['qty']
            clusters[key]["count"] += 1
            
        sorted_clusters = sorted(clusters.items(), key=lambda x: x[1]['total_qty'], reverse=True)
        return {k: v for k, v in sorted_clusters[:self.config.max_liquidation_clusters]}

class MarketObserver:
    """The Elite Market Topographer & Data Orchestrator.
    
    Responsible for harvesting high-fidelity market datum and distilling it 
    into a physically accurate 'Forensic Map' for recursive reasoning.
    
    Attributes:
        symbol: Trading pair asset code.
        data_root: Persistence repository for forensic assets.
    """
    
    def __init__(
        self, 
        config: MarketObserverConfig, 
        symbol: str, 
        data_root: str,
        binance_client: BinanceFuturesClient,
        chart_generator: ChartGenerator
    ):
        """Initializes the observer with the full analytical stack."""
        self.symbol = symbol
        self.data_root = data_root
        self.config = config
        
        # [INFRASTRUCTURE INJECTION]
        self._binance = binance_client
        self._volume_profile_analyzer = self._init_volume_profile()
        self._regime_analyzer = self._init_regime()
        self._charting = chart_generator
        
        # v6.12 Hardening: Dynamic re-configuration of charting engine from global tokens
        self._charting.config = self._charting.config.__class__(
            liq_buy_color=self.config.liq_buy_color,
            liq_sell_color=self.config.liq_sell_color,
            volume_profile_width_ratio=self.config.volume_profile_width_ratio,
            volume_profile_smoothing_sigma=self.config.volume_profile_smoothing_sigma,
            volume_profile_color=self.config.volume_profile_color,
            volume_profile_alpha=self.config.volume_profile_alpha,
            chart_main_panel_weight=self.config.chart_main_panel_weight,
            chart_volume_panel_weight=self.config.chart_volume_panel_weight,
            render_dpi=self.config.render_dpi,
            up_color=self.config.up_color,
            down_color=self.config.down_color,
            bg_color=self.config.bg_color,
            grid_color=self.config.grid_color,
            poc_color=self.config.poc_color,
            value_area_color=self.config.value_area_color,
            current_price_color=self.config.current_price_color
        )
        
        # [MODULARIZED PROCESSING STACK]
        self.loader = MarketDataLoader(self._binance, self.config)
        self.refiner = MarketMetricsRefiner(self.config, self._volume_profile_analyzer, self._regime_analyzer)
        
        # v6.32: Passive Indicator Warmup Quality Audit
        self._validate_warmup_depth()

    def _validate_warmup_depth(self):
        """Passively audits if the configured lookback depth is sufficient for stability."""
        try:
            # Check Macro Context
            macro_warmup = calculate_indicator_warmup(
                iir_periods=[self.config.atr_period, self.config.bb_period, self.config.kc_period],
                fir_periods=[int(self.config.trend_intensity_lookback_hours)], # Base lookback
                multiplier=self.config.indicator_warmup_multiplier
            )
            if self.config.macro_context.lookback_candles < macro_warmup:
                logger.warning(
                    f"MarketObserver: Macro lookback ({self.config.macro_context.lookback_candles}) "
                    f"is below recommended warmup ({macro_warmup}). Indicator drift possible."
                )
        except Exception as e:
            logger.debug(f"Warmup audit skipped: {e}")

    def observe(self, timestamp: Optional[datetime] = None, data_root: Optional[str] = None, persist: bool = True) -> Dict[str, Any]:
        """Executes a complete market mapping cycle."""
        at_time = timestamp or get_current_utc_time()
        logger.info(f"MarketObserver: Capturing topography for {self.symbol}...")

        # 1. [FORENSIC DATA COLLECTION]
        raw = self.loader.collect(self.symbol, at_time)
        
        # 2. [QUALITY VALIDATION]
        if len(raw.macro_klines) < int(self.config.macro_context.lookback_candles * 0.9):
            logger.error("MarketObserver: Insufficient market telemetry. Aborting observation.")
            return {"error": "DATA_INTEGRITY_FAILURE"}

        # 3. [METRIC DISTILLATION]
        metrics = self.refiner.refine(raw)

        # 4. [MULTIMODAL ASSET GENERATION]
        snapshots = self._generate_snapshots(raw, metrics, data_root or self.data_root, at_time)
            
        # 5. [FORENSIC PACKAGING]
        observation = self._package_observation(metrics, snapshots, at_time)
        
        if persist:
            self._persist_observation(observation, data_root or self.data_root, at_time)
        
        return observation

    def _persist_observation(self, observation: Dict[str, Any], data_root: str, at_time: datetime):
        """Archives the market snapshot into the forensic repository."""
        try:
            obs_dir = os.path.join(data_root, "market")
            os.makedirs(obs_dir, exist_ok=True)
            
            ts_str = at_time.strftime(FILE_TIMESTAMP_FORMAT)
            json_filename = f"{self.symbol}_market_{ts_str}.json"
            json_path = os.path.join(obs_dir, json_filename)
            save_json(observation, json_path)
            
            logger.info(f"MarketObserver: Market record archived: {os.path.basename(json_path)}")
        except Exception as e:
            logger.error(f"MarketObserver: Persistence failure: {e}")

    def _generate_snapshots(self, raw: RawMarketData, metrics: ProcessedMarketMetrics, data_root: str, at_time: datetime) -> Dict[str, str]:
        """Triggers high-fidelity chart generation for Macro and Micro contexts."""
        img_dir = os.path.join(data_root, "klines")
        self._charting.storage.output_dir = img_dir 
        
        ctx = {**metrics.volume_profile, "timestamp": format_datetime(at_time, FILE_TIMESTAMP_FORMAT)}
        m_df = self._volume_profile_analyzer.process_klines(raw.macro_klines)
        n_df = self._volume_profile_analyzer.process_klines(raw.micro_klines)
        
        return {
            "macro_snapshot": self._charting.generate_chart(self.symbol, m_df, ctx, raw.liquidations, time_interval=self.config.macro_context.time_interval),
            "micro_snapshot": self._charting.generate_chart(self.symbol, n_df, ctx, raw.liquidations, time_interval=self.config.micro_context.time_interval)
        }

    def _package_observation(self, metrics: ProcessedMarketMetrics, charts: Dict[str, str], at_time: datetime) -> Dict[str, Any]:
        """Assembles the final forensic JSON bundle."""
        ts_compact = at_time.strftime(FILE_TIMESTAMP_FORMAT)
        
        # v6.25 Forensic Hardening: Slimming down the report for AI reasoning
        # We strip the raw 300-bin histogram data from the final JSON bundle 
        # while keeping the distilled anchors. This keeps session contexts lean.
        metrics_dict = {k: (v.copy() if isinstance(v, dict) else v) for k, v in metrics.__dict__.items()}
        if "volume_profile" in metrics_dict:
            metrics_dict["volume_profile"].pop("profile_data", None)
            
        return {
            "symbol": self.symbol,
            "observed_at": to_iso_zulu(at_time),
            "analytical_parameters": {
                "macro_timeframe": {
                    "interval": self.config.macro_context.time_interval,
                    "limit": self.config.macro_context.lookback_candles
                },
                "micro_timeframe": {
                    "interval": self.config.micro_context.time_interval,
                    "limit": self.config.micro_context.lookback_candles
                }
            },
            "visual_context": charts,
            "quantitative_metrics": metrics_dict
        }

    def _init_volume_profile(self) -> VolumeProfileAnalyzer:
        """Initializes the Volume Profile engine with contextual resolution."""
        cfg = self.config
        vp_cfg = VolumeProfileConfig(
            value_area_ratio=cfg.volume_profile_area_ratio, 
            resolution_bins=cfg.volume_profile_price_bucket_count,
            atr_period=cfg.atr_period, 
            max_high_volume_node_count=cfg.max_high_volume_node_count, 
            max_low_volume_node_count=cfg.max_low_volume_node_count,
            high_volume_node_detection_threshold=cfg.high_volume_node_detection_threshold, 
            low_volume_node_detection_threshold=cfg.low_volume_node_detection_threshold,
            min_node_distance=cfg.min_node_gap_price,
            ranging_width_atr=cfg.ranging_width_atr
        )
        return VolumeProfileAnalyzer(config=vp_cfg)

    def _init_regime(self) -> MarketRegimeAnalyzer:
        """Initializes the Market Regime engine for volatility and trend mapping."""
        cfg = self.config
        rg_cfg = MarketRegimeConfig(
            bollinger_window=cfg.bb_period, 
            bollinger_std_dev=cfg.bb_std_dev,
            keltner_window=cfg.kc_period, 
            keltner_multiplier=cfg.kc_multiplier,
            volume_ma_window=cfg.volume_ma_period, 
            trend_intensity_threshold=self.config.trend_intensity_threshold,
            trend_lookback=self.config.trend_lookback,
            wick_skewness_period=self.config.wick_skewness_period
        )
        return MarketRegimeAnalyzer(config=rg_cfg)

    def close(self):
        """Cleanly releases network adapters."""
        if hasattr(self, '_binance'):
            self._binance.close()
