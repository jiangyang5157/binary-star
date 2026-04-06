import pytest
from unittest.mock import MagicMock, patch
from src.agent.binary_star_orchestrator import BinaryStarOrchestrator
from tests.mock_factory import MockDataFactory

class TestBinaryStarFlow:
    @pytest.fixture
    def orchestrator(self, mock_orchestrator_infrastructure, mock_config):
        """Standardized orchestrator instantiation for testing."""
        return BinaryStarOrchestrator(mock_config, "mock_key", data_root="data/test")

    def test_debate_convergence_and_metadata(self, orchestrator):
        """Tests that the orchestrator converges when skepticism score drops."""
        # Setup Mocks
        mock_obs = MockDataFactory.create_mock_session_result("BTCUSDT")["observation"]
        
        # 1. Mock SessionAgent: Planning Rounds + Final Synthesis
        orchestrator.session_agent.execute_session_cycle = MagicMock(side_effect=[
            MockDataFactory.create_mock_ai_response("BULLISH"), # R1
            MockDataFactory.create_mock_ai_response("BULLISH"), # R2
            MockDataFactory.create_mock_ai_response("BULLISH"), # R3
            MockDataFactory.create_mock_ai_response("BULLISH")  # Synthesis
        ])
        
        # 2. Mock Critic: Returns high skepticism then low skepticism (Convergence)
        orchestrator.critic_agent.evaluate = MagicMock(side_effect=[
            MockDataFactory.create_mock_critic_response(score=80, veto=True),
            MockDataFactory.create_mock_critic_response(score=10, veto=False),
            MockDataFactory.create_mock_critic_response(score=5, veto=False)
        ])

        # Execute
        result = orchestrator.execute_flow(mock_obs, "BTCUSDT")
        
        # Verify execution (Always runs max_rounds = 3 in mock_config)
        assert len(result["debate_history"]) == 3
        assert result["final_decision"]["opinion"] == "BULLISH"
        assert "version_control" in result["metadata"]

    def test_max_rounds_exhaustion(self, orchestrator):
        """Enforces max_rounds even if convergence fails."""
        mock_obs = MockDataFactory.create_mock_session_result("BTCUSDT")["observation"]
        
        # Never converges
        orchestrator.session_agent.execute_session_cycle = MagicMock(
            return_value=MockDataFactory.create_mock_ai_response("NEUTRAL")
        )
        orchestrator.critic_agent.evaluate = MagicMock(
            return_value=MockDataFactory.create_mock_critic_response(score=100, veto=True)
        )
        
        result = orchestrator.execute_flow(mock_obs, "BTCUSDT")
        
        # Verify exhaustion (Max rounds = 3 as per mock_config)
        assert len(result["debate_history"]) == 3
