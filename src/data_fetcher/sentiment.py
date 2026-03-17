"""
Data Fetcher Module:
Responsible for all external communication with Binance APIs.
Focuses on both technical price data (K-lines) and psychological sentiment data (OI, LS Ratio).
"""
import logging
from datetime import datetime, timezone
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

    def fetch_open_interest(self, symbol: str, **kwargs) -> Dict[str, Any]:
        """
        Fetches the open interest. If endTime is in kwargs, fetches historical data.
        Note: Binance only provides the last 30 days of historical data.
        """
        try:
            if 'endTime' in kwargs:
                end_ts = kwargs['endTime']
                now_ts = int(datetime.now(timezone.utc).timestamp() * 1000)
                # 30 days in milliseconds: 30 * 24 * 60 * 60 * 1000 = 2,592,000,000
                if now_ts - end_ts > 2592000000:
                    logger.info(f"Skipping historical OI for {symbol}: Date is > 30 days ago.")
                    return {}

                logger.info(f"Fetching Historical Open Interest for {symbol}")
                response = self.client.open_interest_hist(symbol=symbol, period="1h", limit=1, **kwargs)
                if response:
                    return {
                        "symbol": symbol,
                        "openInterest": response[-1].get('sumOpenInterest', 'N/A'),
                        "time": response[-1].get('timestamp', 0)
                    }
                return {}
            
            logger.info(f"Fetching Current Open Interest for {symbol}")
            response = self.client.open_interest(symbol=symbol)
            return response
        except ClientError as error:
            logger.error(f"Failed to fetch open interest for {symbol}: {error.error_message}")
            return {}

    def fetch_long_short_ratio(self, symbol: str, period: str = "4h", limit: int = 1, **kwargs) -> List[Dict[str, Any]]:
        """
        Fetches the Long/Short Ratio. Supports startTime/endTime in kwargs.
        Note: Binance only provides the last 30 days of historical data.
        """
        try:
            if 'endTime' in kwargs:
                end_ts = kwargs['endTime']
                now_ts = int(datetime.now(timezone.utc).timestamp() * 1000)
                if now_ts - end_ts > 2592000000:
                    logger.info(f"Skipping historical L/S ratio for {symbol}: Date is > 30 days ago.")
                    return []

            logger.info(f"Fetching Long/Short ratio for {symbol} - Period: {period}")
            response = self.client.long_short_account_ratio(symbol=symbol, period=period, limit=limit, **kwargs)
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
