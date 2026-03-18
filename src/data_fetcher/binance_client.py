import logging
import requests
import os
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
        self.api_key = os.environ.get("BINANCE_API_KEY")
        self.api_secret = os.environ.get("BINANCE_API_SECRET")
        
        if self.api_key and self.api_secret:
            logger.info("Initializing Binance client with API Keys")
            self.client = UMFutures(key=self.api_key, secret=self.api_secret)
        else:
            logger.info("Initializing Binance client in Public mode")
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

    def fetch_liquidations(self, symbol: str, limit: int = 100) -> List[Dict[str, Any]]:
        """
        Fetches recent liquidation orders (forced orders).
        Tries SDK (signed) first for stability, falls back to public API if needed.
        """
        # Try SDK first
        try:
            logger.info(f"Fetching Liquidations for {symbol} via SDK")
            response = self.client.force_orders(symbol=symbol, limit=limit)
            return response
        except ClientError as error:
            logger.warning(f"SDK liquidation fetch failed ({error.error_message}), falling back to public API...")
        except Exception as e:
            logger.warning(f"SDK liquidation fetch failed ({e}), falling back to public API...")

        # Fallback to Public API
        try:
            url = f"https://fapi.binance.com/fapi/v1/allForceOrders?symbol={symbol}&limit={limit}"
            response = requests.get(url, timeout=10)
            if response.status_code == 200:
                return response.json()
            else:
                logger.error(f"Fallback liquidation fetch failed: {response.status_code} - {response.text}")
                return []
        except Exception as e:
            logger.error(f"Error fetching liquidations via fallback: {e}")
            return []

    def fetch_top_long_short_accounts(self, symbol: str, period: str, limit: int = 1, **kwargs) -> List[Dict[str, Any]]:
        """
        Fetches the Top Traders Long/Short Ratio (Accounts).
        More professional than the general account ratio.
        """
        try:
            logger.info(f"Fetching Top Traders L/S Ratio for {symbol} - Period: {period}")
            response = self.client.top_long_short_account_ratio(symbol=symbol, period=period, limit=limit, **kwargs)
            return response
        except ClientError as error:
            logger.error(f"Failed to fetch top traders L/S ratio for {symbol}: {error.error_message}")
            return []
