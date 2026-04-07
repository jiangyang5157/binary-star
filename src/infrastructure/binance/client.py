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
            logger.warning("Initializing Binance client in public (unauthenticated) mode. Some write endpoints will be unavailable.")
            self.client = UMFutures()
        
        # v6.20: Expose auth state for defensive calls
        self.is_authenticated = bool(key and secret)
            
        self.network_cfg = self._load_network_config()
        # Strict sourcing from global_config.yaml (network section)
        binance_net = self.network_cfg.get('network', {}).get('binance', {})
        self.timeout = int(binance_net['api_timeout_seconds'])
        self.retry_count = int(binance_net['retry_count'])

    def _get_retryer(self, method_name: str) -> tenacity.Retrying:
        """Returns a tenacity retrying object for Binance SDK methods.

        Args:
            method_name: Name of the operation being retried (for logging).

        Returns:
            A tenacity Retrying instance configured with exponential backoff and jitter.
        """
        return tenacity.Retrying(
            stop=tenacity.stop_after_attempt(self.retry_count),
            wait=tenacity.wait_random_exponential(multiplier=1, max=10),
            retry=tenacity.retry_if_exception_type((ClientError, requests.exceptions.RequestException, Exception)),
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

    def fetch_historical_klines(self, symbol: str, interval: str, limit: int, **kwargs: Any) -> List[List[Any]]:
        """Fetches historical candlestick (kline) data with automated pagination.

        Handles Binance API limits (typically 1000-1500) by splitting large 
        requests into sequential chunks and merging them chronologically.

        Args:
            symbol: Trading pair symbol (e.g., BTCUSDT).
            interval: Kline interval (e.g., '1h', '15m').
            limit: Total number of klines to fetch.
            **kwargs: Additional Binance API parameters (startTime, endTime).

        Returns:
            A list of kline lists, sorted by open time.
        """
        try:
            MAX_CHUNK = 1000
            
            if limit <= MAX_CHUNK:
                logger.debug(f"Binance: Fetching klines for {symbol} ({interval})")
                for attempt in self._get_retryer("klines"):
                    with attempt:
                        return self.client.klines(symbol=symbol, interval=interval, limit=limit, **kwargs)
            
            all_klines: List[List[Any]] = []
            remaining = limit
            current_kwargs = kwargs.copy()
            is_forward = 'startTime' in current_kwargs
            
            while remaining > 0:
                fetch_count = min(remaining, MAX_CHUNK)
                logger.debug(f"Binance: Paginating klines ({'FWD' if is_forward else 'BWD'}) for {symbol} (Rem: {remaining})")
                
                for attempt in self._get_retryer("klines_paginated"):
                    with attempt:
                        chunk = self.client.klines(symbol=symbol, interval=interval, limit=fetch_count, **current_kwargs)
                if not chunk:
                    break
                    
                if is_forward:
                    all_klines.extend(chunk)
                    latest_open = int(chunk[-1][0])
                    current_kwargs['startTime'] = latest_open + 1
                    if 'endTime' in current_kwargs and current_kwargs['startTime'] > current_kwargs['endTime']:
                        break
                else:
                    all_klines = chunk + all_klines
                    earliest_open = int(chunk[0][0])
                    current_kwargs['endTime'] = earliest_open - 1
                
                remaining -= len(chunk)
                if len(chunk) < fetch_count:
                    break
            
            unique_klines = {k[0]: k for k in all_klines}
            sorted_unique = [unique_klines[ts] for ts in sorted(unique_klines.keys())]
            
            logger.info(f"Binance: Fetched {len(sorted_unique)} klines for {symbol}.")
            return sorted_unique
            
        except ClientError as e:
            logger.error(f"Binance: Klines fetch failed for {symbol}: {e.error_message}")
            return []
        except Exception as e:
            logger.error(f"Binance: Unexpected error during kline pagination: {e}", exc_info=True)
            return []

    def fetch_order_book(self, symbol: str, limit: int = 1000) -> Dict[str, Any]:
        """Fetches order book depth for identifying liquidity pools.

        Args:
            symbol: Trading pair symbol.
            limit: Depth limit (default 1000).

        Returns:
            The raw order book dictionary (bids, asks, lastUpdateId).
        """
        try:
            logger.debug(f"Binance: Fetching Order Book for {symbol} (Limit: {limit})")
            for attempt in self._get_retryer("depth"):
                with attempt:
                    return self.client.depth(symbol=symbol, limit=limit)
        except ClientError as e:
            logger.error(f"Binance: Order book fetch failed for {symbol}: {e.error_message}")
            return {}

    def fetch_liquidations(self, symbol: str, limit: int = 100, **kwargs: Any) -> List[Dict[str, Any]]:
        """Fetches recent forced liquidation orders.

        Uses the Binance SDK first. If it fails (e.g., 401/Invalid API Key), 
        it falls back to the public REST endpoint which does not require authentication.

        Args:
            symbol: Trading pair symbol.
            limit: Number of records (max 1000).
            **kwargs: Additional parameters (startTime, endTime).

        Returns:
            A list of liquidation order dictionaries.
        """
        try:
            # v6.21: Defensive check for authenticated state
            if self.is_authenticated:
                for attempt in self._get_retryer("force_orders"):
                    with attempt:
                        return self.client.force_orders(symbol=symbol, limit=limit, **kwargs)
            else:
                logger.debug(f"Binance: Skipping SDK force_orders for {symbol} (Unauthenticated).")
        except Exception as e:
            logger.warning(f"Binance: SDK liquidation fetch failed for {symbol} (Trying public fallback): {e}")
            
        try:
            # v6.22: Reverting to 'allForceOrders' as it is the correct public aggregator
            # Note: This endpoint is prone to 400 "out of maintenance" if restricted by Binance
            params = f"symbol={symbol}&limit={limit}"
            if 'startTime' in kwargs: params += f"&startTime={kwargs['startTime']}"
            if 'endTime' in kwargs: params += f"&endTime={kwargs['endTime']}"
            
            url = f"https://fapi.binance.com/fapi/v1/allForceOrders?{params}"
            # Use a ephemeral session for one-off requests or shared session if scaled
            with requests.Session() as s:
                resp = s.get(url, timeout=self.timeout)
                if resp.status_code == 200:
                    return resp.json()
                
                # Check for 400 specifically to log the 'out of maintenance' issue
                if resp.status_code == 400:
                    logger.debug(f"Binance: Public liquidation fallback rejected (HTTP 400): {resp.text}")
                else:
                    logger.error(f"Binance: Public liquidation fallback failed (HTTP {resp.status_code}): {resp.text}")
                return []
        except Exception as e:
            logger.error(f"Binance: Public liquidation fallback crashed: {e}")
            return []

    # --- Sentiment & Psychology Data ---

    def fetch_open_interest(self, symbol: str, period: str = "1h", **kwargs: Any) -> Dict[str, Any]:
        """Fetches current or historical Open Interest.

        Note: Historical data limit on Binance is 30 days.

        Args:
            symbol: Trading pair symbol.
            period: Aggregation period ('1h', '5m', etc).
            **kwargs: Additional parameters (startTime, endTime, limit).

        Returns:
            A dictionary containing the symbol, OI value, and timestamp.
        """
        try:
            if 'endTime' in kwargs and not self._is_within_30_days(kwargs['endTime']):
                logger.debug(f"Binance: Historical OI for {symbol} skipped (30-day limit reached).")
                return {}

            if 'endTime' in kwargs:
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
            
            for attempt in self._get_retryer("open_interest"):
                with attempt:
                    return self.client.open_interest(symbol=symbol)
        except ClientError as e:
            logger.error(f"Binance: Open Interest fetch failed for {symbol}: {e.error_message}")
            return {}

    def fetch_long_short_ratio(self, symbol: str, period: str, limit: int = 1, **kwargs: Any) -> List[Dict[str, Any]]:
        """Fetches Account Long/Short Ratio.

        Args:
            symbol: Trading pair symbol.
            period: Aggregation period.
            limit: Number of records (default 1).
            **kwargs: additional params (startTime, endTime).

        Returns:
            A list of L/S ratio records.
        """
        try:
            if 'endTime' in kwargs and not self._is_within_30_days(kwargs['endTime']):
                logger.debug(f"Binance: Historical L/S ratio for {symbol} skipped (30-day limit).")
                return []
            
            for attempt in self._get_retryer("long_short_account_ratio"):
                with attempt:
                    return self.client.long_short_account_ratio(symbol=symbol, period=period, limit=limit, **kwargs)
        except ClientError as e:
            logger.error(f"Binance: L/S Ratio fetch failed for {symbol}: {e.error_message}")
            return []

    def fetch_top_long_short_accounts(self, symbol: str, period: str, limit: int = 1, **kwargs: Any) -> List[Dict[str, Any]]:
        """Fetches the Top Trader Long/Short Ratio (Accounts)."""
        try:
            for attempt in self._get_retryer("top_long_short_account_ratio"):
                with attempt:
                    return self.client.top_long_short_account_ratio(symbol=symbol, period=period, limit=limit, **kwargs)
        except ClientError as e:
            logger.error(f"Binance: Top L/S Ratio fetch failed for {symbol}: {e.error_message}")
            return []

    def fetch_funding_rate(self, symbol: str, limit: int = 100, **kwargs: Any) -> List[Dict[str, Any]]:
        """Fetches historical funding rate data."""
        try:
            for attempt in self._get_retryer("funding_rate"):
                with attempt:
                    return self.client.funding_rate(symbol=symbol, limit=limit, **kwargs)
        except ClientError as e:
            logger.error(f"Binance: Funding Rate fetch failed for {symbol}: {e.error_message}")
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
