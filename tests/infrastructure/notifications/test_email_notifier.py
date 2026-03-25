import unittest
from unittest.mock import MagicMock, patch
import os
import json
from datetime import datetime
from src.infrastructure.notifications.email_notifier import StrategyNotifier, StrategyEmailTemplate, NotificationConfig

class TestStrategyNotifier(unittest.TestCase):
    def setUp(self):
        # Sample mock data based on recent BTCUSDT run (2026-03-25 04:31:30)
        self.mock_strategy_data = {
          "observation": {
            "symbol": "BTCUSDT",
            "timestamp": "2026-03-25T04:31:30.609001Z",
            "visual_assets": {
              "macro_snapshot": "data/tests/klines/BTCUSDT_1h_klines_20260325_043130.png",
              "micro_snapshot": "data/tests/klines/BTCUSDT_15m_klines_20260325_043130.png"
            },
            "quantitative_metrics": {
              "price_dynamics": {
                "current_price": 70800.1,
                "vol_ratio": "1.50",
                "wick_skewness": "0.54"
              },
              "market_regime": {
                "market_regime": "RANGING",
                "trend_intensity": 0.0887,
                "squeeze_factor": 1.5771
              }
            }
          },
          "final_decision": {
            "opinion": "NEUTRAL",
            "confidence": 90,
            "reasoning": "The BTCUSDT pair is currently exhibiting a RANGING regime with a trend_intensity of 0.0887... neutrality mandate is strictly enforced."
          }
        }

    def test_template_rendering(self):
        """Verify that the HTML template renders with key data points."""
        html = StrategyEmailTemplate.render(self.mock_strategy_data)
        self.assertIn("BTCUSDT Strategy Report", html)
        self.assertIn("MARKET NEUTRAL", html)
        self.assertIn("70800.1", html)
        self.assertIn("90%", html)
        self.assertIn("Refined Strategic Reasoning", html)

    @patch('smtplib.SMTP')
    def test_notification_dispatch(self, mock_smtp):
        """Verify that the dispatcher attempts to send email when enabled."""
        # Setup mock config
        config = NotificationConfig(
            smtp_server="smtp.test.com",
            smtp_port=587,
            sender_email="test@test.com",
            sender_password="password",
            enabled=True
        )
        
        with patch('src.infrastructure.notifications.email_notifier.NotificationConfig.from_env', return_value=config):
            notifier = StrategyNotifier(data_root="data/tests")
            # Mock dispatcher to avoid real SMTP
            notifier.dispatcher.dispatch = MagicMock(return_value=True)
            
            result = notifier.notify_strategy("BTCUSDT", self.mock_strategy_data)
            
            self.assertTrue(result)
            notifier.dispatcher.dispatch.assert_called_once()
            
            # Check if preview was saved in data/tests/html
            preview_dir = "data/tests/html"
            files = os.listdir(preview_dir)
            self.assertTrue(any("BTCUSDT_strategy_preview" in f for f in files))

    def test_local_preview_generation(self):
        """Verify that the HTML preview is saved to the correct directory."""
        notifier = StrategyNotifier(data_root="data/tests")
        html = "<html>Test</html>"
        path = notifier.save_html_preview("TEST_SYMBOL", html)
        
        self.assertIsNotNone(path)
        self.assertTrue(os.path.exists(path))
        self.assertIn("data/tests/html", path)
        
        # Cleanup
        if os.path.exists(path):
            os.remove(path)

if __name__ == '__main__':
    unittest.main()
