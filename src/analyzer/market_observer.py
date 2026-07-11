import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional

import pandas as pd

from src.infrastructure.exchange.base_client import AbstractExchangeClient
from src.infrastructure.exchange.models import KlineData, OpenInterestData, RatioData, LiquidationData, FundingRateData
from src.analyzer.volume_profile import VolumeProfileAnalyzer, VolumeProfileConfig
from src.analyzer.market_regime import MarketRegimeAnalyzer, MarketRegimeConfig
from src.analyzer.chart_generator import ChartGenerator
from src.analyzer.visual_context_summarizer import VisualContextSummarizer
from src.analyzer.liquidation_estimator import LiquidationEstimator
from src.config.sub_configs import RegimeConfig, VisualConfig
from src.utils.datetime_utils import (
    get_current_utc_time, format_datetime, FILE_TIMESTAMP_FORMAT,
    to_iso_zulu, get_interval_seconds
)
from src.utils.json_utils import save_json
from src.utils.market_utils import calculate_indicator_warmup
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
class ObserverTopographyConfig:
    """Indicator and structural-analysis parameters for MarketObserver."""

    atr_period: int
    bb_period: int
    bb_std_dev: float
    kc_period: int
    kc_multiplier: float
    volume_ma_period: int
    max_liquidation_events_to_fetch: int
    max_liquidation_clusters: int
    high_volume_node_detection_threshold: float
    low_volume_node_detection_threshold: float
    max_volume_node_count: int
    top_structural_node_count: int
    min_node_gap_atr: float
    default_structural_distance_atr: float
    wick_skew_lookback_candles: int
    wick_skew_fallback: float


@dataclass(frozen=True)
class ObserverRadarConfig:
    """Liquidation-radar parameters for MarketObserver.

    Projection distances (1/leverage) and 25x weight are physics constants
    hardcoded in LiquidationEstimator itself — no longer config knobs.
    """

    long_threshold: float
    short_threshold: float
    gaussian_sigma: float
    grid_bins: int
    grid_padding_atr: float


@dataclass(frozen=True)
class ObserverVisualConfig:
    """Chart and visualisation parameters specific to MarketObserver."""

    volume_profile_smoothing_sigma: float
    volume_profile_color: str
    volume_profile_alpha: float
    chart_main_panel_weight: int
    chart_volume_panel_weight: int
    chart_trendline_peak_count: int
    chart_trendline_window: int
    liq_max_alpha: float
    liq_min_alpha: float
    liq_legacy_alpha_factor: float
    liq_legacy_min_alpha: float
    liq_legacy_max_alpha: float


