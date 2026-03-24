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
            "temperature": 0.7
        }
    }

def test_audit_success(mock_config):
    """
    Test that audit correctly builds the prompt and parses the AI JSON response.
    """
    # 1. Prepare Mock Data
    observation = {
        "symbol": "BTCUSDT",
        "metrics": {"price": 71000}
    }
    draft_plan = {
        "opinion": "LONG",
        "reasoning": "Bullish breakout above POC"
    }
    
    # 2. Mock Gemini Response
    expected_critique = {
        "is_veto": False,
        "skepticism_score": 35,
        "adversarial_tone": "The draft overestimates the breakout's strength without considering the thin volume gap above.",
        "hidden_risk": "Liquidity sweep potential at 71500."
    }
    
    mock_response = MagicMock()
    mock_response.text = json.dumps(expected_critique)
    
    # 3. Patch the genai Client
    with patch("google.genai.Client") as MockClient:
        # Setup the mock instance
        mock_instance = MockClient.return_value
        mock_instance.models.generate_content.return_value = mock_response
        
        # Initialize Agent
        agent = CriticAgent(mock_config, api_key="fake_key")
        
        # 4. Execute audit
        result = agent.audit(observation, draft_plan)
        
        # 5. Assertions
        assert result["is_veto"] is False
        assert result["skepticism_score"] == 35
        assert "hidden_risk" in result
        
        # Verify that generate_content was called with the prompt
        mock_instance.models.generate_content.assert_called_once()
        
        # Verify the client was initialized with the right key
        MockClient.assert_called_once_with(api_key="fake_key")

def test_audit_parse_failure(mock_config):
    """
    Test handling of invalid JSON from the AI.
    """
    observation = {"symbol": "BTCUSDT"}
    draft_plan = {"opinion": "LONG"}
    
    mock_response = MagicMock()
    # In the current CriticAgent.audit (Step 3530), it just calls json.loads(response.text)
    # So if it fails, it will raise json.JSONDecodeError
    mock_response.text = "Error: Not a JSON"
    
    with patch("google.genai.Client") as MockClient:
        mock_instance = MockClient.return_value
        mock_instance.models.generate_content.return_value = mock_response
        
        agent = CriticAgent(mock_config, api_key="fake_key")
        
        with pytest.raises(json.JSONDecodeError):
            agent.audit(observation, draft_plan)

if __name__ == "__main__":
    pytest.main([__file__])
