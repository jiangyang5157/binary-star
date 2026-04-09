from abc import ABC, abstractmethod
from typing import List, Optional, Dict, Any
from .models import (
    KlineData, 
    OpenInterestData, 
    RatioData, 
    LiquidationData, 
    FundingRateData, 
    GenericOrderBook
)

class AbstractExchangeClient(ABC):
    """
    Abstract Interface for Cryptocurrency Exchange Data Adapters.
    Ensures decoupled downstream components can rely on standardized domain models.
    """

    @abstractmethod
    def fetch_historical_klines(self, symbol: str, interval: str, limit: int, **kwargs) -> List[KlineData]:
        """Fetches historical candlestick (kline) data."""
        pass

    @abstractmethod
    def fetch_order_book(self, symbol: str, limit: int = 1000) -> GenericOrderBook:
        """Fetches order book depth."""
        pass

    @abstractmethod
    def fetch_liquidations(self, symbol: str, limit: int = 100, **kwargs) -> Optional[List[LiquidationData]]:
        """Fetches recent forced liquidation orders."""
        pass

    @abstractmethod
    def fetch_open_interest(self, symbol: str, period: str = "1h", limit: int = 1, **kwargs) -> List[OpenInterestData]:
        """Fetches current or historical Open Interest (Batch-first contract)."""
        pass

    @abstractmethod
    def fetch_taker_long_short_ratio(self, symbol: str, period: str, limit: int = 1, **kwargs) -> List[RatioData]:
        """Fetches Taker Buy/Sell Volume Ratio (Order Flow Sentiment)."""
        pass

    @abstractmethod
    def fetch_long_short_ratio(self, symbol: str, period: str, limit: int = 1, **kwargs) -> List[RatioData]:
        """Fetches Account Long/Short Ratio."""
        pass

    @abstractmethod
    def fetch_top_long_short_accounts(self, symbol: str, period: str, limit: int = 1, **kwargs) -> List[RatioData]:
        """Fetches the Top Trader Long/Short Ratio."""
        pass

    @abstractmethod
    def fetch_funding_rate(self, symbol: str, limit: int = 100, **kwargs) -> List[FundingRateData]:
        """Fetches historical funding rate data."""
        pass

    @abstractmethod
    def close(self):
        """Releases any network connections or sessions."""
        pass
