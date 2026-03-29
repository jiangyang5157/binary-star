import os
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional, Tuple, Union

import pandas as pd
from google import genai
from google.genai import types

from src.agent.base_agent import BaseAgent
from src.infrastructure.binance.client import BinanceFuturesClient
from src.analyzer.volume_profile import VolumeProfileAnalyzer, VolumeProfileConfig
from src.analyzer.market_regime import MarketRegimeAnalyzer, MarketRegimeConfig
from src.analyzer.chart_generator import ChartGenerator
from src.utils.agent_utils import read_prompt_template, safe_format
from src.utils.datetime_utils import get_current_utc_time, to_iso_zulu, get_interval_seconds
from src.utils.path_utils import resolve_project_root
from src.utils.json_utils import convert_to_json_string, extract_json_from_text

# Initialize project-standard logger
from src.utils.logger_utils import setup_logger
logger = setup_logger(__name__)

@dataclass(frozen=True)
class TimeframeConfig:
    """Encapsulates timeframe parameters for market data fetching."""
    time_interval: str
    historical_lookback_candles: int

@dataclass(frozen=True)
class ObserverConfig:
    """Type-safe configuration for the ObserverAgent."""
    role_definition_prompt: str
    model: str
    model_temperature: float
    macro_context: TimeframeConfig
    micro_context: TimeframeConfig
    vp_value_area_width: float
    vp_price_bucket_count: int
    order_flow_lookback_hours: float
    regime_trend_threshold: float
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
    trend_intensity_duration_hours: float
    wick_skewness_period: int
    liquidation_cluster_atr_multiplier: float
    liquidation_cluster_fallback_percentage: float
    funding_rate_lookback_hours: float
    volatility_intensity_lookback: int
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

    @classmethod
    def from_dict(cls, cfg: Dict[str, Any]) -> "ObserverConfig":
        """Factory method to create config from a nested dictionary."""
        obs = cfg['observer']
        macro = obs['macro_analysis_context']
        micro = obs['micro_analysis_context']
        
        return cls(
            role_definition_prompt=str(obs['role_definition_prompt']),
            model=str(obs['model']),
            model_temperature=float(obs['model_temperature']),
            macro_context=TimeframeConfig(
                time_interval=str(macro['time_interval']), 
                historical_lookback_candles=int(macro['historical_lookback_candles'])
            ),
            micro_context=TimeframeConfig(
                time_interval=str(micro['time_interval']), 
                historical_lookback_candles=int(micro['historical_lookback_candles'])
            ),
            vp_value_area_width=float(obs['volume_profile_value_area_width']),
            vp_price_bucket_count=int(obs['volume_profile_price_bucket_count']),
            order_flow_lookback_hours=float(obs['order_flow_lookback_hours']),
            regime_trend_threshold=float(obs['regime_trend_intensity_threshold']),
            atr_period=int(obs['average_true_range_period']),
            bb_period=int(obs['bollinger_bands_period']),
            bb_std_dev=float(obs['bollinger_bands_std_dev']),
            kc_period=int(obs['keltner_channels_period']),
            kc_multiplier=float(obs['keltner_channels_multiplier']),
            vol_ma_period=int(obs['volume_moving_average_period']),
            max_liquidation_events_to_fetch=int(obs['max_liquidation_events_to_fetch']),
            max_liquidation_events_for_context=int(obs['max_liquidation_events_for_context']),
            max_high_volume_node_count=int(obs['max_high_volume_node_count']),
            max_low_volume_node_count=int(obs['max_low_volume_node_count']),
            high_volume_node_detection_threshold=float(obs['high_volume_node_detection_threshold']),
            low_volume_node_detection_threshold=float(obs['low_volume_node_detection_threshold']),
            min_node_gap_price=int(obs['min_price_gap_between_nodes']),
            top_structural_node_count=int(obs['top_structural_node_count']),
            trend_intensity_duration_hours=float(obs['trend_intensity_duration_hours']),
            wick_skewness_period=int(obs['wick_skewness_period']),
            liquidation_cluster_atr_multiplier=float(obs['liquidation_cluster_atr_multiplier']),
            liquidation_cluster_fallback_percentage=float(obs['liquidation_cluster_fallback_percentage']),
            funding_rate_lookback_hours=float(obs['funding_rate_lookback_hours']),
            volatility_intensity_lookback=int(obs['volatility_intensity_lookback']),
            regime_volatility_baseline_ratio=float(obs['regime_volatility_baseline_ratio']),
            regime_volatility_expansion_ratio=float(obs['regime_volatility_expansion_ratio']),
            regime_volatility_extreme_ratio=float(obs['regime_volatility_extreme_ratio']),
            regime_volume_breakout_threshold=float(obs['regime_volume_breakout_threshold']),
            regime_long_short_imbalance_ratio=float(obs['regime_long_short_imbalance_ratio']),
            regime_poc_gravity_atr_distance=float(obs['regime_poc_gravity_atr_distance']),
            regime_vacuum_risk_score=float(obs['regime_vacuum_risk_score']),
            regime_wick_skewness_exhaustion=float(obs['regime_wick_skewness_exhaustion']),
            regime_trend_intensity_strong=float(obs['regime_trend_intensity_strong']),
            regime_min_rr_ranging=float(obs['regime_min_rr_ranging']),
            regime_min_rr_trending=float(obs['regime_min_rr_trending'])
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
        return max(1, int(self.trend_intensity_duration_hours * 3600 / secs))

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
    volume_topography: Dict[str, Any]
    market_regime: Dict[str, Any]
    sentiment_signals: Dict[str, Any]

class MarketDataLoader:
    """Handles high-fidelity data collection from remote exchange endpoints."""
    def __init__(self, binance_client: BinanceFuturesClient, config: ObserverConfig):
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
        liq_lookback_ms = int(micro_delta.total_seconds() * cfg.micro_context.historical_lookback_candles * 1000)
        liq_start_ts_ms = ts_ms - liq_lookback_ms

        return RawMarketData(
            macro_klines=self.client.fetch_historical_klines(symbol, cfg.macro_context.time_interval, cfg.macro_context.historical_lookback_candles, endTime=ts_ms) or [],
            micro_klines=self.client.fetch_historical_klines(symbol, cfg.micro_context.time_interval, cfg.micro_context.historical_lookback_candles, endTime=ts_ms) or [],
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
    def __init__(self, config: ObserverConfig, vp_analyzer: VolumeProfileAnalyzer, regime_analyzer: MarketRegimeAnalyzer):
        self.config = config
        self.vp = vp_analyzer
        self.regime = regime_analyzer

    def refine(self, raw: RawMarketData) -> ProcessedMarketMetrics:
        """Orchestrates the refined calculation of all market dimensions."""
        m_df = self.vp.process_klines(raw.macro_klines)
        n_df = self.vp.process_klines(raw.micro_klines)
        
        # Calculate ATR-Macro here to pass down for high-fidelity clustering
        atr_macro = m_df['atr'].iloc[-1] if 'atr' in m_df.columns and not m_df.empty else 0
        
        profile = self.vp.calculate_profile(m_df)
        nodes = self.vp.find_significant_nodes(profile)
        regime_data = self.regime.analyze(m_df)
        
        return ProcessedMarketMetrics(
            price_dynamics=self._derive_price_dynamics(m_df, n_df),
            structural_anchors=self._derive_anchors(m_df, profile),
            volume_topography=self._refine_topography(profile, nodes, atr_macro),
            market_regime=regime_data,
            sentiment_signals=self._derive_sentiment(raw, atr_macro)
        )

    def _derive_price_dynamics(self, m_df: pd.DataFrame, n_df: pd.DataFrame) -> Dict[str, Any]:
        last = m_df.iloc[-1]
        h, l, c = last['high'], last['low'], last['close']
        wick_skew = (c - l) / (h - l) if (h - l) > 0 else 0.5
        
        atr_m = m_df['atr'].iloc[-1]
        atr_n = n_df['atr'].iloc[-1]
        
        # 1. Vol-Ratio (Micro vs Macro)
        ratio = get_interval_seconds(self.config.macro_context.time_interval) / get_interval_seconds(self.config.micro_context.time_interval)
        volatility_ratio = atr_n / (atr_m / ratio) if atr_m > 0 else 1.0
        
        # 2. Volatility Intensity (Current Macro ATR vs Historical Average)
        # We use a lookback from config for the average-of-average
        avg_atr_lookback = min(self.config.volatility_intensity_lookback, len(m_df))
        mean_historical_atr = m_df['atr'].tail(avg_atr_lookback).mean()
        vol_intensity = (atr_m / mean_historical_atr) if mean_historical_atr > 0 else 1.0
        
        return {
            "current_price": c,
            "atr_macro": atr_m,
            "atr_micro": atr_n,
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

    def _refine_topography(self, profile: Dict[str, Any], nodes: Dict[str, List], atr_macro: float) -> Dict[str, Any]:
        poc = profile.get('poc', 0)
        limit = self.config.top_structural_node_count
        all_nodes = [{**n, "type": "HVN"} for n in nodes.get('hvn', [])] + [{**n, "type": "LVN"} for n in nodes.get('lvn', [])]
        
        # Determine structural_state (BALANCED/IMBALANCED)
        vah = profile.get('vah', 0)
        val = profile.get('val', 0)
        va_width = vah - val
        
        # Consistent with VolumeProfileAnalyzer logic: Balanced if VA width < 2 * ATR
        state = "BALANCED" if va_width < (atr_macro * 2.0) else "IMBALANCED"
        if va_width == 0: state = "INITIALIZING"
        
        return {
            "poc": poc, "vah": vah, "val": val,
            "structural_state": state,
            "anchors_above": sorted([n for n in all_nodes if n['price'] > poc], key=lambda x: x['price'])[:limit],
            "anchors_below": sorted([n for n in all_nodes if n['price'] < poc], key=lambda x: x['price'], reverse=True)[:limit]
        }

    def _derive_sentiment(self, raw: RawMarketData, atr_macro: float = 0) -> Dict[str, Any]:
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
        if cvd_current > cvd_prev + 1.0: cvd_slope = "UPWARD"
        elif cvd_current < cvd_prev - 1.0: cvd_slope = "DOWNWARD"

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

    def _parse_liquidations_to_clusters(self, liqs: List[Dict], atr_macro: float = 0) -> Optional[Dict[str, Any]]:
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
            
        # 2. Return top 3 clusters by volume
        sorted_clusters = sorted(clusters.items(), key=lambda x: x[1]['total_qty'], reverse=True)
        return {k: v for k, v in sorted_clusters[:3]}

class SemanticSynthesizer(BaseAgent):
    """
    The Multimodal Forensic Observer.
    
    This agent synthesizes quantitative telemetry and qualitative visual assets 
    (macro/micro snapshots) into a thematic topographical report. It generates 
     the 'Single Source of Truth' used by the reasoning triad.
    """
    def __init__(self, config: ObserverConfig, ai_client: genai.Client):
        """
        Initializes the synthesizer with multimodal AI configuration.
        """
        self.config = config
        self.prompt_path = os.path.join(resolve_project_root(), config.role_definition_prompt)
        super().__init__(
            model=config.model,
            temperature=config.model_temperature,
            api_key="", # Client already provided via Dependency Injection
            ai_client=ai_client
        )

    def synthesize(self, metrics: ProcessedMarketMetrics, snapshots: Dict[str, str], at_time: datetime) -> Dict[str, Any]:
        """
        Translates raw metrics and visuals into a semantic market map.
        
        Args:
            metrics: Processed quantitative telemetry (price dynamics, volume profile, etc).
            snapshots: Dictionary mapping 'macro_snapshot' and 'micro_snapshot' to file paths.
            at_time: The timestamp of the observation.
            
        Returns:
            A structured JSON-like dictionary containing the qualitative analysis.
        """
        try:
            # Prepare metadata for prompt context
            specs = {
                "macro": {"interval": self.config.macro_context.time_interval, "limit": self.config.macro_context.historical_lookback_candles},
                "micro": {"interval": self.config.micro_context.time_interval, "limit": self.config.micro_context.historical_lookback_candles}
            }
            
            context = {
                "timestamp": to_iso_zulu(at_time),
                "macro_timeframe": json.dumps(specs["macro"]),
                "micro_timeframe": json.dumps(specs["micro"]),
                "metrics": json.dumps(metrics.__dict__)
            }
            
            prompt_text = self._prepare_prompt(self.prompt_path, **context)
            payload = self._build_payload(snapshots, prompt_text)
            
            logger.info("Observer: Synthesizing qualitative market report...")
            # Execute multimodal AI cycle via BaseAgent
            return self._execute_ai_cycle(payload, agent_name="Observer Synthesis")
            
        except Exception as e:
            logger.error(f"Synthesis failed: {e}", exc_info=True)
            return {"error": "Semantic mapping failed.", "details": str(e)}

    def _build_payload(self, snapshots: Dict[str, str], text: str) -> List[Any]:
        """
        Constructs a multimodal payload for the Gemini model.
        
        Pairs visual assets (as Part bytes) with the primary analysis instructions.
        """
        payload = []
        for label, path in [("Current Macro Snapshot", snapshots.get('macro_snapshot')), ("Current Micro Snapshot", snapshots.get('micro_snapshot'))]:
            if path and os.path.exists(path):
                payload.append(f"\n{label}")
                with open(path, 'rb') as f:
                    payload.append(types.Part.from_bytes(data=f.read(), mime_type='image/png'))
            else:
                payload.append(f"\n[SYSTEM NOTICE: Forensic visual asset '{label}' missing from storage.]")
        
        payload.append(text)
        return payload

class ObserverAgent:
    """
    Elite Market Topographer & Observer Facade.
    
    Coordinates high-fidelity telemetry collection and AI processing to provide 
    a 'Single Source of Truth' for downstream strategy agents.
    """
    def __init__(self, config_dict: Dict[str, Any], symbol: str, api_key: str, data_root: str):
        self.symbol = symbol
        self.data_root = data_root
        self.config = ObserverConfig.from_dict(config_dict)
        
        # Core Dependencies
        self._binance = BinanceFuturesClient()
        self._vp_analyzer = self._init_vp()
        self._regime_analyzer = self._init_regime()
        self._charting = ChartGenerator(output_dir=os.path.join(resolve_project_root(), data_root, "klines"))
        self._ai_client = genai.Client(api_key=api_key) if api_key else None
        
        # SRP Sub-components
        self.loader = MarketDataLoader(self._binance, self.config)
        self.refiner = MarketMetricsRefiner(self.config, self._vp_analyzer, self._regime_analyzer)
        self.synthesizer = SemanticSynthesizer(self.config, self._ai_client)

    def observe(self, timestamp: Optional[datetime] = None, data_root: Optional[str] = None) -> Dict[str, Any]:
        """Executes a full topographical observation cycle."""
        at_time = timestamp or get_current_utc_time()
        logger.info(f"Observer: Starting mapping for {self.symbol} at {at_time}")

        # 1. Data Collection
        raw = self.loader.collect(self.symbol, at_time)
        if not raw.macro_klines or not raw.micro_klines:
            return {"error": f"Insufficient data for {self.symbol}"}

        # 2. Metric Refinement
        metrics = self.refiner.refine(raw)

        # 3. Visual Assets
        snapshots = self._generate_snapshots(raw, metrics, data_root or self.data_root, at_time)

        # 4. AI Synthesis
        semantic_report = self.synthesizer.synthesize(metrics, snapshots, at_time)

        return self._package_observation(semantic_report, metrics, snapshots, at_time)

    def _generate_snapshots(self, raw: RawMarketData, metrics: ProcessedMarketMetrics, data_root: str, at_time: datetime) -> Dict[str, str]:
        img_dir = os.path.join(data_root, "klines")
        self._charting.storage.output_dir = img_dir # Direct access to manager if needed or use Facade setter
        
        ctx = {**metrics.volume_topography, "timestamp": at_time.isoformat()}
        m_df = self._vp_analyzer.process_klines(raw.macro_klines)
        n_df = self._vp_analyzer.process_klines(raw.micro_klines)
        
        return {
            "macro_snapshot": self._charting.generate_chart(self.symbol, m_df, ctx, raw.liquidations, time_interval=self.config.macro_context.time_interval),
            "micro_snapshot": self._charting.generate_chart(self.symbol, n_df, ctx, raw.liquidations, time_interval=self.config.micro_context.time_interval)
        }

    def _package_observation(self, report: Dict[str, Any], metrics: ProcessedMarketMetrics, charts: Dict[str, str], at_time: datetime) -> Dict[str, Any]:
        return {
            "symbol": self.symbol,
            "timestamp": to_iso_zulu(at_time),
            "observation_specs": {
                "macro": {
                    "interval": self.config.macro_context.time_interval,
                    "limit": self.config.macro_context.historical_lookback_candles
                },
                "micro": {
                    "interval": self.config.micro_context.time_interval,
                    "limit": self.config.micro_context.historical_lookback_candles
                },
                "logic": {
                    "order_flow_lookback_hours": self.config.order_flow_lookback_hours,
                    "trend_intensity_duration_hours": self.config.trend_intensity_duration_hours,
                    "liquidation_window_hours": round((get_interval_seconds(self.config.micro_context.time_interval) * self.config.micro_context.historical_lookback_candles) / 3600, 1)
                }
            },
            "visual_assets": charts,
            "quantitative_metrics": metrics.__dict__,
            "semantic_analysis": report
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
            min_node_distance=cfg.min_node_gap_price
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
