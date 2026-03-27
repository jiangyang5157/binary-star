import os
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional, Tuple, Union

import pandas as pd
from google import genai
from google.genai import types

from src.infrastructure.binance.client import BinanceFuturesClient
from src.analyzer.volume_profile import VolumeProfileAnalyzer, VolumeProfileConfig
from src.analyzer.market_regime import MarketRegimeAnalyzer, MarketRegimeConfig
from src.analyzer.chart_generator import ChartGenerator
from src.utils.agent_utils import read_prompt_template, safe_format
from src.utils.datetime_utils import (
    format_datetime, get_current_utc_time, to_iso_zulu, get_interval_seconds
)
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
    temperature: float
    macro_context: TimeframeConfig
    micro_context: TimeframeConfig
    vp_value_area_width: float
    vp_price_buckets_count: int
    taker_vol_delta_lookback: int
    regime_trend_threshold: float
    atr_period: int
    bb_period: int
    bb_std_dev: float
    kc_period: int
    kc_multiplier: float
    vol_ma_period: int
    max_liq_to_fetch: int
    max_liq_for_ai: int
    hvn_count: int
    lvn_count: int
    hvn_sensitivity: float
    lvn_sensitivity: float
    min_node_gap_price: int
    top_levels_to_report: int
    funding_rate_limit: int
    trend_intensity_lookback: int
    wick_skewness_period: int
    liq_cluster_atr_multiplier: float
    liq_cluster_fallback_pct: float

    @classmethod
    def from_dict(cls, cfg: Dict[str, Any]) -> "ObserverConfig":
        """Factory method to create config from a nested dictionary."""
        obs = cfg['observer']
        macro = obs['macro_analysis_context']
        micro = obs['micro_analysis_context']
        
        return cls(
            role_definition_prompt=str(obs['role_definition_prompt']),
            model=str(obs['model']),
            temperature=float(obs['temperature']),
            macro_context=TimeframeConfig(
                time_interval=str(macro['time_interval']), 
                historical_lookback_candles=int(macro['historical_lookback_candles'])
            ),
            micro_context=TimeframeConfig(
                time_interval=str(micro['time_interval']), 
                historical_lookback_candles=int(micro['historical_lookback_candles'])
            ),
            vp_value_area_width=float(obs['volume_profile_value_area_width']),
            vp_price_buckets_count=int(obs['volume_profile_price_buckets_count']),
            taker_vol_delta_lookback=int(obs['taker_volume_delta_lookback_period']),
            regime_trend_threshold=float(obs['market_regime_trend_strength_threshold']),
            atr_period=int(obs['average_true_range_period']),
            bb_period=int(obs['bollinger_bands_period']),
            bb_std_dev=float(obs['bollinger_bands_std_dev']),
            kc_period=int(obs['keltner_channels_period']),
            kc_multiplier=float(obs['keltner_channels_multiplier']),
            vol_ma_period=int(obs['volume_moving_average_period']),
            max_liq_to_fetch=int(obs['max_liquidation_events_to_fetch']),
            max_liq_for_ai=int(obs['max_liquidation_events_for_ai_context']),
            hvn_count=int(obs['high_volume_peak_count']),
            lvn_count=int(obs['low_volume_valley_count']),
            hvn_sensitivity=float(obs['high_volume_peak_sensitivity']),
            lvn_sensitivity=float(obs['low_volume_valley_sensitivity']),
            min_node_gap_price=int(obs['min_price_gap_between_nodes']),
            top_levels_to_report=int(obs['top_structural_levels_to_report']),
            funding_rate_limit=int(obs['funding_rate_history_limit']),
            trend_intensity_lookback=int(obs['trend_intensity_lookback']),
            wick_skewness_period=int(obs['wick_skewness_period']),
            liq_cluster_atr_multiplier=float(obs['liq_cluster_atr_multiplier']),
            liq_cluster_fallback_pct=float(obs['liq_cluster_fallback_pct'])
        )

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
            liquidations=self.client.fetch_liquidations(symbol, limit=cfg.max_liq_to_fetch, startTime=liq_start_ts_ms, endTime=ts_ms) or [],
            funding_rate=self.client.fetch_funding_rate(symbol, limit=cfg.funding_rate_limit, startTime=liq_start_ts_ms, endTime=ts_ms) or []
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
        vol_ratio = atr_n / (atr_m / ratio) if atr_m > 0 else 1.0
        
        # 2. Vol-of-Vol (Current Macro ATR vs Historical Average)
        # We use a lookback of 24 for the average-of-average
        avg_atr_lookback = min(24, len(m_df))
        mean_historical_atr = m_df['atr'].tail(avg_atr_lookback).mean()
        atr_rel_pct = (atr_m / mean_historical_atr) if mean_historical_atr > 0 else 1.0
        
        return {
            "current_price": c,
            "atr_macro": atr_m,
            "atr_micro": atr_n,
            "vol_ratio": f"{vol_ratio:.2f}",
            "latest_wick_skew": f"{wick_skew:.2f}",
            "vol_of_vol": f"{atr_rel_pct:.2f}" # > 1.0 means current volatility is expanding beyond its own average
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
        limit = self.config.top_levels_to_report
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
            "ls_ratio_macro": raw.macro_ls[0].get('longShortRatio') if raw.macro_ls else None,
            "ls_ratio_micro": raw.micro_ls[0].get('longShortRatio') if raw.micro_ls else None,
            "net_taker_delta": f"{cvd_current:.4f}",
            "cvd_trend": cvd_slope,
            "funding_rate": raw.funding_rate[0].get('fundingRate') if raw.funding_rate else None,
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
            bucket_size = atr_macro * self.config.liq_cluster_atr_multiplier
        else:
            # Fallback to % of price if ATR is missing (e.g. 0.5%)
            bucket_size = avg_p * self.config.liq_cluster_fallback_pct
        
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

class SemanticSynthesizer:
    """Orchestrates AI multi-modal synthesis to generate qualitative insights."""
    def __init__(self, config: ObserverConfig, ai_client: genai.Client):
        self.config = config
        self.client = ai_client
        self.prompt_path = os.path.join(resolve_project_root(), config.role_definition_prompt)

    def synthesize(self, metrics: ProcessedMarketMetrics, snapshots: Dict[str, str], at_time: datetime) -> Dict[str, Any]:
        """Translates metrics and visuals into a thematic topographical report."""
        try:
            prompt_tpl = read_prompt_template(self.prompt_path)
            
            # Enrich specs for both report and semantic analysis
            specs = {
                "macro": {"interval": self.config.macro_context.time_interval, "limit": self.config.macro_context.historical_lookback_candles},
                "micro": {"interval": self.config.micro_context.time_interval, "limit": self.config.micro_context.historical_lookback_candles}
            }
            
            input_text = safe_format(
                prompt_tpl,
                timestamp=format_datetime(at_time),
                macro_timeframe=convert_to_json_string(specs["macro"]),
                micro_timeframe=convert_to_json_string(specs["micro"]),
                metrics=convert_to_json_string(metrics.__dict__)
            )
            
            payload = self._build_payload(snapshots, input_text)
            resp = self.client.models.generate_content(
                model=self.config.model,
                contents=payload,
                config=types.GenerateContentConfig(temperature=self.config.temperature, response_mime_type="application/json")
            )

            report = extract_json_from_text(resp.text)
            if report is None:
                logger.error(f"Observer Synthesis: Failed to parse JSON from response: {resp.text}")
                return {"error": "JSON_PARSE_FAILURE", "raw_response": resp.text}
            return self._apply_schema_defaults(report)
        except Exception as e:
            logger.error(f"Synthesis failed: {e}", exc_info=True)
            return {"error": "Semantic mapping failed."}

    def _build_payload(self, snapshots: Dict[str, str], text: str) -> List[Any]:
        payload = []
        for label, path in [("MACRO", snapshots.get('macro_snapshot')), ("MICRO", snapshots.get('micro_snapshot'))]:
            if path and os.path.exists(path):
                payload.append(f"[VISUAL PROOF: {label}]")
                with open(path, 'rb') as f:
                    payload.append(types.Part.from_bytes(data=f.read(), mime_type='image/png'))
        payload.append(text)
        return payload

    def _apply_schema_defaults(self, report: Dict[str, Any]) -> Dict[str, Any]:
        """Passes through the report as-is, ensuring no hardcoded constraint on keys."""
        return report

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
                }
            },
            "visual_assets": charts,
            "quantitative_metrics": metrics.__dict__,
            "semantic_analysis": report
        }

    def _init_vp(self) -> VolumeProfileAnalyzer:
        cfg = self.config
        vp_cfg = VolumeProfileConfig(
            value_area_ratio=cfg.vp_value_area_width, resolution_bins=cfg.vp_price_buckets_count,
            atr_period=cfg.atr_period, max_hvn_nodes=cfg.hvn_count, max_lvn_nodes=cfg.lvn_count,
            hvn_sensitivity=cfg.hvn_sensitivity, lvn_sensitivity=cfg.lvn_sensitivity,
            min_node_distance=cfg.min_node_gap_price
        )
        return VolumeProfileAnalyzer(config=vp_cfg)

    def _init_regime(self) -> MarketRegimeAnalyzer:
        cfg = self.config
        rg_cfg = MarketRegimeConfig(
            bollinger_window=cfg.bb_period, bollinger_std_dev=cfg.bb_std_dev,
            keltner_window=cfg.kc_period, keltner_multiplier=cfg.kc_multiplier,
            volume_ma_window=cfg.vol_ma_period, trend_threshold=cfg.regime_trend_threshold,
            trend_intensity_lookback=cfg.trend_intensity_lookback,
            wick_skewness_period=cfg.wick_skewness_period
        )
        return MarketRegimeAnalyzer(config=rg_cfg)

    def close(self):
        """Cleanly releases network adapters."""
        if hasattr(self, '_binance'):
            self._binance.close()