@dataclass(frozen=True)
class MarketObserverConfig:
    """Type-safe configuration engine for the MarketObserver, composed from sub-configs.

    Attributes:
        macro_context: High-level market topography configuration.
        micro_context: Low-level tactical execution configuration.
        regime: Market regime thresholds (trend, volatility, volume, CVD, funding).
        visual: Chart rendering parameters.
        max_tool_iterations: Safety ceiling for neural tool-looping.
    """
    # ── Core sub-configs ──────────────────────────────────────────────
    macro_context: TimeframeConfig
    micro_context: TimeframeConfig
    regime: RegimeConfig
    visual: VisualConfig

    # ── Grouped sub-dataclasses ───────────────────────────────────────
    topo: ObserverTopographyConfig
    radar: ObserverRadarConfig
    obs_visual: ObserverVisualConfig

    # ── Remaining flat fields (non-grouped) ───────────────────────────
    volume_profile_area_ratio: float
    cvd_micro_lookback_candles: int
    trend_intensity_macro_lookback_candles: int
    funding_rate_macro_lookback_candles: int
    volatility_intensity_macro_lookback_candles: int
    liquidation_cluster_atr_multiplier: float
    max_tool_iterations: int

    # ── Backward-compatible property accessors ─────────────────────────

    @property
    def atr_period(self) -> int: return self.topo.atr_period
    @property
    def bb_period(self) -> int: return self.topo.bb_period
    @property
    def bb_std_dev(self) -> float: return self.topo.bb_std_dev
    @property
    def kc_period(self) -> int: return self.topo.kc_period
    @property
    def kc_multiplier(self) -> float: return self.topo.kc_multiplier
    @property
    def volume_ma_period(self) -> int: return self.topo.volume_ma_period
    @property
    def max_liquidation_events_to_fetch(self) -> int: return self.topo.max_liquidation_events_to_fetch
    @property
    def max_liquidation_clusters(self) -> int: return self.topo.max_liquidation_clusters
    @property
    def high_volume_node_detection_threshold(self) -> float: return self.topo.high_volume_node_detection_threshold
    @property
    def low_volume_node_detection_threshold(self) -> float: return self.topo.low_volume_node_detection_threshold
    @property
    def max_volume_node_count(self) -> int: return self.topo.max_volume_node_count
    @property
    def top_structural_node_count(self) -> int: return self.topo.top_structural_node_count
    @property
    def min_node_gap_atr(self) -> float: return self.topo.min_node_gap_atr
    @property
    def default_structural_distance_atr(self) -> float: return self.topo.default_structural_distance_atr
    @property
    def wick_skew_lookback_candles(self) -> int: return self.topo.wick_skew_lookback_candles
    @property
    def wick_skew_fallback(self) -> float: return self.topo.wick_skew_fallback

    @property
    def liq_radar_long_threshold(self) -> float: return self.radar.long_threshold
    @property
    def liq_radar_short_threshold(self) -> float: return self.radar.short_threshold
    @property
    def liq_radar_gaussian_sigma(self) -> float: return self.radar.gaussian_sigma
    @property
    def liq_radar_grid_bins(self) -> int: return self.radar.grid_bins
    @property
    def liq_radar_grid_padding_atr(self) -> float: return self.radar.grid_padding_atr

    @property
    def volume_profile_smoothing_sigma(self) -> float: return self.obs_visual.volume_profile_smoothing_sigma
    @property
    def volume_profile_color(self) -> str: return self.obs_visual.volume_profile_color
    @property
    def volume_profile_alpha(self) -> float: return self.obs_visual.volume_profile_alpha
    @property
    def chart_main_panel_weight(self) -> int: return self.obs_visual.chart_main_panel_weight
    @property
    def chart_volume_panel_weight(self) -> int: return self.obs_visual.chart_volume_panel_weight
    @property
    def chart_trendline_peak_count(self) -> int: return self.obs_visual.chart_trendline_peak_count
    @property
    def chart_trendline_window(self) -> int: return self.obs_visual.chart_trendline_window
    @property
    def liq_max_alpha(self) -> float: return self.obs_visual.liq_max_alpha
    @property
    def liq_min_alpha(self) -> float: return self.obs_visual.liq_min_alpha
    @property
    def liq_legacy_alpha_factor(self) -> float: return self.obs_visual.liq_legacy_alpha_factor
    @property
    def liq_legacy_min_alpha(self) -> float: return self.obs_visual.liq_legacy_min_alpha
    @property
    def liq_legacy_max_alpha(self) -> float: return self.obs_visual.liq_legacy_max_alpha

    @classmethod
    def from_dict(cls, cfg: Dict[str, Any]) -> "MarketObserverConfig":
        """Factory method to transform a raw configuration dict into a type-safe object."""
        from src.config.loader import load_regime_config, load_visual_config

        llm_cfg = cfg.get('llm', {})
        sampling = cfg['analysis_window']
        topography = cfg['topography_parameters']
        regime = cfg['regime_parameters']

        macro = sampling['macro_context']
        micro = sampling['micro_context']

        min_node_gap_atr = topography['structural_nodes']['min_node_gap_atr']
        def_struct_dist = topography['sensors']['default_structural_distance_atr']

        volume_part_surge = regime['volume']['volume_surge_vs_ma_ratio']
        min_volume_part = regime['volume']['min_volume_participation_ratio']
        balancing_width = regime['volatility']['ranging_width_atr']

        import yaml as _yaml
        from src.utils.path_utils import resolve_project_root as _root
        v_path = os.path.join(_root(), "config", "visual_config.yaml")
        with open(v_path, "r") as _f:
            visuals = _yaml.safe_load(_f)

        # Unified Grouping for Profile and Trendline
        vp_cfg = visuals.get('volume_profile', {})
        ct_cfg = visuals.get('chart_trendline', {})

        return cls(
            macro_context=TimeframeConfig(
                time_interval=str(macro['time_interval']),
                lookback_candles=int(macro['lookback_candles']),
            ),
            micro_context=TimeframeConfig(
                time_interval=str(micro['time_interval']),
                lookback_candles=int(micro['lookback_candles']),
            ),
            regime=load_regime_config(cfg),
            visual=load_visual_config(cfg),

            topo=ObserverTopographyConfig(
                atr_period=int(topography['indicators']['average_true_range_period']),
                bb_period=int(topography['indicators']['bollinger_bands_period']),
                bb_std_dev=float(topography['indicators']['bollinger_bands_std_dev']),
                kc_period=int(topography['indicators']['keltner_channels_period']),
                kc_multiplier=float(topography['indicators']['keltner_channels_multiplier']),
                volume_ma_period=int(topography['indicators']['volume_moving_average_period']),
                max_liquidation_events_to_fetch=int(topography['liquidation']['max_liquidation_events_to_fetch']),
                max_liquidation_clusters=int(topography['liquidation']['max_liquidation_clusters']),
                high_volume_node_detection_threshold=float(topography['structural_nodes']['high_volume_node_detection_threshold']),
                low_volume_node_detection_threshold=float(topography['structural_nodes']['low_volume_node_detection_threshold']),
                max_volume_node_count=int(topography['structural_nodes']['max_volume_node_count']),
                top_structural_node_count=int(topography['structural_nodes']['top_structural_node_count']),
                min_node_gap_atr=float(min_node_gap_atr),
                default_structural_distance_atr=float(def_struct_dist),
                wick_skew_lookback_candles=int(topography['sensors']['wick_skew_lookback_candles']),
                wick_skew_fallback=float(topography['sensors']['wick_skew_fallback']),
            ),
            radar=ObserverRadarConfig(
                long_threshold=float(regime['liquidation_radar']['liq_radar_long_threshold']),
                short_threshold=float(regime['liquidation_radar']['liq_radar_short_threshold']),
                gaussian_sigma=float(regime['liquidation_radar']['liq_radar_gaussian_sigma']),
                grid_bins=int(regime['liquidation_radar']['liq_radar_grid_bins']),
                grid_padding_atr=float(regime['liquidation_radar']['liq_radar_grid_padding_atr']),
            ),
            obs_visual=ObserverVisualConfig(
                volume_profile_smoothing_sigma=float(vp_cfg['smoothing_sigma']),
                volume_profile_color=str(vp_cfg['color']),
                volume_profile_alpha=float(vp_cfg['alpha']),
                chart_main_panel_weight=int(visuals['chart_layout']['main_panel_weight']),
                chart_volume_panel_weight=int(visuals['chart_layout']['volume_panel_weight']),
                chart_trendline_peak_count=int(ct_cfg['peak_count']),
                chart_trendline_window=int(ct_cfg['window']),
                liq_max_alpha=float(visuals['liquidation_heatmap']['liq_max_alpha']),
                liq_min_alpha=float(visuals['liquidation_heatmap']['liq_min_alpha']),
                liq_legacy_alpha_factor=float(visuals['liquidation_heatmap']['liq_legacy_alpha_factor']),
                liq_legacy_min_alpha=float(visuals['liquidation_heatmap']['liq_legacy_min_alpha']),
                liq_legacy_max_alpha=float(visuals['liquidation_heatmap']['liq_legacy_max_alpha']),
            ),

            funding_rate_macro_lookback_candles=int(sampling['tensors']['funding_rate_macro_lookback_candles']),
            cvd_micro_lookback_candles=int(sampling['tensors']['cvd_micro_lookback_candles']),
            trend_intensity_macro_lookback_candles=int(sampling['tensors']['trend_intensity_macro_lookback_candles']),
            volatility_intensity_macro_lookback_candles=int(sampling['tensors']['volatility_intensity_macro_lookback_candles']),
            volume_profile_area_ratio=float(topography['volume_profile']['volume_profile_value_area_width']),
            liquidation_cluster_atr_multiplier=float(visuals['liquidation_heatmap']['liq_radar_atr_multiplier']),
            max_tool_iterations=int(llm_cfg['max_tool_iterations']),
        )


    @property
    def funding_rate_lookback_hours(self) -> float:
        """Reverse calculates the temporal duration of the funding lookback window."""
        secs = get_interval_seconds(self.macro_context.time_interval)
        return (self.funding_rate_macro_lookback_candles * secs) / 3600.0

    @property
    def trend_intensity_lookback_hours(self) -> float:
        """Reverse calculates the temporal duration of the trend lookback window."""
        secs = get_interval_seconds(self.macro_context.time_interval)
        return (self.trend_intensity_macro_lookback_candles * secs) / 3600.0

    @property
    def volatility_intensity_lookback_hours(self) -> float:
        """Reverse calculates the temporal duration of the volatility lookback window."""
        secs = get_interval_seconds(self.macro_context.time_interval)
        return (self.volatility_intensity_macro_lookback_candles * secs) / 3600.0

