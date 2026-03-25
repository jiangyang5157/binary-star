import logging
import os
import requests
from datetime import datetime, timezone
from typing import Dict, List, Any, Optional

from binance.um_futures import UMFutures
from binance.error import ClientError
from src.utils.logger_utils import setup_logger

# Initialize project-standard logger
logger = setup_logger(__name__)

class BinanceFuturesClient:
    """
    Unified Data Service for Binance USD-M Futures.
    
    Provides high-integrity access to both 'Technical' (Price/Volume) and 
    'Psychological' (OI, LS Ratio, Funding) market data.
    
    Attributes:
        client (UMFutures): The underlying Binance SDK client.
    """
    
    def __init__(self, api_key: Optional[str] = None, api_secret: Optional[str] = None):
        """
        Initializes the Binance client. Uses environment variables or explicit keys.
        
        Args:
            api_key: Optional Binance API Key.
            api_secret: Optional Binance API Secret.
        """
        key = api_key or os.environ.get("BINANCE_API_KEY")
        secret = api_secret or os.environ.get("BINANCE_API_SECRET")
        
        if key and secret:
            logger.info("Initializing Binance client with authenticated access.")
            self.client = UMFutures(key=key, secret=secret)
        else:
            logger.info("Initializing Binance client in public (unauthenticated) mode.")
            self.client = UMFutures()

    # --- Technical Market Data ---

    def fetch_historical_klines(self, symbol: str, interval: str, limit: int, **kwargs) -> List[List[Any]]:
        """Fetches historical candlestick (kline) data."""
        try:
            logger.info(f"Fetching {limit} klines for {symbol} ({interval})")
            return self.client.klines(symbol=symbol, interval=interval, limit=limit, **kwargs)
        except ClientError as e:
            logger.error(f"Klines fetch failed for {symbol}: {e.error_message}")
            return []

    def fetch_order_book(self, symbol: str, limit: int = 1000) -> Dict[str, Any]:
        """Fetches order book depth for identifying liquidity pools."""
        try:
            logger.debug(f"Fetching Order Book for {symbol} (Limit: {limit})")
            return self.client.depth(symbol=symbol, limit=limit)
        except ClientError as e:
            logger.error(f"Order book fetch failed for {symbol}: {e.error_message}")
            return {}

    def fetch_liquidations(self, symbol: str, limit: int = 100) -> List[Dict[str, Any]]:
        """
        Fetches recent forced liquidation orders. 
        Uses SDK first, falls back to public REST endpoint if necessary.
        """
        try:
            return self.client.force_orders(symbol=symbol, limit=limit)
        except (ClientError, Exception) as e:
            logger.warning(f"SDK liquidation fetch failed for {symbol}, trying fallback: {e}")
            
        # Fallback to public REST API
        try:
            url = f"https://fapi.binance.com/fapi/v1/allForceOrders?symbol={symbol}&limit={limit}"
            resp = requests.get(url, timeout=10)
            return resp.json() if resp.status_code == 200 else []
        except Exception as e:
            logger.error(f"Fallback liquidation fetch failed: {e}")
            return []

    # --- Sentiment & Psychology Data ---

    def fetch_open_interest(self, symbol: str, period: str = "1h", **kwargs) -> Dict[str, Any]:
        """
        Fetches current or historical Open Interest.
        Note: Historical data limit is 30 days.
        """
        try:
            if 'endTime' in kwargs and not self._is_within_30_days(kwargs['endTime']):
                logger.info(f"Historical OI for {symbol} skipped (older than 30 days).")
                return {}

            if 'endTime' in kwargs:
                # Historical fetch
                resp = self.client.open_interest_hist(symbol=symbol, period=period, limit=1, **kwargs)
                if resp:
                    return {
                        "symbol": symbol,
                        "openInterest": resp[-1].get('sumOpenInterest', '0'),
                        "time": resp[-1].get('timestamp', 0)
                    }
                return {}
            
            # Current fetch
            return self.client.open_interest(symbol=symbol)
        except ClientError as e:
            logger.error(f"Open Interest fetch failed for {symbol}: {e.error_message}")
            return {}

    def fetch_long_short_ratio(self, symbol: str, period: str, limit: int = 1, **kwargs) -> List[Dict[str, Any]]:
        """
        Fetches Account Long/Short Ratio.
        Note: Historical data limit is 30 days.
        """
        try:
            if 'endTime' in kwargs and not self._is_within_30_days(kwargs['endTime']):
                logger.info(f"Historical L/S ratio for {symbol} skipped (older than 30 days).")
                return []
            
            return self.client.long_short_account_ratio(symbol=symbol, period=period, limit=limit, **kwargs)
        except ClientError as e:
            logger.error(f"L/S Ratio fetch failed for {symbol}: {e.error_message}")
            return []

    def fetch_top_long_short_accounts(self, symbol: str, period: str, limit: int = 1, **kwargs) -> List[Dict[str, Any]]:
        """Fetches the Top Trader Long/Short Ratio (Accounts)."""
        try:
            return self.client.top_long_short_account_ratio(symbol=symbol, period=period, limit=limit, **kwargs)
        except ClientError as e:
            logger.error(f"Top L/S Ratio fetch failed for {symbol}: {e.error_message}")
            return []

    def fetch_funding_rate(self, symbol: str, limit: int = 100) -> List[Dict[str, Any]]:
        """Fetches historical funding rate data."""
        try:
            return self.client.funding_rate(symbol=symbol, limit=limit)
        except ClientError as e:
            logger.error(f"Funding Rate fetch failed for {symbol}: {e.error_message}")
            return []

    # --- Internal Utilities ---

    def _is_within_30_days(self, timestamp_ms: int) -> bool:
        """Checks if a given millisecond timestamp is within the last 30 days."""
        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        thirty_days_ms = 30 * 24 * 60 * 60 * 1000
        return (now_ms - timestamp_ms) <= thirty_days_ms

    def close(self):
        """Closes the client connection (placeholder for session cleanup)."""
        pass
