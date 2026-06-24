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

from src.infrastructure.exchange.base_client import AbstractExchangeClient
from src.infrastructure.exchange.models import (
    KlineData,
    OpenInterestData,
    RatioData,
    LiquidationData,
    FundingRateData,
    GenericOrderBook
)

# Initialize project-standard logger
logger = setup_logger(__name__)

class BinanceFuturesClient(AbstractExchangeClient):
    """
    Unified Data Service for Binance USD-M Futures.
    
    Provides high-integrity access to both 'Technical' (Price/Volume) and 
    'Psychological' (OI, LS Ratio, Funding) market data.
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
        """
        key = api_key or os.environ.get("BINANCE_API_KEY")
        secret = api_secret or os.environ.get("BINANCE_API_SECRET")
        
        if key and secret:
            logger.info("Initializing Binance client with authenticated access.")
            self.client = UMFutures(key=key, secret=secret)
        else:
            logger.warning("Initializing Binance client in public (unauthenticated) mode. Some write endpoints will be unavailable.")
            self.client = UMFutures()
        
        # Expose auth state for defensive calls
        self.is_authenticated = bool(key and secret)
            
        self.network_cfg = self._load_network_config()
        # Strict sourcing from global_config.yaml (network section)
        binance_net = self.network_cfg.get('network', {}).get('binance', {})
        self.timeout = int(binance_net['api_timeout_seconds'])
        self.retry_count = int(binance_net['retry_count'])

    def _get_retryer(self, method_name: str) -> tenacity.Retrying:
        return tenacity.Retrying(
            stop=tenacity.stop_after_attempt(self.retry_count),
            wait=tenacity.wait_random_exponential(multiplier=1, max=10),
            retry=tenacity.retry_if_exception_type((ClientError, requests.exceptions.RequestException)),
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

    def fetch_historical_klines(self, symbol: str, interval: str, limit: int, **kwargs: Any) -> List[KlineData]:
        try:
            MAX_CHUNK = 1000
            
            if limit <= MAX_CHUNK:
                logger.debug(f"Binance: Fetching klines for {symbol} ({interval})")
                for attempt in self._get_retryer("klines"):
                    with attempt:
                        raw_klines = self.client.klines(symbol=symbol, interval=interval, limit=limit, **kwargs)
                        return self._map_klines(raw_klines)
            
            all_klines: List[List[Any]] = []
            remaining = limit
            current_kwargs = kwargs.copy()
            is_forward = 'startTime' in current_kwargs
            pagination_failed = False

            while remaining > 0:
                fetch_count = min(remaining, MAX_CHUNK)
                logger.debug(f"Binance: Paginating klines ({'FWD' if is_forward else 'BWD'}) for {symbol} (Rem: {remaining})")

                try:
                    for attempt in self._get_retryer("klines_paginated"):
                        with attempt:
                            chunk = self.client.klines(symbol=symbol, interval=interval, limit=fetch_count, **current_kwargs)
                except (ClientError, Exception) as e:
                    logger.warning(f"Binance: Chunk fetch failed mid-pagination ({len(all_klines)} klines accumulated): {e}")
                    pagination_failed = True
                    break

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

            if pagination_failed:
                logger.warning(
                    "Binance: Returning partial klines for %s — %d fetched, %d requested (%d missing).",
                    symbol, len(sorted_unique), limit, limit - len(sorted_unique),
                )
            logger.info(f"Binance: Fetched {len(sorted_unique)} klines for {symbol}.")
            return self._map_klines(sorted_unique)
            
        except ClientError as e:
            logger.error(f"Binance: Klines fetch failed for {symbol}: {e.error_message}")
            return []
        except Exception as e:
            logger.error(f"Binance: Unexpected error during kline pagination: {e}", exc_info=True)
            return []

    # NOTE: Data mappers below use .get() defaults (e.g., .get('field', 0)).
    # Missing API fields silently become 0/1.0 rather than raising — this
    # keeps the pipeline running but masks upstream data-quality issues.
    # Better to add structured data-quality logging when API responses diverge
    # from the expected schema.

    def _map_klines(self, raw_data: List[List[Any]]) -> List[KlineData]:
        """
        Maps raw Binance API responses to domain KlineData objects.

        Binance API Original Kline/Candlestick payload schema:
        [
            0: Open time (开盘时间)
            1: Open (开盘价)
            2: High (最高价)
            3: Low (最低价)
            4: Close (收盘价)
            5: Volume (成交量)
            6: Close time (收盘时间)
            7: Quote asset volume (成交额)
            8: Number of trades (成交笔数)
            9: Taker buy base asset volume (主动买入的成交量)
            10: Taker buy quote asset volume (主动买入的成交额)
            11: Ignore (忽略)
        ]
        """
        return [
            KlineData(
                open_time=int(k[0]),
                open=float(k[1]),
                high=float(k[2]),
                low=float(k[3]),
                close=float(k[4]),
                volume=float(k[5]),
                close_time=int(k[6]),
                quote_volume=float(k[7]),
                trades=int(k[8]),
                taker_buy_base=float(k[9]),
                taker_buy_quote=float(k[10])
            )
            for k in raw_data
        ]

    def fetch_order_book(self, symbol: str, limit: int = 1000) -> GenericOrderBook:
        try:
            logger.debug(f"Binance: Fetching Order Book for {symbol} (Limit: {limit})")
            raw_depth = {}
            for attempt in self._get_retryer("depth"):
                with attempt:
                    raw_depth = self.client.depth(symbol=symbol, limit=limit)
            
            return GenericOrderBook(
                bids=[[float(p), float(q)] for p, q in raw_depth.get('bids', [])],
                asks=[[float(p), float(q)] for p, q in raw_depth.get('asks', [])],
                timestamp=int(datetime.now(timezone.utc).timestamp() * 1000)
            )
        except ClientError as e:
            logger.error(f"Binance: Order book fetch failed for {symbol}: {e.error_message}")
            return GenericOrderBook([], [], 0)

    def fetch_liquidations(self, symbol: str, limit: int = 100, **kwargs: Any) -> Optional[List[LiquidationData]]:
        """
        Fetches recent forced liquidation orders.

        NOTE: Binance API does not provide a public liquidation data endpoint.
        - The /fapi/v1/forceOrders endpoint requires a listen key (user data stream),
          which is scoped to the user's own account — not market-wide liquidations.
        - The /fapi/v1/allForceOrders endpoint was deprecated/restricted and is no
          longer available on the public API.
        - Without a viable data source, this method returns None. Downstream metrics
          (e.g., LiquidationEstimator, liquidation cluster triggers) gracefully handle
          the absence of this data.
        """
        return None

    # --- Sentiment & Psychology Data ---

    def fetch_open_interest(self, symbol: str, period: str = "1h", limit: int = 1, **kwargs: Any) -> List[OpenInterestData]:
        try:
            if 'endTime' in kwargs:
                # 1. Forensic Boundary Check (Binance limit: 30 days)
                if not self._is_within_30_days(kwargs['endTime']):
                    logger.debug(f"Binance: Historical OI for {symbol} skipped (30-day limit reached).")
                    return []
                
                # 2. Historical Sequence Fetch (Requires Period)
                for attempt in self._get_retryer("open_interest_hist"):
                    with attempt:
                        resp = self.client.open_interest_hist(symbol=symbol, period=period, limit=limit, **kwargs)
                
                if not resp:
                    return []
                
                return [
                    OpenInterestData(
                        symbol=symbol,
                        open_interest=float(r.get('sumOpenInterest', 0)),
                        timestamp=int(r.get('timestamp', 0))
                    ) for r in resp
                ]
            
            # 3. Real-time Snapshot Fetch (No Period Required)
            for attempt in self._get_retryer("open_interest"):
                with attempt:
                    resp = self.client.open_interest(symbol=symbol)
                    return [
                        OpenInterestData(
                            symbol=symbol,
                            open_interest=float(resp.get('openInterest', 0)),
                            timestamp=int(resp.get('time', 0))
                        )
                    ]
        except ClientError as e:
            logger.error(f"Binance: Open Interest fetch failed for {symbol}: {e.error_message}")
            return []
        except Exception as e:
            logger.error(f"Binance: Unexpected error in OI fetch for {symbol}: {e}")
            return []

    def fetch_long_short_ratio(self, symbol: str, period: str, limit: int = 1, **kwargs: Any) -> List[RatioData]:
        try:
            if 'endTime' in kwargs and not self._is_within_30_days(kwargs['endTime']):
                logger.debug(f"Binance: Historical L/S ratio for {symbol} skipped (30-day limit).")
                return []
            
            for attempt in self._get_retryer("long_short_account_ratio"):
                with attempt:
                    resp = self.client.long_short_account_ratio(symbol=symbol, period=period, limit=limit, **kwargs)
                    return [
                        RatioData(
                            long_short_ratio=float(r.get('longShortRatio', 1.0)),
                            timestamp=int(r.get('timestamp', 0))
                        ) for r in resp
                    ]
        except ClientError as e:
            logger.error(f"Binance: L/S Ratio fetch failed for {symbol}: {e.error_message}")
            return []

    def fetch_taker_long_short_ratio(self, symbol: str, period: str, limit: int = 1, **kwargs: Any) -> List[RatioData]:
        try:
            for attempt in self._get_retryer("taker_long_short_ratio"):
                with attempt:
                    # SDK method: taker_long_short_ratio
                    resp = self.client.taker_long_short_ratio(symbol=symbol, period=period, limit=limit, **kwargs)
                    return [
                        RatioData(
                            long_short_ratio=float(r.get('buySellRatio', 1.0)),
                            timestamp=int(r.get('timestamp', 0))
                        ) for r in resp
                    ]
        except ClientError as e:
            logger.error(f"Binance: Taker L/S Ratio fetch failed for {symbol}: {e.error_message}")
            return []
        except Exception as e:
            logger.error(f"Binance: Unexpected error in Taker L/S Ratio fetch: {e}")
            return []

    def fetch_top_long_short_accounts(self, symbol: str, period: str, limit: int = 1, **kwargs: Any) -> List[RatioData]:
        try:
            for attempt in self._get_retryer("top_long_short_account_ratio"):
                with attempt:
                    resp = self.client.top_long_short_account_ratio(symbol=symbol, period=period, limit=limit, **kwargs)
                    return [
                        RatioData(
                            long_short_ratio=float(r.get('longShortRatio', 1.0)),
                            timestamp=int(r.get('timestamp', 0))
                        ) for r in resp
                    ]
        except ClientError as e:
            logger.error(f"Binance: Top L/S Ratio fetch failed for {symbol}: {e.error_message}")
            return []

    def fetch_funding_rate(self, symbol: str, limit: int = 100, **kwargs: Any) -> List[FundingRateData]:
        try:
            for attempt in self._get_retryer("funding_rate"):
                with attempt:
                    resp = self.client.funding_rate(symbol=symbol, limit=limit, **kwargs)
                    return [
                        FundingRateData(
                            funding_rate=float(r.get('fundingRate', 0)),
                            timestamp=int(r.get('fundingTime', 0))
                        ) for r in resp
                    ]
        except ClientError as e:
            logger.error(f"Binance: Funding Rate fetch failed for {symbol}: {e.error_message}")
            return []

    # --- Internal Utilities ---

    def _is_within_30_days(self, timestamp_ms: int) -> bool:
        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        thirty_days_ms = 30 * 24 * 60 * 60 * 1000
        return (now_ms - timestamp_ms) <= thirty_days_ms

    def close(self):
        """Closes the client connection (placeholder for session cleanup)."""
        pass
