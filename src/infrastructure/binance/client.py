import logging
import os
import requests
from datetime import datetime, timezone
from typing import Dict, List, Any, Optional

from binance.um_futures import UMFutures
from binance.error import ClientError
import yaml
import tenacity
from src.utils.logger_utils import setup_logger
from src.utils.path_utils import resolve_project_root

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
    
    # Standard Binance intervals in seconds
    INTERVAL_SECONDS = {
        "1m": 60, "3m": 180, "5m": 300, "15m": 900, "30m": 1800,
        "1h": 3600, "2h": 7200, "4h": 14400, "6h": 21600, "8h": 28800, "12h": 43200,
        "1d": 86400, "3d": 259200, "1w": 604800, "1M": 2592000
    }
    
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
            
        self.network_cfg = self._load_network_config()
        # Strict sourcing from global_config.yaml (network section)
        binance_net = self.network_cfg.get('network', {}).get('binance', {})
        self.timeout = int(binance_net['api_timeout_seconds'])
        self.retry_count = int(binance_net['retry_count'])

    def _get_retryer(self, method_name: str) -> tenacity.Retrying:
        """Returns a tenacity retrying object for Binance SDK methods."""
        return tenacity.Retrying(
            stop=tenacity.stop_after_attempt(self.retry_count),
            wait=tenacity.wait_exponential(multiplier=1, min=1, max=10),
            retry=tenacity.retry_if_exception_type((ClientError, Exception)),
            before_sleep=lambda retry_state: logger.warning(
                f"Binance: {method_name} failed. Retrying ({retry_state.attempt_number}/{self.retry_count})..."
            ),
            reraise=True
        )

    def _load_network_config(self) -> Dict[str, Any]:
        """Loads the global configuration from YAML (for network settings)."""
        try:
            cfg_path = os.path.join(resolve_project_root(), "config", "global_config.yaml")
            if os.path.exists(cfg_path):
                with open(cfg_path, 'r') as f:
                    return yaml.safe_load(f)
        except Exception as e:
            logger.error(f"CRITICAL: Failed to load global_config.yaml: {e}")
            raise
        return {}

    # --- Technical Market Data ---

    def fetch_historical_klines(self, symbol: str, interval: str, limit: int, **kwargs) -> List[List[Any]]:
        """
        Fetches historical candlestick (kline) data with automated pagination.
        Handles Binance API limits (typically 1000-1500) by splitting large 
        requests into sequential chunks.
        """
        try:
            # Binance standard max limit per request
            MAX_CHUNK = 1000
            
            if limit <= MAX_CHUNK:
                logger.debug(f"Fetching klines for {symbol} ({interval}) with limit {limit} and kwargs {kwargs}")
                for attempt in self._get_retryer("klines"):
                    with attempt:
                        return self.client.klines(symbol=symbol, interval=interval, limit=limit, **kwargs)
            
            # Pagination Logic for large limits
            all_klines = []
            remaining = limit
            current_kwargs = kwargs.copy()
            
            # Directional Detection: If startTime is present, fetch forward.
            # Otherwise, use standard backward-to-forward pagination.
            is_forward = 'startTime' in current_kwargs
            
            while remaining > 0:
                fetch_count = min(remaining, MAX_CHUNK)
                logger.debug(f"Paginating klines ({'FORWARD' if is_forward else 'BACKWARD'}) for {symbol}: Fetching chunk of {fetch_count} (Remaining: {remaining})")
                
                for attempt in self._get_retryer("klines_paginated"):
                    with attempt:
                        chunk = self.client.klines(symbol=symbol, interval=interval, limit=fetch_count, **current_kwargs)
                if not chunk:
                    break
                    
                if is_forward:
                    # Append chunk to maintain chronological order [Earliest -> Latest]
                    all_klines.extend(chunk)
                    latest_open = int(chunk[-1][0])
                    current_kwargs['startTime'] = latest_open + 1
                    
                    # Stop if we've bypassed the endTime limit
                    if 'endTime' in current_kwargs and current_kwargs['startTime'] > current_kwargs['endTime']:
                        break
                else:
                    # Prepend chunk to maintain chronological order [Earliest -> Latest]
                    all_klines = chunk + all_klines
                    earliest_open = int(chunk[0][0])
                    current_kwargs['endTime'] = earliest_open - 1
                
                remaining -= len(chunk)
                if len(chunk) < fetch_count:
                    # No more data in this range
                    break
            
            # Final deduplication and sorting by OpenTime (index 0)
            # Use dictionary to maintain unique entries by OpenTime
            unique_klines = {k[0]: k for k in all_klines}
            sorted_unique = [unique_klines[ts] for ts in sorted(unique_klines.keys())]
            
            logger.info(f"Fetched total of {len(sorted_unique)} klines for {symbol} via pagination.")
            return sorted_unique
            
        except ClientError as e:
            logger.error(f"Klines fetch failed for {symbol}: {e.error_message}")
            return []
        except Exception as e:
            logger.error(f"Unexpected error during kline pagination: {e}", exc_info=True)
            return []

    def fetch_order_book(self, symbol: str, limit: int = 1000) -> Dict[str, Any]:
        """Fetches order book depth for identifying liquidity pools."""
        try:
            logger.debug(f"Fetching Order Book for {symbol} (Limit: {limit})")
            for attempt in self._get_retryer("depth"):
                with attempt:
                    return self.client.depth(symbol=symbol, limit=limit)
        except ClientError as e:
            logger.error(f"Order book fetch failed for {symbol}: {e.error_message}")
            return {}

    def fetch_liquidations(self, symbol: str, limit: int = 100, **kwargs) -> List[Dict[str, Any]]:
        """
        Fetches recent forced liquidation orders. 
        Uses SDK first, falls back to public REST endpoint if necessary.
        """
        try:
            for attempt in self._get_retryer("force_orders"):
                with attempt:
                    return self.client.force_orders(symbol=symbol, limit=limit, **kwargs)
        except (ClientError, Exception) as e:
            logger.warning(f"SDK liquidation fetch failed for {symbol}, trying fallback: {e}")
            
        # Fallback to public REST API
        try:
            params = f"symbol={symbol}&limit={limit}"
            if 'startTime' in kwargs: params += f"&startTime={kwargs['startTime']}"
            if 'endTime' in kwargs: params += f"&endTime={kwargs['endTime']}"
            
            url = f"https://fapi.binance.com/fapi/v1/allForceOrders?{params}"
            resp = requests.get(url, timeout=self.timeout)
            raw_data = resp.json() if resp.status_code == 200 else []
            return raw_data
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
                for attempt in self._get_retryer("open_interest_hist"):
                    with attempt:
                        resp = self.client.open_interest_hist(symbol=symbol, period=period, limit=1, **kwargs)
                if resp:
                    return {
                        "symbol": symbol,
                        "openInterest": resp[-1].get('sumOpenInterest', '0'),
                        "time": resp[-1].get('timestamp', 0)
                    }
                return {}
            
            # Current fetch
            for attempt in self._get_retryer("open_interest"):
                with attempt:
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
            
            for attempt in self._get_retryer("long_short_account_ratio"):
                with attempt:
                    return self.client.long_short_account_ratio(symbol=symbol, period=period, limit=limit, **kwargs)
        except ClientError as e:
            logger.error(f"L/S Ratio fetch failed for {symbol}: {e.error_message}")
            return []

    def fetch_top_long_short_accounts(self, symbol: str, period: str, limit: int = 1, **kwargs) -> List[Dict[str, Any]]:
        """Fetches the Top Trader Long/Short Ratio (Accounts)."""
        try:
            for attempt in self._get_retryer("top_long_short_account_ratio"):
                with attempt:
                    return self.client.top_long_short_account_ratio(symbol=symbol, period=period, limit=limit, **kwargs)
        except ClientError as e:
            logger.error(f"Top L/S Ratio fetch failed for {symbol}: {e.error_message}")
            return []

    def fetch_funding_rate(self, symbol: str, limit: int = 100, **kwargs) -> List[Dict[str, Any]]:
        """Fetches historical funding rate data."""
        try:
            for attempt in self._get_retryer("funding_rate"):
                with attempt:
                    return self.client.funding_rate(symbol=symbol, limit=limit, **kwargs)
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
