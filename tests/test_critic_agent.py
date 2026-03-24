import os
import sys
import pytest
import json
from unittest.mock import MagicMock, patch

# Ensure project root is in path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.agent.critic_agent import CriticAgent

@pytest.fixture
def mock_config():
    return {
        "critic": {
            "model": "gemini-2.0-flash",
            "prompt_path": "src/agent/prompts/prompt_critic.md",
            "temperature": 0.1
        }
    }

def test_critic_initialization(mock_config):
    """Verify that CriticAgent initializes correctly with a valid API key."""
    agent = CriticAgent(mock_config, api_key="test_key")
    assert agent.model_name == "gemini-2.0-flash"

def test_critic_api_key_error(mock_config):
    """Verify that CriticAgent raises ValueError if api_key is missing."""
    with pytest.raises(ValueError, match="api_key is required"):
        CriticAgent(mock_config, api_key=None)

@patch("google.genai.Client")
def test_audit_mock_flow(mock_genai, mock_config):
    """
    Test the audit flow using mocks for the Gemini API.
    """
    observation = {"symbol": "BTCUSDT"}
    draft_plan = {"opinion": "LONG"}
    
    # Mock Gemini Response
    mock_response = MagicMock()
    mock_response.text = json.dumps({
        "is_veto": False,
        "skepticism_score": 10,
        "adversarial_tone": "Constructive.",
        "hidden_risk": "Low liquidity."
    })
    mock_genai.return_value.models.generate_content.return_value = mock_response

    agent = CriticAgent(mock_config, api_key="test_key")
    result = agent.audit(observation, draft_plan)
    
    assert result["is_veto"] is False
    assert result["skepticism_score"] == 10
    assert "hidden_risk" in result

@patch("google.genai.Client")
def test_audit_json_error_handling(mock_genai, mock_config):
    """Verify that CriticAgent handles invalid JSON response gracefully."""
    mock_response = MagicMock()
    mock_response.text = "INVALID_JSON"
    mock_genai.return_value.models.generate_content.return_value = mock_response

    agent = CriticAgent(mock_config, api_key="test_key")
    result = agent.audit({}, {})
    
    assert result["error"] == "JSON_PARSE_FAILURE"
    assert result["raw_response"] == "INVALID_JSON"

if __name__ == "__main__":
    pytest.main([__file__])
