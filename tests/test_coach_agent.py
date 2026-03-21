import sys
import os
import unittest
from unittest.mock import MagicMock, patch

# Add the 'src' directory to the Python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.agent.coach_agent import CoachAgent

class TestCoachAgent(unittest.TestCase):
    def setUp(self):
        os.environ["GEMINI_API_KEY"] = "mock-key"
        self.coach = CoachAgent(
            model_name="mock-model",
            prompts_dir=os.path.join(os.path.dirname(__file__), '..', 'src', 'agent', 'prompts'),
            prompt_filename="prompt_coach.txt",
            temperature=1.0
        )

    @patch('google.genai.Client')
    def test_coaching_session(self, mock_client_class):
        mock_client_instance = MagicMock()
        mock_client_class.return_value = mock_client_instance
        
        mock_models = MagicMock()
        mock_client_instance.models = mock_models
        
        mock_response = MagicMock(text='{"batch_analysis": "Test Analysis", "master_prompt_patch": []}')
        mock_models.generate_content.return_value = mock_response

        # Mock review reports
        reports = [{
            "prediction": {"content": {"action": "BUY"}},
            "actual_market_outcome": {"price_change_pct": 5.0},
            "analysis": {"evaluation_score": 80}
        }]
        
        # Run coaching
        self.coach.client = mock_client_instance
        result_str = self.coach.coaching_session(
            review_reports=reports,
            current_config={},
            base_prompt="Old Prompt"
        )

        self.assertIn("Test Analysis", result_str)
        self.assertEqual(mock_models.generate_content.call_count, 1)

if __name__ == "__main__":
    unittest.main()
