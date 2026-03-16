import logging
from typing import Dict, Any, List
from binance.um_futures import UMFutures
from binance.error import ClientError

logger = logging.getLogger(__name__)

class SentimentFetcher:
    """
    Focused strictly on Binance Futures sentiment indicators.
    """
    def __init__(self):
        self.client = UMFutures()

    def fetch_open_interest(self, symbol: str) -> Dict[str, Any]:
        """
        Fetches the current open interest. A rising OI usually confirms the validity
        of a current breakout or trend.

        Returns:
            Dict[str, Any]:
            {
                "symbol": "BTCUSDT",
                "openInterest": "89184.862",
                "time": 1773695251702
            }
        """
        try:
            logger.info(f"Fetching Open Interest for {symbol}")
            response = self.client.open_interest(symbol=symbol)
            return response
        except ClientError as error:
            logger.error(f"Failed to fetch open interest for {symbol}: {error.error_message}")
            return {}

    def fetch_long_short_ratio(self, symbol: str, period: str = "4h", limit: int = 30) -> List[Dict[str, Any]]:
        """
        Fetches the Global Long/Short Ratio over a specified period.

        Returns:
            List[Dict[str, Any]]:
            [
                {
                    "symbol": "BTCUSDT",
                    "longAccount": "0.4613",
                    "longShortRatio": "0.8563",
                    "shortAccount": "0.5387",
                    "timestamp": 1773691200000
                }
            ]
        """
        try:
            logger.info(f"Fetching Long/Short ratio for {symbol} - Period: {period}")
            response = self.client.long_short_account_ratio(symbol=symbol, period=period, limit=limit)
            return response
        except ClientError as error:
            logger.error(f"Failed to fetch long/short ratio for {symbol}: {error.error_message}")
            return []

    def fetch_funding_rate(self, symbol: str, limit: int = 100) -> List[Dict[str, Any]]:
        """
        Fetches the funding rate history (useful for seeing if bulls or bears are paying a premium).

        Returns:
            List[Dict[str, Any]]:
            [
                {
                    "symbol": "BTCUSDT",
                    "fundingTime": 1773676800000,
                    "fundingRate": "0.00002015",
                    "markPrice": "73241.19793478"
                }
            ]
        """
        try:
            logger.info(f"Fetching Funding Rate history for {symbol}")
            response = self.client.funding_rate(symbol=symbol, limit=limit)
            return response
        except ClientError as error:
            logger.error(f"Failed to fetch funding rate for {symbol}: {error.error_message}")
            return []
