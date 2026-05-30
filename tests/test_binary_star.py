import pytest
from unittest.mock import MagicMock
from src.agent.binary_star_orchestrator import BinaryStarOrchestrator
from tests.mock_factory import MockDataFactory

class TestBinaryStarFlow:
    @pytest.fixture
    def orchestrator(self, mock_orchestrator_infrastructure, mock_config):
        """Standardized orchestrator instantiation for testing."""
        return BinaryStarOrchestrator(mock_config, "mock_key", data_root="data/test", symbol="BTCUSDT")

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
            MockDataFactory.create_mock_critic_response(level="TERMINAL"),
            MockDataFactory.create_mock_critic_response(level="CONSTRUCTIVE"),
            MockDataFactory.create_mock_critic_response(level="PASS")
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
        
        # Never converges (Always returns high skepticism)
        orchestrator.session_agent.execute_session_cycle = MagicMock(
            return_value=MockDataFactory.create_mock_ai_response("BULLISH")
        )
        orchestrator.critic_agent.evaluate = MagicMock(
            return_value=MockDataFactory.create_mock_critic_response(level="TERMINAL")
        )
        
        result = orchestrator.execute_flow(mock_obs, "BTCUSDT")
        
        # Verify exhaustion (Max rounds = 3 as per mock_config)
        assert len(result["debate_history"]) == 3
        # Ensure it went through the loop 3 times
        assert orchestrator.critic_agent.evaluate.call_count == 3

    def test_early_exit_on_pass(self, orchestrator):
        """Tests that the orchestrator exits early if the Critic issues a PASS."""
        mock_obs = MockDataFactory.create_mock_session_result("BTCUSDT")["observation"]
        
        # R1 returns a perfect plan
        orchestrator.session_agent.execute_session_cycle = MagicMock(
            return_value=MockDataFactory.create_mock_ai_response("BULLISH")
        )
        # Critic returns PASS in Round 1
        orchestrator.critic_agent.evaluate = MagicMock(
            return_value=MockDataFactory.create_mock_critic_response(level="PASS")
        )
        
        result = orchestrator.execute_flow(mock_obs, "BTCUSDT")
        
        # Verify early exit (Only 1 round in history)
        assert len(result["debate_history"]) == 1
        assert orchestrator.critic_agent.evaluate.call_count == 1
        assert orchestrator.session_agent.execute_session_cycle.call_count == 1 # Only 1 planning call

    def test_synthesis_temperature_shift(self, orchestrator):
        """Verifies that final synthesis uses the Critic's cold temperature (Strategic Alpha)."""
        mock_obs = MockDataFactory.create_mock_session_result("BTCUSDT")["observation"]
        
        # Mock responses to ensure it reaches synthesis (no early exit)
        orchestrator.session_agent.execute_session_cycle = MagicMock(
            return_value=MockDataFactory.create_mock_ai_response("BULLISH")
        )
        orchestrator.critic_agent.evaluate = MagicMock(
            return_value=MockDataFactory.create_mock_critic_response(level="CONSTRUCTIVE")
        )
        
        orchestrator.execute_flow(mock_obs, "BTCUSDT")
        
        # Check call arguments for the synthesis round (last call)
        # Round 1, 2, 3 planning calls use session_config.model_temperature (0.7)
        # Synthesis call uses critic_config.model_temperature (0.2)
        calls = orchestrator.session_agent.execute_session_cycle.call_args_list
        
        # Planning Rounds (R1, R2, R3)
        for i in range(3):
            assert calls[i].kwargs["temperature"] == 0.7
            assert "Planning" in calls[i].kwargs["agent_name"]
            
        # Final Synthesis Round
        assert calls[-1].kwargs["temperature"] == 0.2
        assert calls[-1].kwargs["agent_name"] == "Session_Synthesis"

    def test_final_decision_sanitization(self, orchestrator):
        """Verifies that the final decision is sanitized with math-verified parameters."""
        mock_obs = MockDataFactory.create_mock_session_result("BTCUSDT")["observation"]
        
        # 1. Mock synthesis response WITHOUT rr_ratio
        raw_response = MockDataFactory.create_mock_ai_response("BULLISH")
        raw_response["tactical_parameters"] = {
            "entry": 50000.0,
            "take_profit": 55000.0,
            "stop_loss": 48000.0,
            "projected_holding_hours": 999.0, # Incorrect value
            "projected_waiting_hours": 999.0  # Incorrect value
        }
        
        orchestrator.session_agent.execute_session_cycle = MagicMock(return_value=raw_response)
        
        # 2. Mock Critic to PASS Round 1 (Early Exit)
        orchestrator.critic_agent.evaluate = MagicMock(
            return_value=MockDataFactory.create_mock_critic_response(level="PASS")
        )

        # 3. Execution
        result = orchestrator.execute_flow(mock_obs, "BTCUSDT")
        
        # 4. Verification
        tactical = result["final_decision"]["tactical_parameters"]
        
        # Verify that parameters were updated from the initial '999.0' placeholders
        # and that the rr_ratio was successfully injected.
        assert tactical["rr_ratio"] == 2.5
        assert tactical["projected_holding_hours"] != 999.0
        assert tactical["projected_waiting_hours"] != 999.0
        assert tactical["projected_holding_hours"] > 0
        assert tactical["entry"] == 50000.0 # Unchanged
