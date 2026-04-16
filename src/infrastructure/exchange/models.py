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

@dataclass
class MarginAsset:
    """Represents an asset in a Margin account."""
    asset: str
    free: float
    locked: float
    borrowed: float
    interest: float
    net_asset: float

@dataclass
class MarginAccountSummary:
    """Summary of a Spot Margin account (Cross or Isolated)."""
    total_asset_of_btc: float
    total_liability_of_btc: float
    total_net_asset_of_btc: float
    margin_level: float
    status: str  # e.g., 'NORMAL', 'MARGIN_CALL', 'PRE_LIQUIDATION', 'FORCE_LIQUIDATION'
    assets: List[MarginAsset]

@dataclass
class MarginOrder:
    """Standardized representation of a Margin order."""
    symbol: str
    order_id: int
    client_order_id: str
    price: float
    orig_qty: float
    executed_qty: float
    status: str
    time_in_force: str
    type: str
    side: str
    update_time: int
    stop_price: float = 0.0
    is_isolated: bool = False

@dataclass
class MarginPosition:
    """Derived model for a specific pair's net position in Margin."""
    symbol: str
    base_asset: str
    quote_asset: str
    net_qty: float
    borrowed: float
    free: float
    locked: float
