from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional, Tuple, Union
import os
import json
import logging
import pandas as pd

from google import genai
from google.genai import types

from src.data.remote.binance_client import BinanceFuturesClient
from src.analyzer.volume_profile import VolumeProfileAnalyzer, VolumeProfileConfig
from src.analyzer.market_regime import MarketRegimeAnalyzer, MarketRegimeConfig
from src.analyzer.chart_generator import ChartGenerator
from src.utils.agent_utils import read_prompt_template
from src.utils.datetime_utils import format_datetime, get_utc_now
from src.utils.path_utils import resolve_project_root
from src.utils.json_utils import to_json

logger = logging.getLogger(__name__)

@dataclass(frozen=True)
class TimeframeConfig:
    """Encapsulates timeframe parameters for market data fetching."""
    time_interval: str
    historical_lookback_candles: int

@dataclass(frozen=True)
class ObserverConfig:
    """Type-safe configuration for the ObserverAgent with AI-friendly verbose keys."""
    role_definition_prompt: str
    model: str
    temperature: float
    macro_analysis_context: TimeframeConfig
    micro_analysis_context: TimeframeConfig
    volume_profile_value_area_width: float
    volume_profile_price_buckets_count: int
    taker_volume_delta_lookback_period: int
    market_regime_trend_strength_threshold: float
    average_true_range_period: int
    bollinger_bands_period: int
    bollinger_bands_std_dev: float
    keltner_channels_period: int
    keltner_channels_multiplier: float
    volume_moving_average_period: int
    max_liquidation_events_to_fetch: int
    max_liquidation_events_for_ai_context: int
    high_volume_peak_count: int
    low_volume_valley_count: int
    high_volume_peak_sensitivity: float
    low_volume_valley_sensitivity: float
    min_price_gap_between_nodes: int
    top_structural_levels_to_report: int

    @classmethod
    def from_dict(cls, cfg: Dict[str, Any]) -> "ObserverConfig":
        """Factory method to create config from a dictionary with verbose type casting."""
        obs = cfg['observer']
        macro = obs['macro_analysis_context']
        micro = obs['micro_analysis_context']
        
        return cls(
            role_definition_prompt=str(obs['role_definition_prompt']),
            model=str(obs['model']),
            temperature=float(obs['temperature']),
            macro_analysis_context=TimeframeConfig(
                time_interval=str(macro['time_interval']), 
                historical_lookback_candles=int(macro['historical_lookback_candles'])
            ),
            micro_analysis_context=TimeframeConfig(
                time_interval=str(micro['time_interval']), 
                historical_lookback_candles=int(micro['historical_lookback_candles'])
            ),
            volume_profile_value_area_width=float(obs['volume_profile_value_area_width']),
            volume_profile_price_buckets_count=int(obs['volume_profile_price_buckets_count']),
            taker_volume_delta_lookback_period=int(obs['taker_volume_delta_lookback_period']),
            market_regime_trend_strength_threshold=float(obs['market_regime_trend_strength_threshold']),
            average_true_range_period=int(obs['average_true_range_period']),
            bollinger_bands_period=int(obs['bollinger_bands_period']),
            bollinger_bands_std_dev=float(obs['bollinger_bands_std_dev']),
            keltner_channels_period=int(obs['keltner_channels_period']),
            keltner_channels_multiplier=float(obs['keltner_channels_multiplier']),
            volume_moving_average_period=int(obs['volume_moving_average_period']),
            max_liquidation_events_to_fetch=int(obs['max_liquidation_events_to_fetch']),
            max_liquidation_events_for_ai_context=int(obs['max_liquidation_events_for_ai_context']),
            high_volume_peak_count=int(obs['high_volume_peak_count']),
            low_volume_valley_count=int(obs['low_volume_valley_count']),
            high_volume_peak_sensitivity=float(obs['high_volume_peak_sensitivity']),
            low_volume_valley_sensitivity=float(obs['low_volume_valley_sensitivity']),
            min_price_gap_between_nodes=int(obs['min_price_gap_between_nodes']),
            top_structural_levels_to_report=int(obs['top_structural_levels_to_report'])
        )