@dataclass
class RawMarketData:
    """Holds raw datum collected during an observation cycle."""
    macro_klines: List[KlineData] = field(default_factory=list)
    micro_klines: List[KlineData] = field(default_factory=list)
    macro_oi: Optional[OpenInterestData] = None
    micro_oi: Optional[OpenInterestData] = None
    macro_ls: List[RatioData] = field(default_factory=list)
    micro_ls: List[RatioData] = field(default_factory=list)
    current_oi: Optional[OpenInterestData] = None
    liquidations: Optional[List[LiquidationData]] = None
    funding_rate: Optional[List[FundingRateData]] = None
    oi_history: List[OpenInterestData] = field(default_factory=list)
    taker_ratio_history: List[RatioData] = field(default_factory=list)

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
    
    def __init__(self, exchange_client: AbstractExchangeClient, config: MarketObserverConfig):
        """Initializes the loader with shared exchange infrastructure."""
        self.client = exchange_client
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
        
        # Dynamic funding limit to avoid hardcoded bloat.
        # Binance funding interval varies per pair (4-8h). Use 4h as safe lower bound
        # so the limit covers all pairs; over-asking is harmless (Binance returns only
        # what exists), under-asking would silently drop data.
        funding_interval_hours = 4
        funding_rate_limit = max(2, int(cfg.funding_rate_lookback_hours / funding_interval_hours) + 2)

        # Sentiment Window Anchoring (Macro at Start of Window, Micro at Current)
        macro_ls_delta_ms = int(get_interval_seconds(cfg.macro_context.time_interval) * 1000)
        macro_ls_ts_ms = ts_ms - macro_ls_delta_ms

        return RawMarketData(
            macro_klines=self.client.fetch_historical_klines(symbol, cfg.macro_context.time_interval, cfg.macro_context.lookback_candles, endTime=ts_ms) or [],
            micro_klines=self.client.fetch_historical_klines(symbol, cfg.micro_context.time_interval, cfg.micro_context.lookback_candles, endTime=ts_ms) or [],
            macro_oi=(res[0] if (res := self.client.fetch_open_interest(symbol, cfg.macro_context.time_interval, endTime=macro_historical_ts_ms)) else None),
            micro_oi=(res[0] if (res := self.client.fetch_open_interest(symbol, cfg.micro_context.time_interval, endTime=micro_historical_ts_ms)) else None),
            macro_ls=self.client.fetch_long_short_ratio(symbol, cfg.macro_context.time_interval, limit=1, endTime=macro_ls_ts_ms) or [],
            micro_ls=self.client.fetch_long_short_ratio(symbol, cfg.micro_context.time_interval, limit=1, endTime=ts_ms) or [],

            current_oi=(res[0] if (res := self.client.fetch_open_interest(symbol, cfg.micro_context.time_interval, endTime=ts_ms)) else None),
            liquidations=self.client.fetch_liquidations(symbol, limit=cfg.max_liquidation_events_to_fetch, startTime=liq_start_ts_ms, endTime=ts_ms),
            funding_rate=self.client.fetch_funding_rate(symbol, limit=funding_rate_limit, startTime=ts_ms - round(cfg.funding_rate_lookback_hours * 60 * 60 * 1000), endTime=ts_ms),
            oi_history=self.client.fetch_open_interest(symbol, cfg.micro_context.time_interval, limit=cfg.micro_context.lookback_candles, endTime=ts_ms) or [],
            taker_ratio_history=self.client.fetch_taker_long_short_ratio(symbol, cfg.micro_context.time_interval, limit=cfg.micro_context.lookback_candles, endTime=ts_ms) or []
        )

    def _get_interval_delta(self, interval: str) -> timedelta:
        """Converts human interval strings to timedeltas."""
        return timedelta(seconds=get_interval_seconds(interval))

