import sys
import os
import unittest
from unittest.mock import MagicMock, patch

# Add the 'src' directory to the Python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.agent.trader_agent import TraderAgent

class TestTraderAgentLogic(unittest.TestCase):
    def setUp(self):
        # Prevent actual API calls during tests by patching where necessary
        os.environ["GEMINI_API_KEY"] = "mock-key"
        self.agent = TraderAgent(
            model_name="mock-model",
            temp_pass1=1.0,
            temp_pass2=1.0,
            temp_pass3=0.7
        )

    @patch('google.genai.Client')
    def test_multi_pass_reasoning(self, mock_client_class):
        """
        Tests the 3-pass reasoning loop: Initial -> Red Team -> Final
        """
        # Mock the GenAI client and its models.generate_content method
        mock_client_instance = MagicMock()
        mock_client_class.return_value = mock_client_instance
        
        # In the new SDK, it's client.models.generate_content
        mock_models = MagicMock()
        mock_client_instance.models = mock_models
        
        # Define mock responses for each pass
        mock_responses = [
            MagicMock(text='{"action": "BUY", "confidence": 70, "reasoning": "Initial thought", "reasoning_zh": "初始想法"}'),
            MagicMock(text="PASS 2 (RED TEAM): Risky because of hidden resistance at 70k."),
            MagicMock(text='{"action": "HOLD", "confidence": 90, "reasoning": "Pivoting to HOLD after red team highlighted resistance.", "reasoning_zh": "改位HOLD"}')
        ]
        mock_models.generate_content.side_effect = mock_responses

        # Context data
        context = {
            "symbol": "BTCUSDT",
            "price": 65000,
            "review_window_days": 7
        }
        
        # Run analysis
        print("    Running Multi-Pass Analysis (Mocked Client)...")
        # We need to manually set the client since TraderAgent initializes it in __init__
        self.agent.client = mock_client_instance
        
        # Correct arguments for TraderAgent.analyze
        result_str = self.agent.analyze(
            symbol=context["symbol"],
            chart_image_paths=["mock_chart.png"],
            context_data=context
        )

        # Verify 3 calls were made to generate_content
        self.assertEqual(mock_models.generate_content.call_count, 3)
        
        # Verify the final output structure (parse JSON string)
        import json
        result = json.loads(result_str)
        self.assertIsInstance(result, dict)
        self.assertEqual(result['action'], "HOLD")
        self.assertIn('reasoning_zh', result)
        print(f"    Agent effectively pivoted to {result['action']} based on Red Team feedback.")

if __name__ == "__main__":
    unittest.main()
