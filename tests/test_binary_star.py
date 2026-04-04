import unittest
import sys
import os
import json
from unittest.mock import MagicMock, patch

# Setup paths
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.agent.binary_star_orchestrator import BinaryStarOrchestrator
from tests.mock_factory import MockDataFactory

class TestBinaryStarFlow(unittest.TestCase):
    def setUp(self):
        self.api_key = "mock_key"
        self.config = MockDataFactory.create_mock_config()
        
        # Patch external infrastructure to prevent real network calls
        self.patchers = [
            patch('google.genai.Client'),
            patch('src.infrastructure.binance.client.BinanceFuturesClient'),
            patch('src.analyzer.chart_generator.ChartGenerator'),
            patch('src.infrastructure.gemini.cache_manager.GeminiCacheManager'),
            patch('src.agent.binary_star_orchestrator.load_config', return_value=self.config),
            patch('src.utils.pipeline_utils.read_prompt_template', return_value="Mock Instruction")
        ]
        for p in self.patchers:
            p.start()
            
        self.mock_obs = MockDataFactory.create_mock_session_result("BTCUSDT")["observation"]

    def tearDown(self):
        patch.stopall()

    def test_debate_convergence_and_metadata(self):
        """Tests that the orchestrator converges when skepticism score drops."""
        orchestrator = BinaryStarOrchestrator(self.config, self.api_key, data_root="data/test")
        
        # 1. Mock SessionAgent: Handles all phases through execute_session_cycle
        orchestrator.session_agent.execute_session_cycle = MagicMock()
        orchestrator.session_agent.execute_session_cycle.side_effect = [
            {"opinion": "BULLISH", "limit_order": {"entry": 60000}}, # Round 1 Draft
            {"opinion": "BULLISH", "limit_order": {"entry": 60050}}, # Round 2 Draft
            {"opinion": "BULLISH", "final_score": 90}                # Final Synthesis
        ]
        
        # 2. Mock Critic: Returns high skepticism then low skepticism (Convergence)
        orchestrator.critic_agent.evaluate = MagicMock()
        orchestrator.critic_agent.evaluate.side_effect = [
            {"skepticism_score": 80, "objections": ["Too risky"]},
            {"skepticism_score": 10, "objections": []} # Should trigger early stopping (10 < 20)
        ]

        # Set the threshold manually for the test
        orchestrator.stop_threshold = 20
        
        # Execute
        result = orchestrator.execute_flow(self.mock_obs, "BTCUSDT")
        
        # Verify Convergence
        self.assertEqual(len(result["debate_history"]), 2)
        
        # Verify Metadata Fingerprinting
        self.assertIn("version_control", result["metadata"])

    def test_max_rounds_exhaustion(self):
        """Enforces max_rounds even if convergence fails."""
        orchestrator = BinaryStarOrchestrator(self.config, self.api_key, data_root=resolve_data_root("test"))
        orchestrator.stop_threshold = 20
        
        orchestrator.session_agent.execute_session_cycle = MagicMock(return_value={"opinion": "NEUTRAL"})
        # Never converges
        orchestrator.critic_agent.evaluate = MagicMock(return_value={"skepticism_score": 100})
        
        result = orchestrator.execute_flow(self.mock_obs, "BTCUSDT")
        
        # Verify exhaustion
        self.assertEqual(len(result["debate_history"]), 3)

if __name__ == '__main__':
    unittest.main()
