import unittest
from unittest.mock import MagicMock, patch
import os
import json
from datetime import datetime
from src.infrastructure.notifications.email_notifier import StrategyNotifier, StrategyEmailTemplate, NotificationConfig

# Constants for raw JSON parity in mock data
null = None
true = True
false = False

class TestStrategyNotifier(unittest.TestCase):
    def setUp(self):
        self.mock_bullish_order_data = {
  "observation": {
    "symbol": "BTCUSDT",
    "timestamp": "2026-03-25T04:31:30.609001Z",
    "observation_specs": {
      "macro": {
        "interval": "1h",
        "limit": 336
      },
      "micro": {
        "interval": "15m",
        "limit": 192
      }
    },
    "visual_assets": {
      "macro_snapshot": "data/tests/klines/BTCUSDT_1h_klines_20260325_043130.png",
      "micro_snapshot": "data/tests/klines/BTCUSDT_15m_klines_20260325_043130.png"
    },
    "quantitative_metrics": {
      "price_dynamics": {
        "current_price": 70800.1,
        "atr_macro": 545.1142857142868,
        "atr_micro": 204.84285714285562,
        "vol_ratio": "1.50",
        "wick_skewness": "0.54",
        "vol_of_vol": "0.96"
      },
      "structural_anchors": {
        "poc_dist_atr": "1.47",
        "vah_dist_atr": "-8.69",
        "val_dist_atr": "5.04"
      },
      "volume_topography": {
        "poc": 69996.659,
        "vah": 75534.95866666666,
        "val": 68053.90466666667,
        "anchors_above": [
          {
            "price": 69996.66,
            "strength": 1.0,
            "type": "HVN"
          },
          {
            "price": 70924.54,
            "vacuum_score": 0.019,
            "type": "LVN"
          },
          {
            "price": 74027.15,
            "strength": 0.391,
            "type": "HVN"
          }
        ],
        "anchors_below": [
          {
            "price": 69097.77,
            "vacuum_score": 0.021,
            "type": "LVN"
          }
        ]
      },
      "market_regime": {
        "volatility_regime": "NORMAL",
        "squeeze_factor": 1.5771,
        "market_regime": "RANGING",
        "trend_intensity": 0.0887,
        "skewness": 0.2249,
        "volume_breakout_ratio": 0.24
      },
      "sentiment_signals": {
        "oi_nominal": 85943.281,
        "oi_delta_macro": "+0.01%",
        "oi_delta_micro": "+0.04%",
        "ls_ratio_macro": "1.5530",
        "ls_ratio_micro": "1.5426",
        "net_taker_delta": "128.0350",
        "cvd_trend": "UPWARD",
        "funding_rate": "0.00002310",
        "liquidation_clusters": null
      }
    },
    "semantic_analysis": {
      "structural_gravity": "Price is currently positioned at 70800.1, maintaining a positive displacement from the primary structural anchor, the POC at 69996.66, with a poc_dist_atr of 1.47. This indicates price has transitioned from the maximal high-volume node (HVN) toward the upper quadrant of the macro value area, though it remains significantly below the VAH at 75534.96 (vah_dist_atr of -8.69). The visual evidence in the macro chart shows price oscillating within the range defined by the VAL (68053.90) and VAH, currently finding a local equilibrium above the central gravity of the POC. This positioning suggests price is currently 'anchored' to the upper boundary of the high-volume core rather than trending toward the extremes.",
      "topographical_friction": "The market topography is dominated by a maximal strength HVN at 69996.66 (strength 1.0), which has acted as the primary rotational axis for the observed period. Immediately above the current price lies an LVN at 70924.54 with a low vacuum_score of 0.019, suggesting a zone of minimal historical friction that price is currently testing as resistance. Should price clear this minor liquidity gap, the next significant structural friction point is identified at the 74027.15 HVN (strength 0.391). Below the current level, an LVN at 69097.77 represents a potential liquidity vacuum between the POC and the VAL where price could accelerate if the POC fails to hold.",
      "regime_volatility": "The current market regime is classified as 'RANGING' with a very low trend_intensity of 0.0887, confirming the lack of directional conviction seen in the macro chart's lateral movement. However, the vol_ratio of 1.50 indicates that micro-volatility is expanding relative to the macro baseline, even as the vol_of_vol remains stable at 0.96. The squeeze_factor of 1.5771 suggests that Bollinger Bands are currently outside Keltner Channels, indicating an absence of a volatility squeeze and a preference for mean-reverting behavior. This is further corroborated by the volume_breakout_ratio of 0.24, which shows no significant volume-driven expansion at this stage.",
      "sentiment_flow": "Sentiment signals reveal a persistent long bias, with an ls_ratio_macro of 1.5530 and a positive funding_rate of 0.00002310. The cvd_trend is currently 'UPWARD' with a net_taker_delta of 128.0350, suggesting that aggressive market buyers are providing the current upward pressure against passive sellers. Despite this aggressive flow, the oi_delta_macro is nearly flat at +0.01%, indicating that the current move is likely driven by existing position rotation rather than a massive influx of new capital. This creates a state of 'Logical Friction' where aggressive buying is present but structural open interest remains stagnant, often characteristic of a range-bound environment.",
      "micro_interactive": "On the 15m micro-scale, price is consolidating within a tight range, reflected by a wick_skewness of 0.54, which denotes near-perfect indecision at the current level. The micro-ATR of 204.84 highlights the compressed nature of recent candles compared to the macro-ATR of 545.11, suggesting a local volatility contraction. Visually, the micro chart shows a series of small-bodied candles forming a descending flag pattern just above the 70,000 psychological level. This consolidation is occurring with a volume_breakout_ratio of only 0.24, suggesting that the local breakout attempt lacks the necessary participation to sustain a trend beyond the immediate range.",
      "synthesized_topography": "The BTCUSDT topography is currently defined by a mean-reverting rotation around the 69996.66 POC within a broader range bounded by 68053.90 and 75534.96. While aggressive taker flow (cvd_trend UPWARD) has pushed price to 70800.1, the lack of open interest expansion (oi_delta_macro +0.01%) and low trend_intensity (0.0887) suggest this is a low-conviction move within a larger consolidation. Price is currently navigating an LVN at 70924.54; failure to establish acceptance above this level likely results in a return to the high-density friction of the POC. The overall state is one of micro-volatility expansion (vol_ratio 1.50) within a structurally stagnant macro environment."
    }
  },
  "draft": {
    "opinion": "NEUTRAL",
    "confidence": 85,
    "limit_order": null,
    "reasoning": "The market is currently in a RANGING regime with a trend_intensity of 0.0887, indicating a lack of directional conviction. Crucially, the volume_breakout_ratio is 0.24, which fails the mandatory 2.0 threshold required for momentum validation and trend confirmation under the operating protocol. While the CVD trend is upward and price remains above the POC (69996.66), the stagnant Open Interest (+0.01%) suggests the current move is driven by position rotation rather than new capital inflow. Price is currently testing an LVN at 70924.54; without the necessary volume expansion, a sustained breakout toward the VAH is statistically improbable. The neutrality mandate is triggered due to the failure of momentum validation and the contradictory nature of aggressive taker flow against flat structural participation.",
    "critic_impact": null
  },
  "critique": {
    "is_veto": false,
    "skepticism_score": 78,
    "adversarial_tone": "The draft adopts a cowardly 'Neutral' stance that mistakes structural stagnation for safety. It pathetically ignores the toxic Long/Short ratio of 1.55, which, coupled with a positive funding rate and an upward CVD on flat Open Interest, signals a classic 'Absorption Trap.' The strategist is blind to the fact that aggressive market buyers are being absorbed by passive limit sellers at the 70924.54 LVN, creating a prime environment for a violent mean-reversion sweep.",
    "hidden_risk": "The 'Long Squeeze' Liquidity Cascade. With the LS ratio heavily skewed (1.55) and price hovering just 1.47 ATRs above the POC, a failure to penetrate the 70924 LVN will likely trigger a cascading stop-loss hunt. The 69097.77 LVN acts as a gravitational sink; if the POC at 69996 fails, the lack of historical volume between the POC and the VAL (68053) will accelerate a downside flush to liquidate the crowded retail long positions."
  },
  "final_decision": {
    "opinion": "BULLISH",
    "confidence": 80,
    "limit_order": {
        "entry": 70100.0,
        "take_profit": 73000.0,
        "stop_loss": 69000.0,
        "holding_time_hours": 24.0
    },
    "reasoning": "Confidence is at 80% because price cleared the 69996.66 POC with strong taker delta. A limit buy at 70100 is positioned at the HVN support with a target toward the 73000 LVN gap."
  }
}
        self.mock_neutral_no_order_data = {
  "observation": {
    "symbol": "BTCUSDT",
    "timestamp": "2026-03-25T04:31:30.609001Z",
    "observation_specs": {
      "macro": {
        "interval": "1h",
        "limit": 336
      },
      "micro": {
        "interval": "15m",
        "limit": 192
      }
    },
    "visual_assets": {
      "macro_snapshot": "data/tests/klines/BTCUSDT_1h_klines_20260325_043130.png",
      "micro_snapshot": "data/tests/klines/BTCUSDT_15m_klines_20260325_043130.png"
    },
    "quantitative_metrics": {
      "price_dynamics": {
        "current_price": 70800.1,
        "atr_macro": 545.1142857142868,
        "atr_micro": 204.84285714285562,
        "vol_ratio": "1.50",
        "wick_skewness": "0.54",
        "vol_of_vol": "0.96"
      },
      "sentiment_signals": {
        "oi_nominal": 85943.281,
        "oi_delta_macro": "+0.01%",
        "oi_delta_micro": "+0.04%",
        "ls_ratio_macro": "1.5530",
        "ls_ratio_micro": "1.5426",
        "net_taker_delta": "128.0350",
        "cvd_trend": "UPWARD",
        "funding_rate": "0.00002310",
        "liquidation_clusters": null
      }
    },
    "semantic_analysis": {
      "topographical_friction": "The market topography is dominated by a maximal strength HVN at 69996.66 (strength 1.0), which has acted as the primary rotational axis for the observed period. Immediately above the current price lies an LVN at 70924.54 with a low vacuum_score of 0.019, suggesting a zone of minimal historical friction that price is currently testing as resistance. Should price clear this minor liquidity gap, the next significant structural friction point is identified at the 74027.15 HVN (strength 0.391). Below the current level, an LVN at 69097.77 represents a potential liquidity vacuum between the POC and the VAL where price could accelerate if the POC fails to hold."
    }
  },
  "draft": {
    "opinion": "NEUTRAL",
    "confidence": 85,
    "limit_order": null,
    "reasoning": "The market is currently in a RANGING regime with a trend_intensity of 0.0887, indicating a lack of directional conviction. Crucially, the volume_breakout_ratio is 0.24, which fails the mandatory 2.0 threshold required for momentum validation and trend confirmation under the operating protocol. While the CVD trend is upward and price remains above the POC (69996.66), the stagnant Open Interest (+0.01%) suggests the current move is driven by position rotation rather than new capital inflow. Price is currently testing an LVN at 70924.54; without the necessary volume expansion, a sustained breakout toward the VAH is statistically improbable. The neutrality mandate is triggered due to the failure of momentum validation and the contradictory nature of aggressive taker flow against flat structural participation.",
    "critic_impact": null
  },
  "critique": {
    "is_veto": false,
    "skepticism_score": 78,
    "adversarial_tone": "The draft adopts a cowardly 'Neutral' stance that mistakes structural stagnation for safety. It pathetically ignores the toxic Long/Short ratio of 1.55, which, coupled with a positive funding rate and an upward CVD on flat Open Interest, signals a classic 'Absorption Trap.' The strategist is blind to the fact that aggressive market buyers are being absorbed by passive limit sellers at the 70924.54 LVN, creating a prime environment for a violent mean-reversion sweep.",
    "hidden_risk": "The 'Long Squeeze' Liquidity Cascade. With the LS ratio heavily skewed (1.55) and price hovering just 1.47 ATRs above the POC, a failure to penetrate the 70924 LVN will likely trigger a cascading stop-loss hunt. The 69097.77 LVN acts as a gravitational sink; if the POC at 69996 fails, the lack of historical volume between the POC and the VAL (68053) will accelerate a downside flush to liquidate the crowded retail long positions."
  },
  "final_decision": {
    "opinion": "NEUTRAL",
    "confidence": 80,
    "limit_order": null,
    "reasoning": "Confidence is at 80% because price cleared the 69996.66 POC with strong taker delta. A limit buy at 70100 is positioned at the HVN support with a target toward the 73000 LVN gap."
  }
        }
        self.mock_low_confidence_data = {
            "observation": {"symbol": "BTCUSDT", "visual_assets": {}},
            "final_decision": {"opinion": "NEUTRAL", "confidence": 50, "reasoning": "Weak signal"}
        }

    def test_template_rendering(self):
        """Verify that the HTML template renders with key data points."""
        html = StrategyEmailTemplate.render(self.mock_bullish_order_data)
        self.assertIn("BTCUSDT Signal Detected", html)
        self.assertIn("MARKET BULLISH", html)
        self.assertIn("70800.1", html)
        self.assertIn("80%", html)
        self.assertIn("Refined Strategic Reasoning", html)

    def test_template_rendering_neutral(self):
        """Verify that the HTML template handles NEUTRAL opinion with no limit_order."""
        html = StrategyEmailTemplate.render(self.mock_neutral_no_order_data)
        self.assertIn("MARKET NEUTRAL", html)
        # The order block uses a specific background color and 3-column grid
        self.assertNotIn("display: grid; grid-template-columns: repeat(3, 1fr); gap: 15px; text-align: center;", html)
        self.assertIn("Refined Strategic Reasoning", html)
        
        # Also generate a preview for visual confirmation as requested
        notifier = StrategyNotifier(data_root="data/tests")
        notifier.notify_strategy("BTCUSDT", self.mock_neutral_no_order_data)

    def test_confidence_filter(self):
        """Verify that the Notifier skips dispatch when confidence < 60%."""
        notifier = StrategyNotifier(data_root="data/tests")
        notifier.dispatcher.dispatch = MagicMock()
        
        success = notifier.notify_strategy("BTCUSDT", self.mock_low_confidence_data)
        
        self.assertFalse(success)
        notifier.dispatcher.dispatch.assert_not_called()

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
            
            result = notifier.notify_strategy("BTCUSDT", self.mock_bullish_order_data)
            
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
        path = notifier.save_html_preview("TEST_SYMBOL", html, {})
        
        self.assertIsNotNone(path)
        self.assertTrue(os.path.exists(path))
        self.assertIn("data/tests/html", path)
        
        # Cleanup
        if os.path.exists(path):
            os.remove(path)

if __name__ == '__main__':
    unittest.main()
