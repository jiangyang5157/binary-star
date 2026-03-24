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
        }
    }

def test_draft_success(mock_config):
    """
    Test Pass 1: Drafting.
    """
    observation = {"symbol": "BTCUSDT"}
    draft_response = {"opinion": "SHORT", "reasoning": "Overbought condition"}
    
    mock_response = MagicMock()
    mock_response.text = json.dumps(draft_response)
    
    with patch("google.genai.Client") as MockClient:
        mock_instance = MockClient.return_value
        mock_instance.models.generate_content.return_value = mock_response
        
        agent = StrategistAgent(mock_config, api_key="test_key")
        result = agent.draft(observation)
        
        assert result["opinion"] == "SHORT"
        assert MockClient.call_args[1]["api_key"] == "test_key"

def test_synthesize_success(mock_config):
    """
    Test Pass 3: Synthesis.
    """
    observation = {"symbol": "BTCUSDT"}
    draft_plan = {"opinion": "SHORT"}
    critique = {"is_veto": False, "adversarial_tone": "Agree with short."}
    
    final_output = {
        "opinion": "SHORT",
        "confidence": 90,
        "reasoning": "Audit passed.",
        "limit_order": {"entry": 72000, "take_profit": 70000, "stop_loss": 72500}
    }
    
    mock_response = MagicMock()
    mock_response.text = json.dumps(final_output)
    
    with patch("google.genai.Client") as MockClient:
        mock_instance = MockClient.return_value
        mock_instance.models.generate_content.return_value = mock_response
        
        agent = StrategistAgent(mock_config, api_key="test_key")
        result = agent.synthesize(observation, draft_plan, critique)
        
        assert result["opinion"] == "SHORT"
        assert result["limit_order"]["take_profit"] == 70000

def test_api_key_validation(mock_config):
    """
    Test that ValueError is raised if api_key is empty.
    """
    with pytest.raises(ValueError, match="api_key is required"):
        StrategistAgent(mock_config, api_key=None)

if __name__ == "__main__":
    pytest.main([__file__])
