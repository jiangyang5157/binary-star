import unittest
import pandas as pd
import numpy as np
from src.analyzer.market_regime import MarketRegimeAnalyzer, MarketRegimeConfig
from src.analyzer.volume_profile import VolumeProfileAnalyzer, VolumeProfileConfig

class TestSemanticConsistency(unittest.TestCase):
    def setUp(self):
        self.regime_cfg = MarketRegimeConfig(
            bollinger_window=20, bollinger_std_dev=2.0,
            keltner_window=20, keltner_multiplier=1.5,
            volume_ma_window=20, trend_threshold=0.35,
            trend_intensity_lookback=14, wick_skewness_period=5
        )
        self.vp_cfg = VolumeProfileConfig(
            value_area_ratio=0.7, resolution_bins=10,
            atr_period=14, max_hvn_nodes=3, max_lvn_nodes=3,
            hvn_sensitivity=0.1, lvn_sensitivity=0.1,
            min_node_distance=1
        )

    def test_wick_skewness_directionality(self):
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
        self.assertIn('wick_skewness_lookback', result)
        self.assertGreater(result['wick_skewness_lookback'], 0.5)

    def test_volume_profile_structural_state_naming(self):
        """Verify that volume profile uses 'structural_state' and not 'market_regime'."""
        klines = [
            [i, 100, 105, 95, 100, 1000, i+1, 10000, 100, 500, 5000, 0]
            for i in range(100)
        ]
        analyzer = VolumeProfileAnalyzer(config=self.vp_cfg)
        result = analyzer.analyze(klines)
        
        self.assertIn('structural_state', result)
        self.assertNotIn('market_regime', result) # Should be removed/renamed
        self.assertIn(result['structural_state'], ["BALANCED", "IMBALANCED"])

if __name__ == "__main__":
    unittest.main()
