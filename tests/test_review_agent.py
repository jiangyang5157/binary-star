import sys
import os
import json
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.agent.reviewer_agent import ReviewerAgent


class TestReviewerAgent(unittest.TestCase):
    def setUp(self):
        os.environ["GEMINI_API_KEY"] = "mock-key"
        self.reviewer = ReviewerAgent(
            model_name="mock-model",
            prompts_dir=os.path.join(os.path.dirname(__file__), '..', 'src', 'agent', 'prompts')
        )

    @patch('google.genai.Client')
    def test_review_with_mock(self, mock_client_class):
        """
        Tests the Reviewer Agent's review method with fully mocked Gemini API.
        """
        mock_client_instance = MagicMock()
        mock_client_class.return_value = mock_client_instance

        mock_models = MagicMock()
        mock_client_instance.models = mock_models

        mock_response = MagicMock(text=json.dumps({
            "evaluation_score": 35,
            "tp_sl_result": "SL_HIT",
            "trade_post_mortem": "Agent A was trapped in a fakeout breakout above POC. Key lesson: always wait for volume confirmation.",
            "trade_post_mortem_zh": "Agent A 被假突破困住了。核心教训：必须等待成交量确认。"
        }))
        mock_models.generate_content.return_value = mock_response

        # Manually set the mocked client
        self.reviewer.client = mock_client_instance

        historical_prediction = {
            "timestamp": "2026-03-01T12:00:00Z",
            "action": "BUY",
            "current_price": 65000,
            "take_profit": 72000,
            "stop_loss": 63000,
            "confidence": 85,
            "reasoning": "Price broke out above POC on high volume.",
            "reasoning_zh": "价格在高成交量下突破了POC。"
        }

        actual_outcome = {
            "start_price": 65000,
            "max_price_reached": 68000,
            "min_price_reached": 62000,
            "final_close_price": 63000,
            "price_change_pct": -3.08,
            "max_drawup_pct": 4.62,
            "max_drawdown_pct": -4.62,
            "outcome_period_bars": 672
        }

        current_config = {
            "symbol": "BTCUSDT",
            "prediction": {
                "trade_horizon_days": 7,
                "macro_timeframe": {"interval": "4h", "limit": 500},
                "micro_timeframe": {"interval": "1h", "limit": 240},
            },
            "agent": {
                "reviewer_model": "mock-model",
                "review_temperature": 1.0
            }
        }

        result_str = self.reviewer.review(
            historical_prediction=historical_prediction,
            actual_outcome=actual_outcome,
            config=current_config,
            chart_image_paths=[],
            base_prompt="Mock base prompt for testing."
        )

        # Verify the API was called exactly once
        self.assertEqual(mock_models.generate_content.call_count, 1)

        # Verify the output is valid JSON
        result = json.loads(result_str)
        self.assertIsInstance(result, dict)
        self.assertIn("evaluation_score", result)
        self.assertEqual(result["evaluation_score"], 35)
        self.assertIn("trade_post_mortem_zh", result)


if __name__ == "__main__":
    unittest.main()
