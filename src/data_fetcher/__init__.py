"""
Data Fetcher Module:
Handles all I/O with external Binance APIs and local storage.
- binance_client.py: Technical price candles and order book.
- sentiment.py: Psychological metrics (OI, Long/Short Ratio).
- storage.py: Persistence of results and history.
"""
from .binance_client import BinanceDataFetcher
from .sentiment import SentimentFetcher

__all__ = ["BinanceDataFetcher", "SentimentFetcher"]
