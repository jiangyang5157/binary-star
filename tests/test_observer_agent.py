import os
import sys
import pytest
import json
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone

# Ensure project root is in path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.agent.observer_agent import ObserverAgent

@pytest.fixture
def mock_config():
    return {
        "observer": {
            "model": "gemini-2.0-flash",
            "prompt_path": "src/agent/prompts/prompt_observer.md",
            "temperature": 0.1,
            "holding_period_days": 1,
            "macro_timeframe": {"interval": "1h", "limit": 100},
            "micro_timeframe": {"interval": "15m", "limit": 100},
            "vp_value_area_pct": 0.7,
            "vp_bins": 50,
            "atr_window": 14,
            "bb_window": 20,
            "bb_std": 2,
            "kc_window": 20,
            "kc_mult": 1.5,
            "vol_ma_window": 20,
            "trend_intensity_threshold": 25,
            "hvn_count": 3,
            "lvn_count": 3,
            "hvn_sensitivity": 0.5,
            "lvn_sensitivity": 0.5,
            "node_min_separation": 1,
            "structural_anchor_count": 2,
            "liquidation_fetch_limit": 100,
            "liquidation_context_limit": 5,
            "order_flow_lookback_bars": 5
        },
        "paths": {
            "data_dir": "data",
            "images_dir": "images"
        }
    }

def test_observer_initialization(mock_config):
    """Verify that ObserverAgent initializes correctly with a valid API key."""
    agent = ObserverAgent(mock_config, symbol="BTCUSDT", api_key="test_key")
    assert agent.symbol == "BTCUSDT"
    assert agent.model_name == "gemini-2.0-flash"

def test_observer_api_key_error(mock_config):
    """Verify that ObserverAgent raises ValueError if api_key is missing."""
    with pytest.raises(ValueError, match="api_key is required"):
        ObserverAgent(mock_config, symbol="BTCUSDT", api_key=None)

@patch("src.data_fetcher.binance_client.BinanceDataFetcher.fetch_historical_klines")
@patch("src.data_fetcher.sentiment.SentimentFetcher.fetch_open_interest")
@patch("src.data_fetcher.sentiment.SentimentFetcher.fetch_long_short_ratio")
@patch("src.data_fetcher.binance_client.BinanceDataFetcher.fetch_liquidations")
@patch("src.analyzer.chart_generator.ChartGenerator.generate_chart")
@patch("google.genai.Client")
def test_observe_mock_flow(mock_genai, mock_gen_chart, mock_liq, mock_ls, mock_oi, mock_klines, mock_config):
    """
    Test the full observation flow using mocks for all external dependencies.
    """
    # Mock Klines return (minimal data for 100 bars)
    mock_klines.return_value = [[0]*12]*100
    mock_oi.return_value = {"openInterest": "1000000"}
    mock_ls.return_value = [{"longShortRatio": "1.5"}]
    mock_liq.return_value = []
    mock_gen_chart.return_value = "data/images/test_chart.png"
    
    # Mock Gemini Response
    mock_response = MagicMock()
    mock_response.text = json.dumps({
        "structural_proximity": "Near POC",
        "anomaly_detection": "None",
        "regime_delta": "Stable",
        "macro_topography": "Range",
        "micro_execution": "Wait"
    })
    mock_genai.return_value.models.generate_content.return_value = mock_response

    agent = ObserverAgent(mock_config, symbol="BTCUSDT", api_key="test_key")
    context = agent.observe(data_dir="data")
    
    assert context["symbol"] == "BTCUSDT"
    assert "metrics" in context
    assert "observations" in context
    assert context["observations"]["structural_proximity"] == "Near POC"

if __name__ == "__main__":
    pytest.main([__file__])
