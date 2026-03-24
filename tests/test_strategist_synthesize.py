import os
import sys
import pytest
import json
from unittest.mock import MagicMock, patch

# Ensure project root is in path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.agent.strategist_agent import StrategistAgent

@pytest.fixture
def mock_config():
    return {
        "strategist": {
            "model": "gemini-2.0-flash",
            "prompt_path": "src/agent/prompts/prompt_strategist.md",
            "temperature_draft": 0.3,
            "temperature_synthesis": 0.1
        },
        "paths": {"data_dir": "data"}
    }

def test_synthesize_success(mock_config):
    """
    Test that synthesize correctly builds the prompt and parses the AI JSON response.
    """
    # 1. Prepare Mock Data
    observation = {
        "symbol": "BTCUSDT", 
        "timestamp": "2026-03-24 22:25:53Z",
        "metrics": {"price": 71000}
    }
    draft_plan = {
        "opinion": "LONG",
        "reasoning": "Bullish divergence"
    }
    critique = {
        "is_veto": False,
        "skepticism_score": 20,
        "adversarial_tone": "Minor concerns about liquidity.",
        "hidden_risk": "None"
    }
    
    # 2. Mock Gemini Response
    expected_output = {
        "opinion": "LONG",
        "confidence": 85,
        "reasoning": "Synthesis complete. Logic holds up after audit.",
        "limit_order": {
            "entry": 70800,
            "take_profit": 72500,
            "stop_loss": 69900
        }
    }
    
    mock_response = MagicMock()
    mock_response.text = json.dumps(expected_output)
    
    # 3. Patch the genai Client
    with patch("google.genai.Client") as MockClient:
        # Setup the mock instance
        mock_instance = MockClient.return_value
        mock_instance.models.generate_content.return_value = mock_response
        
        # Initialize Agent
        agent = StrategistAgent(mock_config, api_key="fake_key")
        
        # 4. Execute synthesize
        result = agent.synthesize(observation, draft_plan, critique)
        
        # 5. Assertions
        assert result["opinion"] == "LONG"
        assert result["confidence"] == 85
        assert "limit_order" in result
        assert result["limit_order"]["entry"] == 70800
        
        # Verify that generate_content was called
        mock_instance.models.generate_content.assert_called_once()
        
        # Verify the client was initialized with the right key
        MockClient.assert_called_once_with(api_key="fake_key")

def test_synthesize_parse_failure(mock_config):
    """
    Test graceful handling of invalid JSON from the AI.
    """
    observation = {"symbol": "BTCUSDT"}
    draft_plan = {"opinion": "LONG"}
    critique = {"is_veto": False}
    
    mock_response = MagicMock()
    mock_response.text = "Invalid JSON string"
    
    with patch("google.genai.Client") as MockClient:
        mock_instance = MockClient.return_value
        mock_instance.models.generate_content.return_value = mock_response
        
        agent = StrategistAgent(mock_config, api_key="fake_key")
        result = agent.synthesize(observation, draft_plan, critique)
        
        assert "error" in result
        assert result["error"] == "JSON parsing failed"
        assert result["raw_response"] == "Invalid JSON string"

if __name__ == "__main__":
    # Allow running directly for quick feedback
    pytest.main([__file__])