@dataclass
class MarketDataContainer:
    """Holds raw market data collected during an observation cycle."""
    macro_klines: List[List[Any]] = field(default_factory=list)
    micro_klines: List[List[Any]] = field(default_factory=list)
    macro_oi_history: Optional[Dict[str, Any]] = None
    micro_oi_history: Optional[Dict[str, Any]] = None
    macro_ls_ratio: List[Dict[str, Any]] = field(default_factory=list)
    micro_ls_ratio: List[Dict[str, Any]] = field(default_factory=list)
    current_oi: Optional[Dict[str, Any]] = None
    liquidations: List[Dict[str, Any]] = field(default_factory=list)

@dataclass
class MarketMetricsContainer:
    """Container for all calculated market indicators and profiles."""
    price: Dict[str, Any]
    structural_proximity: Dict[str, Any]
    volume_profile: Dict[str, Any]
    regime: Dict[str, Any]
    sentiment: Dict[str, Any]

class ObserverAgent:
    """
    Elite Market Topographer & Data Service.
    
    Orchestrates high-fidelity data collection, technical analysis, and multi-modal
    AI processing to provide a 'Single Source of Truth' for trading strategies.
    
    Attributes:
        symbol: The trading pair symbol (e.g., BTCUSDT).
        config: Type-safe configuration object.
        data_root: Base directory for storing generated data assets.
    """
    
    def __init__(self, config_dict: Dict[str, Any], symbol: str, api_key: str, data_root: str = "data"):
        """Initializes the Agent with required services and configuration."""
        self.symbol = symbol
        self.data_root = data_root
        self.config = ObserverConfig.from_dict(config_dict)
            
        # Domain Logic Services
        self._vp_analyzer = self._setup_vp_analyzer()
        self._regime_analyzer = self._setup_regime_analyzer()
        
        # Primary Data Adapters
        self._binance = BinanceFuturesClient()

        # Visual Asset Management
        project_root = resolve_project_root()
        self._charting = ChartGenerator(
            output_dir=os.path.join(project_root, data_root, "images")
        )
        
        # AI Infrastructure
        self._prompt_file = os.path.join(project_root, self.config.role_definition_prompt)
        if not api_key:
            raise ValueError("ObserverAgent Specialist: Gemini API key is required.")
        self._ai_client = genai.Client(api_key=api_key)

    def observe(self, timestamp: Optional[datetime] = None, data_dir: Optional[str] = None, prefix: str = "") -> Dict[str, Any]:
        """
        Executes a comprehensive market observation cycle.
        
        Args:
            timestamp: Specific point in time to observe. Defaults to UTC now.
            data_dir: Override path for data output.
            prefix: Optional filename prefix for generated assets.
            
        Returns:
            A dictionary containing the structured observation context.
        """
        target_time = timestamp or get_utc_now()
        logger.info(f"Observer [Specialist]: Mapping {self.symbol} topographical state at {target_time}")
        
        # Phase 1: High-Fidelity Data Collection
        raw_market_data = self._collect_raw_data(target_time)
        
        # Phase 2: Multi-Dimensional Metric Calculation
        if not raw_market_data.macro_klines or not raw_market_data.micro_klines:
            logger.warning(f"Observer: Insufficient kline data for {self.symbol} at {target_time}")
            return {"error": "Insufficient market data."}

        market_metrics = self._calculate_metrics(raw_market_data)
        
        # Phase 3: Visual Evidence Generation
        visual_snapshots = self._generate_visual_proofs(
            raw_market_data, 
            market_metrics, 
            output_dir=data_dir or self.data_root,
            at_time=target_time,
            prefix=prefix
        )
        
        # Phase 4: Semantic Synthesis via Multi-modal AI
        mapping_report, final_at = self._synthesize_semantic_mapping(market_metrics, visual_snapshots, target_time)
        
        return self._build_final_observation_package(mapping_report, market_metrics, visual_snapshots, final_at)

    def _collect_raw_data(self, at_time: datetime) -> MarketDataContainer:
        """Fetches raw datum from multiple exchange and sentiment endpoints."""
        ts_ms = int(at_time.timestamp() * 1000)
        cfg = self.config
        
        # Specialized collection logic using DTO for isolation
        return MarketDataContainer(
            macro_klines=self._binance.fetch_historical_klines(self.symbol, cfg.macro_analysis_context.time_interval, cfg.macro_analysis_context.historical_lookback_candles, endTime=ts_ms) or [],
            micro_klines=self._binance.fetch_historical_klines(self.symbol, cfg.micro_analysis_context.time_interval, cfg.micro_analysis_context.historical_lookback_candles, endTime=ts_ms) or [],
            macro_oi_history=self._binance.fetch_open_interest(self.symbol, cfg.macro_analysis_context.time_interval, endTime=ts_ms - self._ms(cfg.macro_analysis_context.time_interval)),
            micro_oi_history=self._binance.fetch_open_interest(self.symbol, cfg.micro_analysis_context.time_interval, endTime=ts_ms - self._ms(cfg.micro_analysis_context.time_interval)),
            macro_ls_ratio=self._binance.fetch_long_short_ratio(self.symbol, cfg.macro_analysis_context.time_interval, limit=1, endTime=ts_ms) or [],
            micro_ls_ratio=self._binance.fetch_long_short_ratio(self.symbol, cfg.micro_analysis_context.time_interval, limit=1, endTime=ts_ms) or [],
            current_oi=self._binance.fetch_open_interest(self.symbol, cfg.micro_analysis_context.time_interval, endTime=ts_ms),
            liquidations=self._binance.fetch_liquidations(self.symbol, limit=cfg.max_liquidation_events_to_fetch) or []
        )

    def _calculate_metrics(self, raw: MarketDataContainer) -> MarketMetricsContainer:
        """Processes raw datum into structured market metrics."""
        m_df = self._vp_analyzer.process_klines(raw.macro_klines)
        n_df = self._vp_analyzer.process_klines(raw.micro_klines)
        
        profile = self._vp_analyzer.calculate_profile(m_df)
        nodes = self._vp_analyzer.find_significant_nodes(profile)
        regime = self._regime_analyzer.analyze(m_df)
        
        # Composed metric container for variable isolation
        return MarketMetricsContainer(
            price=self._derive_price_dynamics(m_df, n_df),
            structural_proximity=self._derive_structural_anchors(m_df, profile),
            volume_profile=self._refine_volume_topography(profile, nodes),
            regime=regime,
            sentiment=self._derive_sentiment_delta(raw)
        )

    def _derive_price_dynamics(self, m_df: pd.DataFrame, n_df: pd.DataFrame) -> Dict[str, Any]:
        """Calculates volatility-adjusted price metrics and structural pressure."""
        last = m_df.iloc[-1]
        h, l, c = last['high'], last['low'], last['close']
        wick_skew = (c - l) / (h - l) if (h - l) > 0 else 0.5
        
        return {
            "current_price": c,
            "atr_macro": m_df['atr'].iloc[-1],
            "atr_micro": n_df['atr'].iloc[-1],
            "wick_skewness": f"{wick_skew:.2f}"
        }

    def _derive_structural_anchors(self, df: pd.DataFrame, profile: Dict[str, Any]) -> Dict[str, Any]:
        """Maps price distance to key structural nodes in ATR units."""
        price = df['close'].iloc[-1]
        atr = df['atr'].iloc[-1]
        
        def to_atr_dist(target):
            if not target or not atr: return None
            return f"{((price - target) / atr):.2f}"

        return {
            "poc_dist_atr": to_atr_dist(profile.get('poc')),
            "vah_dist_atr": to_atr_dist(profile.get('vah')),
            "val_dist_atr": to_atr_dist(profile.get('val'))
        }

    def _refine_volume_topography(self, profile: Dict[str, Any], nodes: Dict[str, List]) -> Dict[str, Any]:
        """Filters and organizes significant volume nodes relative to price."""
        poc = profile.get('poc', 0)
        limit = self.config.top_structural_levels_to_report
        
        all_nodes = [{**n, "type": "HVN"} for n in nodes.get('hvn', [])] + [{**n, "type": "LVN"} for n in nodes.get('lvn', [])]
        
        return {
            "poc": profile.get('poc'),
            "vah": profile.get('vah'),
            "val": profile.get('val'),
            "anchors_above": sorted([n for n in all_nodes if n['price'] > poc], key=lambda x: x['price'])[:limit],
            "anchors_below": sorted([n for n in all_nodes if n['price'] < poc], key=lambda x: x['price'], reverse=True)[:limit]
        }

    def _derive_sentiment_delta(self, raw: MarketDataContainer) -> Dict[str, Any]:
        """Aggregates multi-source sentiment and order flow signals."""
        cfg = self.config
        
        # Order Flow Cumulative Delta (Short-term)
        cvd = 0.0
        if raw.micro_klines:
            for k in raw.micro_klines[-cfg.taker_volume_delta_lookback_period:]:
                v, tb = float(k[5]), float(k[9])
                cvd += (tb - (v - tb))

        # Open Interest Sensitivity
        cur_oi = float(raw.current_oi.get('openInterest', 0)) if raw.current_oi else 0
        
        def pct_chg(hist):
            if not hist: return None
            h_val = float(hist.get('openInterest', 0))
            return f"{(((cur_oi - h_val) / h_val) * 100):+.2f}%" if h_val > 0 else None

        ls_ratio_macro = raw.macro_ls_ratio[0].get('longShortRatio') if raw.macro_ls_ratio else None
        ls_ratio_micro = raw.micro_ls_ratio[0].get('longShortRatio') if raw.micro_ls_ratio else None

        return {
            "oi_nominal": cur_oi,
            "oi_delta_macro": pct_chg(raw.macro_oi_history),
            "oi_delta_micro": pct_chg(raw.micro_oi_history),
            "ls_ratio_macro": ls_ratio_macro,
            "ls_ratio_micro": ls_ratio_micro,
            "net_taker_delta": f"{cvd:.4f}",
            "high_value_liquidations": self._parse_liquidations(raw.liquidations)
        }

    def _parse_liquidations(self, liqs: List[Dict]) -> Optional[List[Dict[str, Any]]]:
        """Extracts significant liquidations into a readable context."""
        if not liqs: return None
        sorted_liqs = sorted(liqs, key=lambda x: float(x.get('qty', 0)), reverse=True)
        return [{
            "side": l.get('side'),
            "price": float(l.get('price', 0)),
            "qty": float(l.get('qty', 0)),
            "time": datetime.fromtimestamp(l.get('time', 0)/1000, tz=timezone.utc).strftime('%H:%M:%S')
        } for l in sorted_liqs[:self.config.max_liquidation_events_for_ai_context]]

    def _generate_visual_proofs(self, raw: MarketDataContainer, metrics: MarketMetricsContainer, output_dir: str, at_time: datetime, prefix: str) -> Dict[str, str]:
        """Generates visual chart artifacts for auditability."""
        img_dir = os.path.join(output_dir, "images")
        os.makedirs(img_dir, exist_ok=True)
        self._charting.output_dir = img_dir
        
        # Profile data binding for visualizer
        chart_ctx = {**metrics.volume_profile, "timestamp": at_time.isoformat()}
        m_df = self._vp_analyzer.process_klines(raw.macro_klines)
        n_df = self._vp_analyzer.process_klines(raw.micro_klines)
        
        return {
            "macro_snapshot": self._charting.generate_chart(self.symbol, m_df, chart_ctx, raw.liquidations, time_interval=self.config.macro_analysis_context.time_interval),
            "micro_snapshot": self._charting.generate_chart(self.symbol, n_df, chart_ctx, raw.liquidations, time_interval=self.config.micro_analysis_context.time_interval)
        }

    def _synthesize_semantic_mapping(self, metrics: MarketMetricsContainer, snapshots: Dict[str, str], at_time: datetime) -> Tuple[Dict[str, Any], datetime]:
        """Translates numerical metrics and charts into objective semantic observations via AI."""
        try:
            prompt_tpl = read_prompt_template(self._prompt_file)
            input_text = prompt_tpl.format(
                timestamp=format_datetime(at_time),
                macro_timeframe=to_json({"interval": self.config.macro_analysis_context.time_interval, "limit": self.config.macro_analysis_context.historical_lookback_candles}),
                micro_timeframe=to_json({"interval": self.config.micro_analysis_context.time_interval, "limit": self.config.micro_analysis_context.historical_lookback_candles}),
                metrics=to_json(metrics.__dict__)
            )
            
            # Multi-modal payload construction
            payload = []
            for lbl, path in [("MACRO", snapshots['macro_snapshot']), ("MICRO", snapshots['micro_snapshot'])]:
                if path and path is not None and os.path.exists(path):
                    payload.append(f"[VISUAL PROOF: {lbl}]")
                    with open(path, 'rb') as f:
                        payload.append(types.Part.from_bytes(data=f.read(), mime_type='image/png'))
            payload.append(input_text)
            
            resp = self._ai_client.models.generate_content(
                model=self.config.model,
                contents=payload,
                config=types.GenerateContentConfig(temperature=self.config.temperature, response_mime_type="application/json")
            )

            result = json.loads(resp.text)
            return self._validate_report_schema(result), at_time
            
        except Exception as e:
            logger.error(f"Semantic Mapping Failure: {e}", exc_info=True)
            return {"error": "Observer failed to generate semantic mapping."}, at_time

    def _validate_report_schema(self, report: Dict[str, Any]) -> Dict[str, Any]:
        """Ensures the AI output adheres to the specialist topographical schema."""
        required = ["structural_proximity", "anomaly_detection", "regime_delta", "macro_topography", "micro_execution"]
        for key in required:
            if key not in report:
                report[key] = "Mapping unavailable for this dimension."
        return report

    def _build_final_observation_package(self, mapping: Dict[str, Any], metrics: MarketMetricsContainer, charts: Dict[str, str], at_time: datetime) -> Dict[str, Any]:
        """Constructs the high-level response dictionary for the observer cycle."""
        cfg = self.config
        return {
            "symbol": self.symbol,
            "timestamp": f"{at_time.isoformat()}Z",
            "observation_specs": {
                "macro": {"interval": cfg.macro_analysis_context.time_interval, "limit": cfg.macro_analysis_context.historical_lookback_candles},
                "micro": {"interval": cfg.micro_analysis_context.time_interval, "limit": cfg.micro_analysis_context.historical_lookback_candles}
            },
            "visual_assets": charts,
            "quantitative_metrics": metrics.__dict__,
            "semantic_observations": mapping
        }

    def _ms(self, interval: Union[str, Any]) -> int:
        """Utility to convert timeframe strings to milliseconds."""
        if not isinstance(interval, str):
            logger.warning(f"Invalid interval type: {type(interval)}")
            return 60000
        u = interval[-1]
        v = int(interval[:-1])
        m = {"m": 60, "h": 3600, "d": 86400}
        return v * m.get(u, 60) * 1000

    def _setup_vp_analyzer(self) -> VolumeProfileAnalyzer:
        """Configures the Volume Profile analyzer with type-safe parameters."""
        cfg = self.config
        vp_config = VolumeProfileConfig(
            value_area_ratio=cfg.volume_profile_value_area_width, 
            resolution_bins=cfg.volume_profile_price_buckets_count,
            atr_period=cfg.average_true_range_period, 
            max_hvn_nodes=cfg.high_volume_peak_count, 
            max_lvn_nodes=cfg.low_volume_valley_count,
            hvn_sensitivity=cfg.high_volume_peak_sensitivity, 
            lvn_sensitivity=cfg.low_volume_valley_sensitivity,
            min_node_distance=cfg.min_price_gap_between_nodes
        )
        return VolumeProfileAnalyzer(config=vp_config)

    def _setup_regime_analyzer(self) -> MarketRegimeAnalyzer:
        """Configures the Market Regime analyzer with type-safe parameters."""
        cfg = self.config
        regime_config = MarketRegimeConfig(
            bollinger_window=cfg.bollinger_bands_period, 
            bollinger_std_dev=cfg.bollinger_bands_std_dev, 
            keltner_window=cfg.keltner_channels_period,
            keltner_multiplier=cfg.keltner_channels_multiplier, 
            volume_ma_window=cfg.volume_moving_average_period,
            trend_threshold=cfg.market_regime_trend_strength_threshold
        )
        return MarketRegimeAnalyzer(config=regime_config)

    def close(self):
        """Cleanly releases network resources."""
        if hasattr(self, '_binance'):
            self._binance.close()
