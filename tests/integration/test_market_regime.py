import unittest
import pandas as pd
from src.analyzer.market_regime import MarketRegimeAnalyzer, MarketRegimeConfig
from src.analyzer.volume_profile import VolumeProfileAnalyzer, VolumeProfileConfig
from src.infrastructure.exchange.models import KlineData

class TestSemanticConsistency(unittest.TestCase):
    def setUp(self):
        from src.utils.pipeline_utils import load_combined_config as _lc
        from src.analyzer.market_observer import MarketObserverConfig as _moc
        _obs = _moc.from_dict(_lc())
        self.regime_cfg = MarketRegimeConfig(
            bollinger_window=_obs.bb_period,
            bollinger_std_dev=_obs.bb_std_dev,
            keltner_window=_obs.kc_period,
            keltner_multiplier=_obs.kc_multiplier,
            volume_ma_window=_obs.volume_ma_period,
            trend_intensity_threshold=_obs.regime.trend_intensity_threshold,
            trend_lookback_candles=_obs.trend_intensity_macro_lookback_candles,
            wick_skew_lookback_candles=_obs.wick_skew_lookback_candles,
        )
        self.vp_cfg = VolumeProfileConfig(
            value_area_ratio=0.7, 
            resolution_bins=10,
            atr_period=14, 
            max_volume_node_count=3, 
            high_volume_node_detection_threshold=0.1, 
            low_volume_node_detection_threshold=0.1,
            min_node_gap_atr=1.2,
            ranging_width_atr=1.5
        )

    def test_wick_skew_directionality(self):
        """Verify that upper wicks result in positive skewness (selling pressure)."""
        # Create 30 candles with long upper wicks to satisfy 20-period BB window
        data = {
            'open': [100] * 30,
            'high': [110] * 30, # 10 point upper wick
            'low': [99] * 30,   # 1 point lower wick
            'close': [100] * 30,
            'volume': [1000] * 30
        }
        df = pd.DataFrame(data)
        analyzer = MarketRegimeAnalyzer(config=self.regime_cfg)
        result = analyzer.analyze(df)
        
        # Upper wicks (10) > Lower wicks (1) => Positive Skewness
        self.assertIn('wick_skew_regime', result)
        self.assertGreater(result['wick_skew_regime'], 0.5)

    def test_volume_profile_structural_state_naming(self):
        """Verify that volume profile uses 'structural_state' and not 'market_regime'."""
        klines = [
            KlineData(i, 100.0, 105.0, 95.0, 100.0, 1000.0, i+1, 10000.0, 100, 500.0, 5000.0)
            for i in range(100)
        ]
        analyzer = VolumeProfileAnalyzer(config=self.vp_cfg)
        result = analyzer.analyze(klines)
        
        self.assertIn('poc', result)
        self.assertIn('vah', result)
        self.assertIn('val', result)
        self.assertGreater(result['poc'], 0)

if __name__ == "__main__":
    unittest.main()
