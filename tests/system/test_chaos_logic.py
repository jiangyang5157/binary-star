import pytest
from src.agent.binary_star_orchestrator import BinaryStarOrchestrator
from tests.mock_factory import MockDataFactory

class TestChaosLogic:
    @pytest.fixture
    def orchestrator(self, mock_orchestrator_infrastructure, mock_config):
        """Standardized orchestrator instantiation for testing."""
        return BinaryStarOrchestrator(mock_config, "mock_key", data_root="data/test", symbol="BTCUSDT")

    def test_rr_validation_no_chaos(self, orchestrator):
        """Standard RR check without chaos (min_rr_trending = 1.2)."""
        observation = MockDataFactory.create_mock_session_result(
            "BTCUSDT", current_price=60000, atr=500, trend_intensity=0.96
        )["observation"]
        # Explicitly set no chaos
        observation["quantitative_metrics"]["price_dynamics"]["volatility_expansion_index"] = 1.0
        
        plan = MockDataFactory.create_mock_ai_response(opinion="BULLISH")
        # Entry 60000, SL 59500, TP 60550. RR = 550/500 = 1.1 (< 1.2)
        plan["tactical_parameters"].update({
            "entry": 60000.0,
            "stop_loss": 59500.0,
            "take_profit": 60550.0
        })

        results = orchestrator.math_checker.verify(plan, observation)
        assert results["compliance_verdict"]["rr_is_valid"] is False
        assert results["rr_verification"]["rr_ratio"] == 1.1

    def test_rr_validation_with_chaos(self, orchestrator):
        """Discounted RR check during IS_CHAOS.
        Standard min_rr_trending = 1.2.
        Chaos discount = 0.35.
        Effective min_rr = 1.2 * (1 - 0.35) = 0.78.
        """
        observation = MockDataFactory.create_mock_session_result(
            "BTCUSDT", current_price=60000, atr=500, trend_intensity=0.96
        )["observation"]
        # Trigger Chaos (extreme_ratio = 2.0)
        observation["quantitative_metrics"]["price_dynamics"]["volatility_expansion_index"] = 2.5
        
        plan = MockDataFactory.create_mock_ai_response(opinion="BULLISH")
        # Entry 60000, SL 59500, TP 60450. RR = 450/500 = 0.9.
        # 0.9 is below standard 1.2 but above chaos-adjusted 0.78.
        plan["tactical_parameters"].update({
            "entry": 60000.0,
            "stop_loss": 59500.0,
            "take_profit": 60450.0
        })

        results = orchestrator.math_checker.verify(plan, observation)
        assert results["compliance_verdict"]["rr_is_valid"] is True
        assert results["rr_verification"]["rr_ratio"] == 0.9

    def test_rr_validation_chaos_boundary(self, orchestrator):
        """RR exactly at chaos-adjusted threshold (0.78) should be valid."""
        observation = MockDataFactory.create_mock_session_result(
            "BTCUSDT", current_price=60000, atr=500, trend_intensity=0.96
        )["observation"]
        observation["quantitative_metrics"]["price_dynamics"]["volatility_expansion_index"] = 2.5

        plan = MockDataFactory.create_mock_ai_response(opinion="BULLISH")
        # RR = 390/500 = 0.78 (exactly at chaos-adjusted min_rr = 1.2 * 0.65 = 0.78)
        plan["tactical_parameters"].update({
            "entry": 60000.0,
            "stop_loss": 59500.0,
            "take_profit": 60390.0
        })

        results = orchestrator.math_checker.verify(plan, observation)
        assert results["rr_verification"]["rr_ratio"] == 0.78

    def test_rr_validation_chaos_below_threshold(self, orchestrator):
        """RR below chaos-adjusted threshold (0.78) should be invalid."""
        observation = MockDataFactory.create_mock_session_result(
            "BTCUSDT", current_price=60000, atr=500, trend_intensity=0.96
        )["observation"]
        observation["quantitative_metrics"]["price_dynamics"]["volatility_expansion_index"] = 2.5

        plan = MockDataFactory.create_mock_ai_response(opinion="BULLISH")
        # RR = 350/500 = 0.7 (below chaos-adjusted 0.78)
        plan["tactical_parameters"].update({
            "entry": 60000.0,
            "stop_loss": 59500.0,
            "take_profit": 60350.0
        })

        results = orchestrator.math_checker.verify(plan, observation)
        assert results["compliance_verdict"]["rr_is_valid"] is False
        assert results["rr_verification"]["rr_ratio"] == 0.7
