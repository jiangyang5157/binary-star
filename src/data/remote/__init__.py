"""
Remote Data Layer:
Handles data acquisition from external sources.
"""
from .binance_client import BinanceFuturesClient

__all__ = ["BinanceFuturesClient"]