class MarketMetricsRefiner:
    """The Metric Distiller.
    
    Transforms raw telemetry into actionable topographical and tactical metrics 
    using specialized Volume Profile and Market Regime analysis.
    """
    
    def __init__(self, config: MarketObserverConfig, vp_analyzer: VolumeProfileAnalyzer, regime_analyzer: MarketRegimeAnalyzer, radar: LiquidationEstimator):
        """Initializes specialized processing units for topography and dynamics."""
        self.config = config
        self.vp = vp_analyzer
        self.regime = regime_analyzer
        self.radar = radar

    def refine(self, raw: RawMarketData) -> tuple[ProcessedMarketMetrics, 'pd.DataFrame', 'pd.DataFrame']:
        """Orchestrates comprehensive metric distillation.

        Args:
            raw: RawMarketData package.

        Returns:
            (ProcessedMarketMetrics, macro_df, micro_df) — DataFrames returned for reuse in chart generation.
        """
        m_df = self.vp.process_klines(raw.macro_klines)
        n_df = self.vp.process_klines(raw.micro_klines)
        
        atr_macro = m_df['atr'].iloc[-1] if 'atr' in m_df.columns and not m_df.empty else 0
        current_price = m_df['close'].iloc[-1] if not m_df.empty else 0
        
        profile = self.vp.calculate_profile(m_df)
        nodes = self.vp.find_significant_nodes(profile, atr=atr_macro)
        regime_data = self.regime.analyze(m_df)
        
        atr_micro = n_df['atr'].iloc[-1] if 'atr' in n_df.columns and not n_df.empty else 0

        return (
            ProcessedMarketMetrics(
                price_dynamics=self._derive_price_dynamics(m_df, n_df),
                structural_anchors=self._derive_anchors(m_df, profile),
                volume_profile=self._refine_topography(profile, nodes, atr_macro, current_price),
                market_regime=regime_data,
                sentiment_signals=self._derive_sentiment(raw, atr_macro, atr_micro, current_price)
            ),
            m_df,
            n_df,
        )

    def _derive_price_dynamics(self, m_df: pd.DataFrame, n_df: pd.DataFrame) -> Dict[str, Any]:
        """Calculates price velocity, wick skewness, and volatility intensity."""
        last = m_df.iloc[-1]
        h, l, c = last['high'], last['low'], last['close']
        wick_skew = (c - l) / (h - l) if (h - l) > 0 else self.config.wick_skew_fallback
        
        atr_m = m_df['atr'].iloc[-1]
        if pd.isna(atr_m):
            atr_m = 0.0
        atr_n = n_df['atr'].iloc[-1]
        if pd.isna(atr_n):
            atr_n = 0.0
        
        ratio = get_interval_seconds(self.config.macro_context.time_interval) / get_interval_seconds(self.config.micro_context.time_interval)
        volatility_expansion_index = atr_n / (atr_m / (ratio ** 0.5)) if atr_m > 0 else 1.0
        
        avg_atr_lookback_candles = min(self.config.volatility_intensity_macro_lookback_candles, len(m_df))
        mean_historical_atr = m_df['atr'].tail(avg_atr_lookback_candles).mean()
        volatility_intensity_index = (atr_m / mean_historical_atr) if mean_historical_atr > 0 else 1.0
        
        # Physics Engine Correction - Normalized Velocity (ATR/Bar)
        # Calculates the actual physical speed of the trend for Zero-Entropy time projections.
        trend_lookback = self.config.trend_intensity_macro_lookback_candles
        normalized_velocity = 0.0
        if len(m_df) >= trend_lookback + 1 and atr_m > 0 and trend_lookback > 0:
            net_displacement = abs(m_df['close'].iloc[-1] - m_df['close'].iloc[-(trend_lookback + 1)])
            # Velocity = Total ATRs moved / Total candles
            normalized_velocity = (net_displacement / atr_m) / trend_lookback

        return {
            "current_price": c,
            "atr_macro": atr_m,
            "atr_micro": atr_n,
            "wick_skew_instant": wick_skew,
            "volatility_expansion_index": volatility_expansion_index,
            "volatility_intensity_index": volatility_intensity_index,
            "normalized_velocity": normalized_velocity
        }



    def _derive_anchors(self, df: pd.DataFrame, profile: Dict[str, Any]) -> Dict[str, Any]:
        """Calculates distance to structural anchors (POC/VAH/VAL) in ATR units."""
        price = df['close'].iloc[-1]
        atr = df['atr'].iloc[-1]
        # Guard both zero AND NaN — bool(NaN) is True, so `if atr` alone misses NaN
        valid = bool(atr) and not pd.isna(atr)
        return {
            "poc_dist_atr": (price - profile.get('poc', 0)) / atr if valid else 0,
            "vah_dist_atr": (price - profile.get('vah', 0)) / atr if valid else 0,
            "val_dist_atr": (price - profile.get('val', 0)) / atr if valid else 0
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
        if atr_macro <= 0:
            nearest_hvn_dist_atr = self.config.default_structural_distance_atr
            nearest_lvn_dist_atr = self.config.default_structural_distance_atr
        else:
            hvn_proximities = [abs(n['price'] - current_price) / atr_macro for n in all_nodes if n['type'] == "HVN"]
            lvn_proximities = [abs(n['price'] - current_price) / atr_macro for n in all_nodes if n['type'] == "LVN"]
            nearest_hvn_dist_atr = min(hvn_proximities) if hvn_proximities else self.config.default_structural_distance_atr
            nearest_lvn_dist_atr = min(lvn_proximities) if lvn_proximities else self.config.default_structural_distance_atr

        return {
            "poc": poc, "vah": vah, "val": val,
            "volume_span_atr": va_width / atr_macro if atr_macro > 0 else 0,
            "nearest_hvn_dist_atr": nearest_hvn_dist_atr,
            "nearest_lvn_dist_atr": nearest_lvn_dist_atr,
            "anchors_above": anchors_above,
            "anchors_below": anchors_below,
            "profile_data": profile.get("profile_data", [])
        }

    def _derive_sentiment(self, raw: RawMarketData, atr_macro: float, atr_micro: float, current_price: float) -> Dict[str, Any]:
        """Calculates Order Flow, Open Interest delta, and Liquidation Clusters."""
        cvd_vol_delta = 0.0
        cvd_total_vol = 0.0
        
        # 1. Calculate CVD Intensity using standardized volume lookback candles
        lookback_candles = self.config.cvd_micro_lookback_candles
        
        if len(raw.micro_klines) >= lookback_candles:
            curr_window = raw.micro_klines[-lookback_candles:]
            for k in curr_window:
                v = k.volume
                tb = k.taker_buy_base
                if tb is not None:
                    cvd_vol_delta += (tb - (v - tb))
                cvd_total_vol += v
            
        cvd_intensity_ratio = cvd_vol_delta / (cvd_total_vol + 1e-9)

        # 2. Calculate avg trade size (large-player activity proxy)
        avg_trade_size = 0.0
        trade_count = 0
        if len(raw.micro_klines) >= lookback_candles:
            curr_window = raw.micro_klines[-lookback_candles:]
            total_trades = sum(
                k.trades for k in curr_window if k.trades is not None
            )
            if total_trades > 0 and cvd_total_vol > 0:
                avg_trade_size = cvd_total_vol / total_trades
                trade_count = total_trades

        cur_oi = raw.current_oi.open_interest if raw.current_oi else 0.0
        def raw_oi_delta(hist):
            if not hist: return 0.0
            h_val = hist.open_interest
            return (cur_oi - h_val) / h_val if h_val > 0 else 0.0

        # Enhanced sentiment trending
        funding_history = raw.funding_rate
        f_rate = funding_history[-1].funding_rate if funding_history else 0.0
        f_delta = (f_rate - funding_history[-2].funding_rate) if funding_history and len(funding_history) >= 2 else 0.0
        
        return {
            "oi_nominal": cur_oi,
            "oi_delta_macro": raw_oi_delta(raw.macro_oi),
            "oi_delta_micro": raw_oi_delta(raw.micro_oi),
            "ls_ratio_macro": raw.macro_ls[0].long_short_ratio if raw.macro_ls else 0.0,
            "ls_ratio_micro": raw.micro_ls[0].long_short_ratio if raw.micro_ls else 0.0,
            "cvd_intensity_ratio": cvd_intensity_ratio,
            "cvd_volume_delta": cvd_vol_delta,
            "cvd_total_volume": cvd_total_vol,
            "cvd_lookback_candles": lookback_candles,
            "avg_trade_size": avg_trade_size,
            "trade_count": trade_count,
            "funding_rate": f_rate,
            "funding_rate_delta": f_delta,
            "funding_rate_lookback_candles": self.config.funding_rate_macro_lookback_candles,
            "liquidation_clusters": self.radar.synthesize_clusters(
                raw.micro_klines, 
                raw.oi_history, 
                raw.taker_ratio_history,
                current_price=current_price,
                atr=atr_micro
            )
        }


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
        exchange_client: AbstractExchangeClient,
        chart_generator: ChartGenerator
    ):
        """Initializes the observer with the full analytical stack."""
        self.symbol = symbol
        self.data_root = data_root
        self.config = config
        
        # [INFRASTRUCTURE INJECTION]
        self._exchange = exchange_client
        self._volume_profile_analyzer = self._init_volume_profile()
        self._regime_analyzer = self._init_regime()
        self._charting = chart_generator
        self._summarizer = VisualContextSummarizer()

        # Hardening: Dynamic re-configuration of charting engine from global tokens
        self._charting.config = self._charting.config.__class__(
            up_color=self.config.visual.up_color,
            down_color=self.config.visual.down_color,
            bg_color=self.config.visual.bg_color,
            poc_color=self.config.visual.poc_color,
            vah_val_color=self.config.visual.vah_val_color,
            current_price_color=self.config.visual.current_price_color,
            volume_profile_width_ratio=self.config.visual.volume_profile_width_ratio,
            volume_profile_smoothing_sigma=self.config.volume_profile_smoothing_sigma,
            volume_profile_color=self.config.volume_profile_color,
            volume_profile_alpha=self.config.volume_profile_alpha,
            chart_main_panel_weight=self.config.chart_main_panel_weight,
            chart_volume_panel_weight=self.config.chart_volume_panel_weight,
            render_dpi=self.config.visual.render_dpi,
            liquidation_cluster_atr_multiplier=self.config.liquidation_cluster_atr_multiplier,
            liq_max_alpha=self.config.liq_max_alpha,
            liq_min_alpha=self.config.liq_min_alpha,
            liq_legacy_alpha_factor=self.config.liq_legacy_alpha_factor,
            liq_legacy_min_alpha=self.config.liq_legacy_min_alpha,
            liq_legacy_max_alpha=self.config.liq_legacy_max_alpha,
            chart_trendline_peak_count=self.config.chart_trendline_peak_count,
            chart_trendline_window=self.config.chart_trendline_window
        )

        # [MODULARIZED PROCESSING STACK]
        self.radar = LiquidationEstimator(
            volume_moving_average_period=self.config.volume_ma_period,
            volume_surge_vs_ma_ratio=self.config.regime.volume_surge_vs_ma_ratio,
            max_liquidation_clusters=self.config.max_liquidation_clusters,
            long_taker_threshold=self.config.liq_radar_long_threshold,
            short_taker_threshold=self.config.liq_radar_short_threshold,
            gaussian_sigma=self.config.liq_radar_gaussian_sigma,
            grid_bins=self.config.liq_radar_grid_bins,
            grid_padding_atr=self.config.liq_radar_grid_padding_atr,
        )
        self.loader = MarketDataLoader(self._exchange, self.config)
        self.refiner = MarketMetricsRefiner(self.config, self._volume_profile_analyzer, self._regime_analyzer, self.radar)
        
        # Passive Indicator Warmup Quality Audit
        self._validate_warmup_depth()

    def _validate_warmup_depth(self):
        """Passively audits if the configured lookback depth is sufficient for stability."""
        try:
            # Check Macro Context
            macro_warmup = calculate_indicator_warmup(
                iir_periods=[self.config.atr_period, self.config.bb_period, self.config.kc_period],
                fir_periods=[self.config.trend_intensity_macro_lookback_candles],
            )
            if self.config.macro_context.lookback_candles < macro_warmup:
                logger.warning(
                    f"lookback ({self.config.macro_context.lookback_candles}) "
                    f"below recommended warmup ({macro_warmup}). Possible indicator drift."
                )
        except Exception as e:
            logger.warning(f"warmup audit skipped | error={e}")

    def observe(self, timestamp: Optional[datetime] = None, data_root: Optional[str] = None, persist: bool = True,
                progress_callback=None) -> Dict[str, Any]:
        """Executes a complete market mapping cycle.

        Args:
            progress_callback: Optional fn(stage, activity) for progress reporting.
        """
        at_time = timestamp or get_current_utc_time()
        logger.info(f"[{self.symbol}] capturing topography")

        # 1. [FORENSIC DATA COLLECTION]
        raw = self.loader.collect(self.symbol, at_time)
        
        # 2. [QUALITY VALIDATION]
        if len(raw.macro_klines) < int(self.config.macro_context.lookback_candles * 0.9):
            logger.error(f"[{self.symbol}] insufficient telemetry — aborting")
            return {"error": "DATA_INTEGRITY_FAILURE"}

        # 3. [METRIC DISTILLATION]
        if progress_callback:
            progress_callback(stage=1, activity="Computing volatility indicators…")
        metrics, m_df, n_df = self.refiner.refine(raw)

        # 4. [MULTIMODAL ASSET GENERATION]
        if progress_callback:
            progress_callback(stage=1, activity="Rendering charts…")
        snapshots = self._generate_snapshots(raw, metrics, m_df, n_df, data_root or self.data_root, at_time)

        # 5. [FORENSIC PACKAGING]
        observation = self._package_observation(metrics, snapshots, at_time)

        if progress_callback:
            macro_count = len(raw.macro_klines) if hasattr(raw, 'macro_klines') else 0
            micro_count = len(raw.micro_klines) if hasattr(raw, 'micro_klines') else 0
            macro_interval = self.config.macro_context.time_interval
            micro_interval = self.config.micro_context.time_interval
            total = macro_count + micro_count
            progress_callback(
                stage=1,
                activity=f"Data collection done · {total} klines ({macro_count} × {macro_interval} + {micro_count} × {micro_interval})",
            )

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
            
            logger.info(f"[{self.symbol}] market record archived | file={os.path.basename(json_path)}")
        except Exception as e:
            logger.error(f"persistence failure | error={e}")

    def _generate_snapshots(self, raw: RawMarketData, metrics: ProcessedMarketMetrics,
                            m_df: 'pd.DataFrame', n_df: 'pd.DataFrame',
                            data_root: str, at_time: datetime) -> Dict[str, str]:
        """Triggers high-fidelity chart generation and text summaries for Macro and Micro contexts."""
        img_dir = os.path.join(data_root, "klines")
        self._charting.storage.output_dir = img_dir

        ctx = {**metrics.volume_profile, "timestamp": format_datetime(at_time, FILE_TIMESTAMP_FORMAT)}
        liq_clusters = metrics.sentiment_signals.get("liquidation_clusters")
        atr_macro = metrics.price_dynamics['atr_macro']

        # Macro
        macro_png = self._charting.generate_chart(
            self.symbol, m_df, ctx, liq_clusters,
            time_interval=self.config.macro_context.time_interval,
            atr=atr_macro,
        )
        macro_md = self._write_summary(
            self.symbol, m_df, ctx, liq_clusters,
            time_interval=self.config.macro_context.time_interval,
            atr=atr_macro, output_dir=img_dir,
        )

        # Micro
        micro_png = self._charting.generate_chart(
            self.symbol, n_df, ctx, liq_clusters,
            time_interval=self.config.micro_context.time_interval,
            atr=atr_macro,
        )
        micro_md = self._write_summary(
            self.symbol, n_df, ctx, liq_clusters,
            time_interval=self.config.micro_context.time_interval,
            atr=atr_macro, output_dir=img_dir,
        )

        return {
            "macro_snapshot": macro_png,
            "micro_snapshot": micro_png,
            "macro_snapshot_summary": macro_md,
            "micro_snapshot_summary": micro_md,
        }

    def _write_summary(self, symbol: str, df: 'pd.DataFrame',
                       profile_data: Dict[str, Any],
                       liquidations, time_interval: str,
                       atr: float, output_dir: str) -> str:
        """Generate visual context summary .md file and return its path."""
        os.makedirs(output_dir, exist_ok=True)
        # Derive .md path from same naming convention as .png
        from src.utils.datetime_utils import format_timestamp_for_filename
        ts = profile_data.get("timestamp", "")
        ts_readable = format_timestamp_for_filename(ts)
        filename = f"{symbol}_klines_{time_interval}_{ts_readable}.md"
        filepath = os.path.join(output_dir, filename)

        text = self._summarizer.generate(
            symbol=symbol, df=df, profile_data=profile_data,
            liquidations=liquidations, time_interval=time_interval, atr=atr,
        )
        with open(filepath, 'w') as f:
            f.write(text)

        logger.info(f"[{symbol}] visual summary written | interval={time_interval} | file={filepath}")
        return filepath

    def _package_observation(self, metrics: ProcessedMarketMetrics, charts: Dict[str, str], at_time: datetime) -> Dict[str, Any]:
        """Assembles the final forensic JSON bundle."""
        ts_compact = at_time.strftime(FILE_TIMESTAMP_FORMAT)
        
        # Forensic Hardening: Slimming down the report for AI reasoning
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
            atr_period=cfg.atr_period,
            max_volume_node_count=cfg.max_volume_node_count,
            high_volume_node_detection_threshold=cfg.high_volume_node_detection_threshold,
            low_volume_node_detection_threshold=cfg.low_volume_node_detection_threshold,
            min_node_gap_atr=cfg.min_node_gap_atr,
            ranging_width_atr=cfg.regime.ranging_width_atr
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
            trend_intensity_threshold=cfg.regime.trend_intensity_threshold,
            trend_lookback_candles=cfg.trend_intensity_macro_lookback_candles,
            wick_skew_lookback_candles=cfg.wick_skew_lookback_candles
        )
        return MarketRegimeAnalyzer(config=rg_cfg)

    def close(self):
        """Cleanly releases network adapters."""
        if hasattr(self, '_exchange'):
            self._exchange.close()
