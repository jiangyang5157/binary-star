import logging
from typing import Dict, List, Any
from binance.um_futures import UMFutures
from binance.error import ClientError

# Set up standard logging module for our classes
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

class BinanceDataFetcher:
    """
    A unified wrapper for fetching high-integrity Market Data from Binance Futures.
    No API Key is required because we only fetch public market data endpoints.
    
    This class is the 'Technical Source' for Agent A, providing raw price 
    action and order book liquidity data.
    """
    def __init__(self):
        # We target the Binance USD-M Futures api to align with Long/Short ratios.
        self.client = UMFutures()

    def fetch_historical_klines(self, symbol: str, interval: str, limit: int, **kwargs) -> List[List[Any]]:
        """
        Fetches historical kline (candlestick) data for a given symbol.
        Volume is incredibly important for Profile so we ensure the limits are solid.

        Args:
            symbol (str): The trading symbol.
            interval (str): The kline interval (e.g., '1m', '15m', '1h', '1d', '1w').
            limit (int): The number of klines to fetch.
            **kwargs: Additional arguments like startTime, endTime.

        Returns:
            List: A list of kline data as defined in the Binance API.
        """
        try:
            logger.info(f"Fetching {limit} klines for {symbol} at {interval} interval")
            response = self.client.klines(symbol=symbol, interval=interval, limit=limit, **kwargs)
            return response
        except ClientError as error:
            logger.error(f"Failed to fetch klines for {symbol}: {error.error_message}")
            return []

    def fetch_order_book(self, symbol: str, limit: int = 1000) -> Dict[str, Any]:
        """
        Fetches the order book depth for the given symbol to identify massive liquidity pools.
        Returns a dictionary with 'bids' and 'asks'.

        Args:
            symbol (str): The trading symbol.
            limit (int, optional): The maximum number of orders to return.

        Returns:
            Dict[str, Any]: The order book data.
            {
                "lastUpdateId": 1027024,
                "E": 1773693621079,    # Message output time (Unix epoch)
                "T": 1773693621069,    # Transaction time (Unix epoch)
                "bids": [              # Buy
                    [
                        "4.00000000",  # PRICE
                        "431.00000000" # QTY
                    ]
                ],
                "asks": [              # Sell
                    [
                        "4.00000200",
                        "12.00000000"
                    ]
                ]
            }
        """
        try:
            logger.info(f"Fetching Order Book for {symbol} - Limit: {limit}")
            response = self.client.depth(symbol=symbol, limit=limit)
            return response
        except ClientError as error:
            logger.error(f"Failed to fetch order book for {symbol}: {error.error_message}")
            return {}
