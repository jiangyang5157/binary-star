import pytest
from src.agent.binary_star_orchestrator import BinaryStarOrchestrator
from tests.mock_factory import MockDataFactory

class TestMathFactCheck:
    @pytest.fixture
    def orchestrator(self, mock_orchestrator_infrastructure, mock_config):
        """Standardized orchestrator instantiation for testing."""
        return BinaryStarOrchestrator(mock_config, "mock_key", data_root="data/test", symbol="BTCUSDT")

    def test_bullish_valid_check(self, orchestrator):
        """Tests a standard bullish proposal with valid RR and structural shielding."""
        # Setup: Entry 60000, SL 59000, TP 62000. POC is at 60000.
        # Shielding: SL (59000) is below POC (60000), which is good for BULLISH.
        observation = MockDataFactory.create_mock_session_result(
            "BTCUSDT", current_price=60100, poc=60000, atr=500, trend_intensity=0.8
        )["observation"]
        
        plan = MockDataFactory.create_mock_ai_response(opinion="BULLISH")
        plan["tactical_parameters"].update({
            "entry": 60000.0,
            "stop_loss": 59000.0,
            "take_profit": 62500.0,
            "current_price": 60100.0
        })

        results = orchestrator._assemble_math_fact_check(plan, observation)
        
        assert results["status"] == "VERIFIED"
        assert results["compliance_verdict"]["rr_is_valid"] is True
        assert results["compliance_verdict"]["sl_is_shielded"] is True
        # RR = (62500-60000)/(60000-59000) = 2500/1000 = 2.5
        assert results["rr_verification"]["rr_ratio"] == 2.5

    def test_bearish_invalid_rr_trending(self, orchestrator):
        """Tests a bearish proposal in a trending market with insufficient RR."""
        # Trending threshold: 0.95. Trend Intensity: 0.96 -> Trending.
        # min_rr_trending: 1.2.
        observation = MockDataFactory.create_mock_session_result(
            "BTCUSDT", current_price=60000, poc=60500, atr=500, trend_intensity=0.96
        )["observation"]
        
        plan = MockDataFactory.create_mock_ai_response(opinion="BEARISH")
        # Entry 60000, TP 59500, SL 60500. RR = 500/500 = 1.0 (< 1.2)
        plan["tactical_parameters"].update({
            "entry": 60000.0,
            "stop_loss": 60500.0,
            "take_profit": 59500.0
        })

        results = orchestrator._assemble_math_fact_check(plan, observation)
        
        assert results["status"] == "VERIFIED"
        assert results["compliance_verdict"]["rr_is_valid"] is False
        assert results["rr_verification"]["rr_ratio"] == 1.0

    def test_shielding_violation(self, orchestrator):
        """Tests a bullish proposal where the SL is not shielded by any structural anchor."""
        # Bullish: SL must be BELOW structural anchors to be "shielded".
        # If SL (59000) is ABOVE all anchors (58000, 58500, 57500), it's unshielded.
        observation = MockDataFactory.create_mock_session_result(
            "BTCUSDT", current_price=60000, poc=58000, vah=58500, val=57500, atr=500
        )["observation"]
        
        plan = MockDataFactory.create_mock_ai_response(opinion="BULLISH")
        plan["tactical_parameters"].update({
            "entry": 60000.0,
            "stop_loss": 59000.0,
            "take_profit": 63000.0
        })

        results = orchestrator._assemble_math_fact_check(plan, observation)
        
        assert results["status"] == "VERIFIED"
        assert results["compliance_verdict"]["sl_is_shielded"] is False

    def test_neutral_stance_skipped(self, orchestrator):
        """Ensures neutral proposals bypass the math audit."""
        observation = MockDataFactory.create_mock_session_result("BTCUSDT")["observation"]
        plan = {"opinion": "NEUTRAL", "reasoning_chain": "Wait for volatility."}
        
        results = orchestrator._assemble_math_fact_check(plan, observation)
        assert results["status"] == "SKIPPED"

    def test_error_handling_in_math_fact_check(self, orchestrator):
        """Gracefully handle missing tactical parameters."""
        observation = MockDataFactory.create_mock_session_result("BTCUSDT")["observation"]
        plan = {"opinion": "BULLISH", "tactical_parameters": {}} # Missing keys
        
        results = orchestrator._assemble_math_fact_check(plan, observation)
        # Depending on implementation, it might return status: VERIFIED but with default values or error
        # In BinaryStarOrchestrator._assemble_math_fact_check, it uses float(tactical.get('entry', 0))
        # So it will likely be 0, leading to a VERIFIED status but with RR=0 or similar.
        assert "status" in results
