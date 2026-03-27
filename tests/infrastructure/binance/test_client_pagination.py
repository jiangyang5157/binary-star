import pytest
from unittest.mock import MagicMock, patch
from src.infrastructure.binance.client import BinanceFuturesClient

@pytest.fixture
def mock_client():
    """Fixture to provide a BinanceFuturesClient with a mocked internal SDK client."""
    with patch('src.infrastructure.binance.client.UMFutures') as mock_um:
        client = BinanceFuturesClient(api_key="mock_key", api_secret="mock_secret")
        client.client = mock_um.return_value
        return client

def test_fetch_historical_klines_pagination(mock_client):
    """
    Verify that fetch_historical_klines correctly paginates when limit > 1000.
    """
    # Setup mock data for two chunks
    # Chunk 1 (Latest): 1000 candles starting at 2000ms
    chunk1 = [[2000 + i, str(i), "h", "l", "c", "v"] for i in range(1000)]
    # Chunk 2 (Earlier): 500 candles starting at 1500ms
    chunk2 = [[1500 + i, str(i), "h", "l", "c", "v"] for i in range(500)]
    
    # Configure mock to return chunk1 then chunk2
    # Note: Logic is backward-to-forward (endTime shifting)
    mock_client.client.klines.side_effect = [chunk1, chunk2]
    
    # Request 1500 klines
    result = mock_client.fetch_historical_klines("BTCUSDT", "1m", 1500, endTime=3000)
    
    # Verify klines was called twice
    assert mock_client.client.klines.call_count == 2
    
    # Verify result size and ordering
    assert len(result) == 1500
    assert result[0][0] == 1500  # Earliest
    assert result[-1][0] == 2999 # Latest
    
    # Verify calls arguments
    calls = mock_client.client.klines.call_args_list
    # First call: limit 1000, endTime 3000
    assert calls[0].kwargs['limit'] == 1000
    assert calls[0].kwargs['endTime'] == 3000
    # Second call: limit 500, endTime = chunk1[0][0] - 1 = 2000 - 1 = 1999
    assert calls[1].kwargs['limit'] == 500
    assert calls[1].kwargs['endTime'] == 1999

def test_fetch_historical_klines_no_pagination_for_small_limit(mock_client):
    """Verify that it does not paginate for limits <= 1000."""
    mock_data = [[1000, "o", "h", "l", "c", "v"]]
    mock_client.client.klines.return_value = mock_data
    
    result = mock_client.fetch_historical_klines("BTCUSDT", "1m", 500)
    
    assert len(result) == 1
    assert mock_client.client.klines.call_count == 1
    mock_client.client.klines.assert_called_with(symbol="BTCUSDT", interval="1m", limit=500)

def test_fetch_historical_klines_forward_pagination(mock_client):
    """
    Verify that it uses forward pagination when startTime is provided.
    """
    # Chunk 1 (Earlier): 1000 candles starting at 1000ms
    chunk1 = [[1000 + i, str(i), "h", "l", "c", "v"] for i in range(1000)]
    # Chunk 2 (Later): 500 candles starting at 2000ms
    # Note: last ts of chunk1 is 1999. Next startTime should be 2000.
    chunk2 = [[2000 + i, str(i), "h", "l", "c", "v"] for i in range(500)]
    
    mock_client.client.klines.side_effect = [chunk1, chunk2]
    
    # Request 1500 klines starting from 1000ms
    result = mock_client.fetch_historical_klines("BTCUSDT", "1m", 1500, startTime=1000)
    
    assert mock_client.client.klines.call_count == 2
    assert len(result) == 1500
    assert result[0][0] == 1000  # Earliest
    assert result[-1][0] == 2499 # Latest
    
    calls = mock_client.client.klines.call_args_list
    # First call uses initial startTime
    assert calls[0].kwargs['startTime'] == 1000
    # Second call uses latest_open + 1 = 1999 + 1 = 2000
    assert calls[1].kwargs['startTime'] == 2000
