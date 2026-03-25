import os
import pytest
from unittest.mock import MagicMock, patch
from src.data.remote.binance_client import BinanceFuturesClient
from binance.error import ClientError

# Manually load .env for integration tests
def load_env():
    env_path = os.path.join(os.getcwd(), '.env')
    if os.path.exists(env_path):
        with open(env_path, 'r') as f:
            for line in f:
                if '=' in line and not line.startswith('#'):
                    key, value = line.strip().split('=', 1)
                    os.environ[key] = value.strip('"').strip("'")

load_env()

@pytest.fixture
def mock_client():
    """Fixture to provide a BinanceFuturesClient with a mocked internal SDK client."""
    with patch('src.data.remote.binance_client.UMFutures') as mock_um:
        client = BinanceFuturesClient(api_key="mock_key", api_secret="mock_secret")
        # Access the internal client instance
        client.client = mock_um.return_value
        return client

def test_fetch_historical_klines_success(mock_client):
    """Verify that klines are fetched and returned correctly."""
    mock_data = [["123", "open", "high", "low", "close", "vol"]]
    mock_client.client.klines.return_value = mock_data
    
    result = mock_client.fetch_historical_klines("BTCUSDT", "1h", 10)
    assert result == mock_data
    mock_client.client.klines.assert_called_once_with(symbol="BTCUSDT", interval="1h", limit=10)

def test_fetch_order_book_success(mock_client):
    """Verify that order book data is returned."""
    mock_data = {"lastUpdateId": 1, "bids": [], "asks": []}
    mock_client.client.depth.return_value = mock_data
    
    result = mock_client.fetch_order_book("BTCUSDT", limit=100)
    assert result == mock_data
    mock_client.client.depth.assert_called_once_with(symbol="BTCUSDT", limit=100)

def test_fetch_open_interest_current(mock_client):
    """Verify that current open interest is fetched."""
    mock_data = {"symbol": "BTCUSDT", "openInterest": "100.0"}
    mock_client.client.open_interest.return_value = mock_data
    
    result = mock_client.fetch_open_interest("BTCUSDT")
    assert result == mock_data
    mock_client.client.open_interest.assert_called_once_with(symbol="BTCUSDT")

def test_fetch_long_short_ratio_success(mock_client):
    """Verify that long/short ratio is fetched."""
    mock_data = [{"symbol": "BTCUSDT", "longShortRatio": "1.5"}]
    mock_client.client.long_short_account_ratio.return_value = mock_data
    
    result = mock_client.fetch_long_short_ratio("BTCUSDT", "1h")
    assert result == mock_data
    mock_client.client.long_short_account_ratio.assert_called_once()

def test_error_handling_returns_defaults(mock_client):
    """Verify that ClientError is handled and defaults are returned."""
    mock_client.client.klines.side_effect = ClientError(400, "Bad Request", {"code": -1102}, {})
    
    result = mock_client.fetch_historical_klines("INVALID", "1h", 10)
    assert result == []

# --- Conditional Integration Test ---

@pytest.mark.skipif(
    not os.environ.get("BINANCE_API_KEY") or not os.environ.get("BINANCE_API_SECRET"),
    reason="Binance API keys not found in environment"
)
def test_real_api_connectivity():
    """
    Integration test: Verifies real connectivity to Binance (Public data).
    This only runs if API keys are set in the environment.
    """
    client = BinanceFuturesClient()
    # Fetch klines for BTCUSDT
    result = client.fetch_historical_klines("BTCUSDT", "1h", 2)
    assert isinstance(result, list)
    assert len(result) > 0
    print(f"\nReal API Result (Klines): {result[0]}")
