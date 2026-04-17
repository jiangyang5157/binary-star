import os
from typing import List, Optional
from binance.spot import Spot
from binance.error import ClientError
from src.utils.logger_utils import setup_logger
from src.infrastructure.exchange.models import (
    MarginAccountSummary,
    MarginAsset,
    MarginOrder,
    MarginPosition
)

logger = setup_logger(__name__)

class BinanceMarginClient:
    """
    Client for Binance Spot Margin (Cross) operations.
    Focused on managing orders and monitoring account state (borrowing/risk).
    """

    def __init__(self, api_key: Optional[str] = None, api_secret: Optional[str] = None):
        key = api_key or os.environ.get("BINANCE_API_KEY")
        secret = api_secret or os.environ.get("BINANCE_API_SECRET")
        
        if not key or not secret:
            logger.error("BinanceMarginClient: API Key or Secret missing. Margin operations require authentication.")
            raise ValueError("Authenticated access required for Margin operations.")

        self.client = Spot(api_key=key, api_secret=secret)
        logger.info("BinanceMarginClient initialized for authenticated Spot Margin access.")

    def get_cross_margin_account(self) -> MarginAccountSummary:
        """
        Fetches Cross Margin account details.
        API: GET /sapi/v1/margin/account
        """
        try:
            resp = self.client.margin_account()
            
            assets = [
                MarginAsset(
                    asset=a['asset'],
                    free=float(a['free']),
                    locked=float(a['locked']),
                    borrowed=float(a['borrowed']),
                    interest=float(a['interest']),
                    net_asset=float(a['netAsset'])
                ) for a in resp.get('userAssets', [])
                if float(a['free']) > 0 or float(a['borrowed']) > 0 or float(a['locked']) > 0
            ]

            return MarginAccountSummary(
                total_asset_of_btc=float(resp.get('totalAssetOfBtc', 0)),
                total_liability_of_btc=float(resp.get('totalLiabilityOfBtc', 0)),
                total_net_asset_of_btc=float(resp.get('totalNetAssetOfBtc', 0)),
                margin_level=float(resp.get('marginLevel', 999.0)),
                status=resp.get('tradeEnabled', False) and 'NORMAL' or 'BLOCKED', # Simplified status
                assets=assets
            )
        except ClientError as e:
            logger.error(f"BinanceMarginClient: Failed to fetch margin account: {e.error_message}")
            raise
        except Exception as e:
            logger.error(f"BinanceMarginClient: Unexpected error: {e}")
            raise

    def get_active_orders(self, symbol: Optional[str] = None) -> List[MarginOrder]:
        """
        Fetches open Margin orders.
        API: GET /sapi/v1/margin/openOrders
        """
        try:
            # Note: Binance SAPI openOrders for margin
            resp = self.client.margin_open_orders(symbol=symbol)
            
            orders = []
            for o in resp:
                try:
                    orders.append(MarginOrder(
                        symbol=o.get('symbol', 'UNKNOWN'),
                        order_id=o.get('orderId', 0),
                        client_order_id=o.get('clientOrderId', ''),
                        price=float(o.get('price', 0)),
                        orig_qty=float(o.get('origQty', o.get('qty', 0))),
                        executed_qty=float(o.get('executedQty', 0)),
                        status=o.get('status', 'UNKNOWN'),
                        time_in_force=o.get('timeInForce', 'GTC'),
                        type=o.get('type', 'LIMIT'),
                        side=o.get('side', 'BUY'),
                        update_time=o.get('updateTime', 0),
                        stop_price=float(o.get('stopPrice', 0))
                    ))
                except Exception as ex:
                    logger.error(f"Error parsing order: {o}. Error: {ex}")
            return orders
        except ClientError as e:
            logger.error(f"BinanceMarginClient: Failed to fetch open orders: {e.error_message}")
            return []

    def get_ticker_price(self, symbol: str) -> float:
        """
        Fetches the latest price for a symbol.
        API: GET /api/v3/ticker/price
        """
        try:
            resp = self.client.ticker_price(symbol=symbol)
            return float(resp.get('price', 0))
        except Exception as e:
            logger.error(f"BinanceMarginClient: Failed to fetch ticker price for {symbol}: {e}")
            return 0.0

    def get_symbol_position(self, symbol: str) -> Optional[MarginPosition]:
        """
        Derived helper to get the net position for a specific symbol (e.g. BTCUSDT).
        Calculates net quantity for the base asset.
        """
        # This is a bit complex in Spot Margin because it's asset-based, not symbol-based.
        # For BTCUSDT, we look at BTC asset.
        summary = self.get_cross_margin_account()
        
        # Assumption: standard pairs. This is a simplified version.
        # We'll just look for the base asset of the symbol.
        # e.g. for BTCUSDT, we look for BTC.
        base_asset = symbol.replace("USDT", "") # Simple heuristic
        
        target_asset = next((a for a in summary.assets if a.asset == base_asset), None)
        
        if not target_asset:
            return None
            
        return MarginPosition(
            symbol=symbol,
            base_asset=base_asset,
            quote_asset="USDT",
            net_qty=target_asset.net_asset,
            borrowed=target_asset.borrowed,
            free=target_asset.free,
            locked=target_asset.locked
        )

    # --- Write Operations / Execution ---

    def cancel_all_symbol_orders(self, symbol: str) -> bool:
        """Cancels all active margin orders for a given symbol."""
        try:
            self.client.margin_open_orders_cancellation(symbol=symbol)
            logger.info(f"BinanceMarginClient: Cancelled all open orders for {symbol}.")
            return True
        except ClientError as e:
            # -2011 represents 'Unknown order sent', indicating no open orders were found.
            if e.error_code == -2011:
                return True
            logger.error(f"BinanceMarginClient: Failed to cancel orders for {symbol}: {e.error_message}")
            return False

    def _get_precisions(self, symbol: str):
        """Loads precisions and tolerances from config. Raises Exception if missing."""
        import os, yaml
        from src.utils.path_utils import resolve_project_root
        
        config_path = os.path.join(resolve_project_root(), "config", "global_config.yaml")
        if not os.path.exists(config_path):
            raise FileNotFoundError(f"Global configuration file missing at {config_path}")
            
        with open(config_path, 'r') as f:
            cfg = yaml.safe_load(f)
            
        tm = cfg["trade_management"]
        tolerance = tm["net_qty_tolerance"]
        
        sym_cfg = tm[symbol]
        p_qty = sym_cfg["precision_qty"]
        p_price = sym_cfg["precision_price"]
        
        return p_qty, p_price, tolerance

    def execute_market_close(self, symbol: str) -> bool:
        """Closes any open net position for the symbol with a Market order."""
        pos = self.get_symbol_position(symbol)
        p_qty, _, tolerance = self._get_precisions(symbol)
        
        if not pos or abs(pos.net_qty) < tolerance:
            return True # Nothing to close
        
        side = "BUY" if pos.net_qty < 0 else "SELL"
        qty = round(abs(pos.net_qty), p_qty)
        
        try:
            self.client.new_margin_order(
                symbol=symbol,
                side=side,
                type="MARKET",
                quantity=qty,
                sideEffectType="MARGIN_BUY"  # Instructs to use auto-borrow logic if necessary
            )
            logger.info(f"BinanceMarginClient: Market closed {qty} of {symbol} (Side: {side}).")
            return True
        except ClientError as e:
            logger.error(f"BinanceMarginClient: Failed to market close {symbol}: {e.error_message}")
            return False

    def place_limit_order(self, symbol: str, side: str, qty: float, price: float) -> Optional[int]:
        """Places a standard LIMIT order on cross-margin. Returns order_id or None on failure."""
        p_qty, p_price, _ = self._get_precisions(symbol)
        try:
            resp = self.client.new_margin_order(
                symbol=symbol,
                side=side,
                type="LIMIT",
                quantity=round(qty, p_qty),
                price=round(price, p_price),
                timeInForce="GTC",
                sideEffectType="MARGIN_BUY"
            )
            order_id = resp.get('orderId')
            logger.info(f"BinanceMarginClient: Placed LIMIT {side} for {symbol}. OrderId: {order_id}, Price: {price}, Qty: {qty}")
            return order_id
        except ClientError as e:
            logger.error(f"BinanceMarginClient: Failed to place LIMIT order for {symbol}: {e.error_message}")
            return None

    def cancel_order(self, symbol: str, order_id: int) -> bool:
        """Cancels a specific margin order by ID."""
        try:
            self.client.cancel_margin_order(symbol=symbol, orderId=order_id)
            logger.info(f"BinanceMarginClient: Cancelled order {order_id} for {symbol}.")
            return True
        except ClientError as e:
            if e.error_code == -2011:  # Unknown order (already filled/cancelled)
                logger.info(f"BinanceMarginClient: Order {order_id} already gone (likely filled/cancelled).")
                return True
            logger.error(f"BinanceMarginClient: Failed to cancel order {order_id}: {e.error_message}")
            return False

    def place_oco_order(self, symbol: str, side: str, qty: float, price: float, stop_price: float, stop_limit_price: float) -> bool:
        """Places a standard OCO order to manage an existing position's exit."""
        p_qty, p_price, _ = self._get_precisions(symbol)
        try:
            self.client.new_margin_oco_order(
                symbol=symbol,
                side=side,
                quantity=round(qty, p_qty),
                price=round(price, p_price),
                stopPrice=round(stop_price, p_price),
                stopLimitPrice=round(stop_limit_price, p_price),
                stopLimitTimeInForce="GTC"
            )
            logger.info(f"BinanceMarginClient: Placed OCO for {symbol}. Side: {side}, Qty: {qty}")
            return True
        except ClientError as e:
            logger.error(f"BinanceMarginClient: Failed to place OCO for {symbol}: {e.error_message}")
            return False

    def place_otoco_order(self, symbol: str, side: str, qty: float, entry_price: float, tp_price: float, sl_trigger_price: float, sl_limit_price: float) -> bool:
        """Places an OTOCO order specifying entry, and nested TP/SL."""
        p_qty, p_price, _ = self._get_precisions(symbol)
        try:
            pending_side = "SELL" if side == "BUY" else "BUY"
            
            # Formulating parameters for SAPI OTOCO
            params = {
                "symbol": symbol,
                "workingType": "LIMIT",
                "workingSide": side,
                "workingPrice": round(entry_price, p_price),
                "workingQuantity": round(qty, p_qty),
                "workingTimeInForce": "GTC",
                "pendingSide": pending_side,
                "pendingAboveTimeInForce": "GTC",
            }
            
            if side == "BUY":
                # Entry lower -> TP is higher(ABOVE), SL is lower(BELOW)
                params["pendingAboveType"] = "LIMIT_MAKER"
                params["pendingBelowType"] = "STOP_LOSS_LIMIT"
                
                params["pendingAbovePrice"] = round(tp_price, p_price)
                params["pendingBelowStopPrice"] = round(sl_trigger_price, p_price)
                params["pendingBelowPrice"] = round(sl_limit_price, p_price)
            else:
                # Entry higher -> TP is lower(BELOW), SL is higher(ABOVE)
                params["pendingAboveType"] = "STOP_LOSS_LIMIT"
                params["pendingBelowType"] = "LIMIT_MAKER"
                
                params["pendingBelowPrice"] = round(tp_price, p_price)
                params["pendingAboveStopPrice"] = round(sl_trigger_price, p_price)
                params["pendingAbovePrice"] = round(sl_limit_price, p_price)
            
            resp = self.client.send_request("POST", "/sapi/v1/margin/order/otoco", params)
            logger.info(f"BinanceMarginClient: Placed OTOCO for {symbol}. Resp: {resp.get('orderListId')}")
            return True
        except Exception as e:
            logger.error(f"BinanceMarginClient: Failed to place OTOCO for {symbol}: {e}")
            return False
