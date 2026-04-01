import unittest
import sys
import os
import json
from unittest.mock import MagicMock, patch

# Setup paths (tests/ -> PROJECT_ROOT)
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.agent.binary_star_orchestrator import BinaryStarOrchestrator

class TestBinaryStarFlow(unittest.TestCase):
    def setUp(self):
        self.api_key = "mock_key"
        
        # Start patcher
        self.patcher = patch('src.agent.binary_star_orchestrator.load_config')
        self.mock_load_config = self.patcher.start()
        
        # Mock global infrastructure config
        self.mock_load_config.return_value = {
            'network': {
                'gemini': {
                    'api_timeout_seconds': 30,
                    'retry_count': 2,
                    'retry_strategy': {
                        'multiplier': 1,
                        'min_seconds': 2,
                        'max_seconds': 10
                    }
                }
            },
            'agent_model_shared_config': {
                'max_tool_iterations': 5
            },
            'strategy_intent': 'MARKET_TOPOGRAPHY_EXPLOITATION'
        }
        
        self.config = {
            "strategy_intent": "MARKET_TOPOGRAPHY_EXPLOITATION",
            "data_storage_root": "data",
            "network": {
                "gemini": {
                    "api_timeout_seconds": 120,
                    "retry_count": 2,
                    "retry_strategy": {
                        "multiplier": 2.0,
                        "min_seconds": 2,
                        "max_seconds": 10
                    }
                }
            },
            "agent_model_shared_config": {
                "max_tool_iterations": 5
            },
            "binary_star": {
                "agent_model": "gemini-flash-latest",
                "agent_model_max_debate_rounds": 1,
                "agent_model_debate_stop_threshold": 50,
                "agent_model_cache_expiration_minutes": 10,
                "agent_model_system_instruction": "src/agent/prompts/binary_star.md",
                "default_symbol": "BTCUSDT"
            },
            "strategist": {
                "role_definition_prompt": "src/agent/prompts/strategist.md",
                "model": "gemini-flash-latest",
                "model_temperature_draft": 0.7,
                "model_temperature_synthesis": 0.3,
                "min_trade_velocity": 0.4,
                "stop_loss_buffer_min": 0.3,
                "stop_loss_buffer_max": 2.5,
                "score_confidence_base": 75,
                "score_confidence_decay_min": 5,
                "score_confidence_decay_max": 30,
                "holding_time_modifier": 1.5,
                "projected_vel_min": 0.1,
                "projected_vel_max": 2.0
            },
            "critic": {
                "role_definition_prompt": "src/agent/prompts/critic.md",
                "model": "gemini-flash-latest",
                "model_temperature": 0.3,
                "threshold_skepticism_clear": 20,
                "threshold_skepticism_weak": 40,
                "threshold_skepticism_constructive": 60
            },
            "observer": {
                "role_definition_prompt": "src/agent/prompts/observer.md",
                "model": "gemini-flash-latest",
                "model_temperature": 0.3,
                "macro_analysis_context": {
                    "time_interval": "1h",
                    "historical_lookback_candles": 100
                },
                "micro_analysis_context": {
                    "time_interval": "1m",
                    "historical_lookback_candles": 100
                },
                "volume_profile_value_area_width": 0.7,
                "volume_profile_price_bucket_count": 24,
                "order_flow_lookback_hours": 24.0,
                "regime_trend_intensity_threshold": 0.5,
                "average_true_range_period": 14,
                "bollinger_bands_period": 20,
                "bollinger_bands_std_dev": 2.0,
                "keltner_channels_period": 20,
                "keltner_channels_multiplier": 1.5,
                "volume_moving_average_period": 20,
                "max_liquidation_events_to_fetch": 100,
                "max_liquidation_events_for_context": 50,
                "max_high_volume_node_count": 3,
                "max_low_volume_node_count": 3,
                "high_volume_node_detection_threshold": 1.2,
                "low_volume_node_detection_threshold": 0.8,
                "min_price_gap_between_nodes": 10,
                "top_structural_node_count": 3,
                "trend_intensity_duration_hours": 24.0,
                "wick_skewness_period": 24,
                "liquidation_cluster_atr_multiplier": 0.25,
                "liquidation_cluster_fallback_percentage": 0.005,
                "funding_rate_lookback_hours": 24.0,
                "volatility_intensity_lookback": 100,
                "regime_volatility_baseline_ratio": 1.0,
                "regime_volatility_expansion_ratio": 1.5,
                "regime_volatility_extreme_ratio": 3.0,
                "regime_volume_breakout_threshold": 2.0,
                "regime_long_short_imbalance_ratio": 1.5,
                "regime_poc_gravity_atr_distance": 1.0,
                "regime_vacuum_risk_score": 3.0,
                "regime_wick_skewness_exhaustion": 0.6,
                "regime_wick_skewness_momentum_bullish": 0.2,
                "regime_wick_skewness_momentum_bearish": -0.2,
                "regime_trend_intensity_strong": 0.8,
                "regime_min_rr_ranging": 1.5,
                "regime_min_rr_trending": 2.5,
                "regime_volume_baseline_ratio": 1.0,
                "regime_squeeze_threshold": 0.1,
                "regime_squeeze_audit_threshold": 0.2,
                "regime_balanced_atr_multiplier": 1.5,
                "regime_breakout_buffer_atr": 0.1,
                "regime_breakout_frontrun_atr": 0.2,
                "regime_poc_magnet_atr_threshold": 1.5,
                "regime_gravity_volume_override_ratio": 3.0,
                "regime_boundary_clipping_atr": 0.2,
                "regime_cvd_slope_threshold": 0.1,
                "regime_participation_volume_threshold": 1.0,
                "regime_anchor_drift_threshold": 0.5,
                "max_liquidation_clusters": 5,
                "wick_skew_fallback": 0.5
            }
        }
        self.api_key = "test_api_key"
        
        # Start patchers for external dependencies to ensure isolation
        self.patchers = [
            patch('src.infrastructure.binance.client.BinanceFuturesClient'),
            patch('src.analyzer.chart_generator.ChartGenerator'),
            patch('src.infrastructure.gemini.cache_manager.GeminiCacheManager')
        ]
        for p in self.patchers:
            p.start()
        
        # Mock Observation
        self.mock_obs = {
            "symbol": "BTCUSDT",
            "timestamp": "2026-04-01T22:00:00Z",
            "quantitative_metrics": {
                "price_dynamics": {"current_price": 60000.0, "atr_macro": 500.0}
            }
        }
        
    def tearDown(self):
        self.patcher.stop()

    @patch('google.genai.Client')
    @patch('src.infrastructure.gemini.cache_manager.GeminiCacheManager.create_market_cache')
    def test_full_debate_cycle(self, mock_create_cache, mock_client):
        # Define a detailed mock usage metadata
        mock_usage = MagicMock()
        mock_usage.total_token_count = 100
        mock_usage.prompt_token_count = 80
        mock_usage.candidates_token_count = 20
        mock_usage.cached_content_token_count = 50
        
        mock_response = MagicMock()
        mock_response.text = '{"decision": "BULLISH", "confidence": 0.85, "reasoning": "Mocked", "action": "LIMIT_BUY", "position_size": 0.1}'
        mock_response.usage_metadata = mock_usage
        mock_client.models.generate_content.return_value = mock_response
        
        # Mock Cache Manager
        mock_create_cache.return_value = "mock_cache_id"
        
        # Initialize Orchestrator
        orchestrator = BinaryStarOrchestrator(self.config, self.api_key, data_root="data")
        
        # NOTE: Orchestrator internally initializes agents using its self.client
        # No more manual agent initialization with api_key in tests unless via Orchestrator
        
        # Mock Agent Responses
        orchestrator.strategist.draft = MagicMock(return_value={"opinion": "BULLISH", "limit_order": {"entry": 60000}})
        orchestrator.critic.audit = MagicMock(return_value={"skepticism_score": 20, "objections": []})
        orchestrator.strategist.synthesize = MagicMock(return_value={"opinion": "BULLISH", "final_score": 85})
        
        # Execute
        result = orchestrator.execute_flow(self.mock_obs, "BTCUSDT")
        
        # Verify
        self.assertIn("metadata", result)
        self.assertIn("version_control", result["metadata"])
        self.assertIn("strategist_hash", result["metadata"]["version_control"])
        self.assertEqual(result["final_decision"]["opinion"], "BULLISH")
        
        print(f"\nIntegration Mock Result: {json.dumps(result['metadata']['version_control'], indent=2)}")

if __name__ == '__main__':
    unittest.main()
