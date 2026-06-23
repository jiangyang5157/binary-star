import os
import yaml
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, Any, Optional

from src.infrastructure.exchange.base_client import AbstractExchangeClient
from src.infrastructure.binance.client import BinanceFuturesClient
from src.analyzer.market_observer import MarketObserverConfig, MarketDataLoader, MarketMetricsRefiner
from src.analyzer.volume_profile import VolumeProfileAnalyzer, VolumeProfileConfig
from src.analyzer.market_regime import MarketRegimeAnalyzer, MarketRegimeConfig
from src.analyzer.liquidation_radar import LiquidationRadar
from src.utils.pipeline_utils import load_config, load_global_config
from src.utils.logger_utils import setup_logger

logger = setup_logger(__name__)

@dataclass
class ScoutResult:
    """Lean container for trigger-specific metrics."""
    symbol: str
    timestamp: datetime
    metrics: Dict[str, Any]
    raw_data: Any  # RawMarketData for possible downstream reuse

class SniperScout:
    """
    Lightweight topography harvester.
    
    Orchestrates the minimally viable data collection required for 
    the 'Wake-Up Matrix'. Skips visualization to ensure zero-latency 
    noise-less monitoring.
    """
    
    def __init__(self, symbol: str, exchange_client: Optional[AbstractExchangeClient] = None):
        self.symbol = symbol
        self.exchange_client: AbstractExchangeClient = exchange_client or BinanceFuturesClient()
        
        # Load core strategy configs to initialize analyzers (Option A: Full reuse)
        self.strategy_cfg = load_config()
        self.global_cfg = load_global_config()

        # Apply per-symbol config overrides (XAUTUSDT vs BTCUSDT baseline)
        from src.config.symbol_resolver import resolve_config
        self.strategy_cfg = resolve_config(self.strategy_cfg, symbol)
        self.global_cfg = resolve_config(self.global_cfg, symbol)

        # Merge for MarketObserverConfig structure
        full_cfg = {**self.strategy_cfg, **self.global_cfg}
        self.obs_config = MarketObserverConfig.from_dict(full_cfg)
        
        # Initialize analyzers (No UI, just math)
        vp_cfg = VolumeProfileConfig(
            value_area_ratio=self.obs_config.volume_profile_area_ratio,
            atr_period=self.obs_config.atr_period,
            max_volume_node_count=self.obs_config.max_volume_node_count,
            high_volume_node_detection_threshold=self.obs_config.high_volume_node_detection_threshold,
            low_volume_node_detection_threshold=self.obs_config.low_volume_node_detection_threshold,
            min_node_gap_atr=self.obs_config.min_node_gap_atr,
            ranging_width_atr=self.obs_config.regime.ranging_width_atr
        )
        self.vp_analyzer = VolumeProfileAnalyzer(config=vp_cfg)

        rg_cfg = MarketRegimeConfig(
            bollinger_window=self.obs_config.bb_period,
            bollinger_std_dev=self.obs_config.bb_std_dev,
            keltner_window=self.obs_config.kc_period,
            keltner_multiplier=self.obs_config.kc_multiplier,
            volume_ma_window=self.obs_config.volume_ma_period,
            trend_intensity_threshold=self.obs_config.regime.trend_intensity_threshold,
            trend_lookback_candles=self.obs_config.trend_intensity_macro_lookback_candles,
            wick_skew_lookback_candles=self.obs_config.wick_skew_lookback_candles
        )
        self.regime_analyzer = MarketRegimeAnalyzer(config=rg_cfg)

        self.radar = LiquidationRadar(
            volume_moving_average_period=self.obs_config.volume_ma_period,
            volume_surge_vs_ma_ratio=self.obs_config.regime.volume_surge_vs_ma_ratio,
            max_liquidation_clusters=self.obs_config.max_liquidation_clusters,
            long_taker_threshold=self.obs_config.liq_radar_long_threshold,
            short_taker_threshold=self.obs_config.liq_radar_short_threshold,
            gaussian_sigma=self.obs_config.liq_radar_gaussian_sigma,
            grid_bins=self.obs_config.liq_radar_grid_bins,
            grid_padding_atr=self.obs_config.liq_radar_grid_padding_atr,
        )
        self.loader = MarketDataLoader(self.exchange_client, self.obs_config)
        self.refiner = MarketMetricsRefiner(self.obs_config, self.vp_analyzer, self.regime_analyzer, self.radar)

    def scout(self, at_time: Optional[datetime] = None) -> ScoutResult:
        """Harvests market datum and distills it into trigger-ready metrics."""
        ts = at_time or datetime.now(timezone.utc)
        logger.debug(f"SniperScout [{self.symbol}]: Harvester active...")
        
        # 1. Harvest raw telemetry (No cache, direct from Binance)
        raw = self.loader.collect(self.symbol, ts)
        
        # 2. Quality Validation
        if len(raw.macro_klines) < int(self.obs_config.macro_context.lookback_candles * 0.9):
            logger.warning(f"SniperScout [{self.symbol}]: Insufficient telemetry. Skipping.")
            return ScoutResult(self.symbol, ts, {}, raw)

        # 3. Refine into metrics (Option A: Full Re-use of VP and Regime math)
        metrics = self.refiner.refine(raw)
        
        # Slim down the processed metrics to just what the Trigger needs
        distilled = {
            "price_dynamics": metrics.price_dynamics,
            "market_regime": metrics.market_regime,
            "structural_anchors": metrics.structural_anchors,
            "sentiment_signals": metrics.sentiment_signals,
            "volume_profile": metrics.volume_profile  # Distilled nodes
        }
        
        return ScoutResult(
            symbol=self.symbol,
            timestamp=ts,
            metrics=distilled,
            raw_data=raw
        )

    def close(self):
        self.exchange_client.close()
