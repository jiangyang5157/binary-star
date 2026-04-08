from dataclasses import dataclass, field
from typing import Optional, List

@dataclass
class KlineData:
    """
    Standardized representation of a trading candlestick.
    
    Compatible with Exchange API Original Kline payloads, e.g., Binance:
    [
        0: Open time, 1: Open, 2: High, 3: Low, 4: Close, 5: Volume, 
        6: Close time, 7: Quote asset vol, 8: Trades, 
        9: Taker buy base vol, 10: Taker buy quote vol, 11: Ignore
    ]
    """
    open_time: int
    open: float
    high: float
    low: float
    close: float
    volume: float
    close_time: int
    quote_volume: Optional[float] = None
    trades: Optional[int] = None
    taker_buy_base: Optional[float] = None
    taker_buy_quote: Optional[float] = None

@dataclass
class OpenInterestData:
    """Standardized representation of Open Interest."""
    symbol: str
    open_interest: float
    timestamp: int

@dataclass
class RatioData:
    """Standardized representation of trader positioning (Long/Short ratio)."""
    long_short_ratio: float
    timestamp: int

@dataclass
class LiquidationData:
    """Standardized representation of a forced liquidation event."""
    price: float
    qty: float
    side: str  # e.g., 'BUY' or 'SELL'
    timestamp: int

@dataclass
class FundingRateData:
    """Standardized representation of funding rates for perpetual futures."""
    funding_rate: float
    timestamp: int

@dataclass
class GenericOrderBook:
    """Standardized representation of an Order Book depth snapshot."""
    bids: List[List[float]]  # List of [price, quantity]
    asks: List[List[float]]  # List of [price, quantity]
    timestamp: int
