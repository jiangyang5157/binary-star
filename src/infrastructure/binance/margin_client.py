import os
import time
from typing import List, Optional
from binance.spot import Spot
from binance.error import ClientError, ServerError
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
            logger.error("API key or secret missing | margin operations require authentication")
            raise ValueError("Authenticated access required for Margin operations.")

        self.client = Spot(api_key=key, api_secret=secret)
        self._precisions_cache: dict = {}  # symbol → (p_qty, p_price, tolerance)
        self._entry_cache: dict = {}  # symbol → (net_qty, avg_entry)
        logger.info("initialized for Spot Margin access")

    def close(self):
        """Release the underlying HTTP session to prevent connection leaks."""
        try:
            if hasattr(self.client, 'session'):
                self.client.session.close()
        except Exception as e:
            logger.warning("margin client close failed | error=%s", e)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

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
            logger.error(f"margin account fetch failed | error={e.error_message}")
            raise
        except ServerError as e:
            logger.error(f"margin account fetch failed (server) | status={e.status_code}")
            raise
        except Exception as e:
            logger.error(f"margin account fetch error | error={e}")
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
                        order_id=str(o.get('orderId', '')),
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
                    logger.error(f"order parse failed | order={o} | error={ex}")
            return orders
        except ClientError as e:
            logger.error(f"open orders fetch failed | error={e.error_message}")
            raise
        except ServerError as e:
            logger.error(f"open orders fetch failed (server) | status={e.status_code}")
            raise

    def get_ticker_price(self, symbol: str) -> float:
        """
        Fetches the latest price for a symbol.
        API: GET /api/v3/ticker/price
        """
        try:
            resp = self.client.ticker_price(symbol=symbol)
            return float(resp.get('price', 0))
        except Exception as e:
            logger.error(f"ticker price fetch failed | symbol={symbol} | error={e}")
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
        from src.utils.symbol_utils import get_quote_currency
        quote = get_quote_currency()
        base_asset = symbol[:-len(quote)] if symbol.endswith(quote) else symbol.replace(quote, "")

        target_asset = next((a for a in summary.assets if a.asset == base_asset), None)

        if not target_asset:
            return None

        return MarginPosition(
            symbol=symbol,
            base_asset=base_asset,
            quote_asset=quote,
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
            logger.info(f"all orders cancelled | symbol={symbol}")
            return True
        except ClientError as e:
            # -2011 represents 'Unknown order sent', indicating no open orders were found.
            if e.error_code == -2011:
                return True
            logger.error(f"cancel orders failed | symbol={symbol} | error={e.error_message}")
            return False
        except ServerError as e:
            logger.error(f"cancel orders failed (server) | symbol={symbol} | status={e.status_code}")
            return False

    def _get_precisions(self, symbol: str):
        """Loads precisions and tolerances from config. Cached per symbol."""
        if symbol in self._precisions_cache:
            return self._precisions_cache[symbol]

        import os
        from src.utils.path_utils import resolve_project_root
        from src.config.symbol_resolver import get_symbol_trade_params

        config_path = os.path.join(resolve_project_root(), "config", "global_config.yaml")
        if not os.path.exists(config_path):
            raise FileNotFoundError(f"Global configuration file missing at {config_path}")

        with open(config_path, 'r') as f:
            import yaml
            cfg = yaml.safe_load(f)

        tolerance = cfg["trade_management"]["net_qty_tolerance"]

        sym_cfg = get_symbol_trade_params(symbol)
        p_qty = sym_cfg["precision_qty"]
        p_price = sym_cfg["precision_price"]

        result = (p_qty, p_price, tolerance)
        self._precisions_cache[symbol] = result
        return result

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
            logger.info(f"market closed | symbol={symbol} | qty={qty} | side={side}")
            return True
        except ClientError as e:
            logger.error(f"market close failed | symbol={symbol} | error={e.error_message}")
            return False
        except ServerError as e:
            logger.error(f"market close failed (server) | symbol={symbol} | status={e.status_code}")
            return False

    def execute_partial_market_close(self, symbol: str, side: str, qty: float) -> bool:
        """Market-sell a specific quantity on the given side. For partial TP."""
        p_qty, _, _ = self._get_precisions(symbol)
        try:
            self.client.new_margin_order(
                symbol=symbol,
                side=side,
                type="MARKET",
                quantity=round(qty, p_qty),
                sideEffectType="MARGIN_BUY"
            )
            logger.info(f"partial market close | symbol={symbol} | qty={qty} | side={side}")
            return True
        except ClientError as e:
            logger.error(f"partial market close failed | symbol={symbol} | error={e.error_message}")
            return False
        except ServerError as e:
            logger.error(f"partial market close server error | symbol={symbol} | error={e.message}")
            return False

    def place_limit_order(self, symbol: str, side: str, qty: float, price: float) -> Optional[int]:
        """Places a standard LIMIT order on cross-margin. Returns order_id or None on failure."""
        p_qty, p_price, _ = self._get_precisions(symbol)
        tag = self._make_tag(symbol, "entry")
        try:
            resp = self.client.new_margin_order(
                symbol=symbol,
                side=side,
                type="LIMIT",
                quantity=round(qty, p_qty),
                price=round(price, p_price),
                timeInForce="GTC",
                newClientOrderId=tag,
                sideEffectType="MARGIN_BUY"
            )
            order_id = resp.get('orderId')
            logger.info(f"order placed | tag={tag} | side={side} | symbol={symbol} | order_id={order_id} | price={price} | qty={qty}")
            return order_id
        except ClientError as e:
            logger.error(f"limit order failed | symbol={symbol} | error={e.error_message}")
            return None
        except ServerError as e:
            logger.error(f"limit order failed (server) | symbol={symbol} | status={e.status_code}")
            return None

    def cancel_order(self, symbol: str, order_id: int) -> bool:
        """Cancels a specific margin order by ID."""
        try:
            self.client.cancel_margin_order(symbol=symbol, orderId=order_id)
            logger.info(f"order cancelled | order_id={order_id} | symbol={symbol}")
            return True
        except ClientError as e:
            if e.error_code == -2011:  # Unknown order (already filled/cancelled)
                logger.info(f"order already gone | order_id={order_id}")
                return True
            logger.error(f"cancel order failed | order_id={order_id} | error={e.error_message}")
            return False
        except ServerError as e:
            logger.error(f"cancel order failed (server) | order_id={order_id} | status={e.status_code}")
            return False

    @staticmethod
    def _round_price(value: float, decimals: int, side: str) -> float:
        """Directional round: SELL→floor (toward/away from price), BUY→ceil.

        For a SELL (LONG exit): TP is above price → floor = toward (conservative fill).
        SL is below price → floor = away (safe trigger, earlier activation).
        For a BUY (SHORT exit): both round up for the same reasons.
        """
        import math
        factor = 10 ** decimals
        if side == "SELL":
            return math.floor(value * factor) / factor
        else:
            return math.ceil(value * factor) / factor

    @staticmethod
    def _make_tag(symbol: str, tag_type: str) -> str:
        """Build order tag for bot identification on exchange.

        Tag is set via newClientOrderId (entry) or listClientOrderId (OCO),
        so bot orders can be distinguished from user's manual orders.

        Format: bot_{symbol}_{type}_{ms_timestamp}
        """
        return f"bot_{symbol}_{tag_type}_{int(time.time() * 1000)}"

    @staticmethod
    def _fifo_avg_entry(trades: list, net_qty: float) -> float:
        """FIFO weighted average entry price from trade history.

        LONG (net_qty > 0): BUY opens, SELL closes → FIFO deduplicates buys.
        SHORT (net_qty < 0): SELL opens, BUY closes → FIFO deduplicates sells.
        Returns 0.0 if insufficient trade history to cover |net_qty|.
        """
        abs_qty = abs(net_qty)
        is_long = net_qty > 0
        open_side = "BUY" if is_long else "SELL"
        close_side = "SELL" if is_long else "BUY"

        # Sort by trade ID ascending (chronological)
        sorted_trades = sorted(trades, key=lambda t: t.get('id', 0))

        queue = []  # list of (price, qty) for open-side trades still "alive"
        for t in sorted_trades:
            is_buyer = t.get('isBuyer')
            side = "BUY" if is_buyer else "SELL"
            price = float(t.get('price', 0))
            qty = float(t.get('qty', 0))

            if side == open_side:
                queue.append((price, qty))
            elif side == close_side:
                remaining_close = qty
                while remaining_close > 0 and queue:
                    oldest_price, oldest_qty = queue[0]
                    if oldest_qty <= remaining_close:
                        remaining_close -= oldest_qty
                        queue.pop(0)
                    else:
                        queue[0] = (oldest_price, oldest_qty - remaining_close)
                        remaining_close = 0

        total_qty = sum(q for _, q in queue)

        # Trim excess from oldest end: when queue qty exceeds position qty,
        # older trades are residual from prior positions that were never fully
        # closed (e.g. manual partial exit).  Discard them so the weighted
        # average reflects only the current position's entry.
        while total_qty > abs_qty * 1.01 and queue:
            excess = total_qty - abs_qty
            oldest_price, oldest_qty = queue[0]
            if oldest_qty <= excess:
                total_qty -= oldest_qty
                queue.pop(0)
            else:
                queue[0] = (oldest_price, oldest_qty - excess)
                total_qty = abs_qty
                break

        if total_qty <= 0 or total_qty < abs_qty * 0.99:
            return 0.0  # Insufficient history

        return sum(p * q for p, q in queue) / total_qty

    def get_avg_entry_price(self, symbol: str, net_qty: float) -> float:
        """Returns average entry price for current net position. Cached per symbol.

        Only calls margin_my_trades when net_qty changed from cached value.
        Falls back to pagination (fromId) if 500 trades don't cover the position.
        Returns 0.0 if position is flat or trade history unavailable.
        """
        tolerance = 1e-8
        if abs(net_qty) < tolerance:
            return 0.0

        cached = self._entry_cache.get(symbol)
        if cached is not None:
            cached_qty, cached_entry = cached
            if abs(cached_qty - net_qty) < tolerance:
                return cached_entry

        # Net qty changed — fetch trade history and recompute
        all_trades = []
        from_id = None
        abs_qty = abs(net_qty)

        while True:
            kwargs = {'symbol': symbol, 'limit': 500}
            if from_id is not None:
                kwargs['fromId'] = from_id
            try:
                trades = self.client.margin_my_trades(**kwargs)
            except Exception as e:
                logger.error(f"myTrades fetch failed | symbol={symbol} | error={e}")
                return cached_entry if cached else 0.0

            if not trades:
                break

            all_trades.extend(trades)
            from_id = min(int(t.get('id', 0)) for t in trades) - 1

            # Check if we have enough coverage
            avg = self._fifo_avg_entry(all_trades, net_qty)
            if avg > 0:
                self._entry_cache[symbol] = (net_qty, avg)
                logger.info(f"avg_entry refreshed | symbol={symbol} | entry={avg:.2f} | qty={net_qty}")
                return avg

            if len(trades) < 500:
                break

        # Exhausted all trades, try one final calculation
        avg = self._fifo_avg_entry(all_trades, net_qty)
        if avg > 0:
            self._entry_cache[symbol] = (net_qty, avg)
            return avg

        logger.warning(f"avg_entry unavailable | symbol={symbol} | qty={net_qty} | trades_scanned={len(all_trades)}")
        return cached_entry if cached else 0.0

    def place_oco_order(self, symbol: str, side: str, qty: float, price: float, stop_price: float, stop_limit_price: float) -> bool:
        """Places a standard OCO order to manage an existing position's exit.

        Prices are directionally rounded: TP toward current price (conservative fill),
        SL trigger away from current price (safe, earlier activation).
        """
        p_qty, p_price, _ = self._get_precisions(symbol)
        tag = self._make_tag(symbol, "oco")
        try:
            self.client.new_margin_oco_order(
                symbol=symbol,
                side=side,
                quantity=round(qty, p_qty),
                price=self._round_price(price, p_price, side),
                stopPrice=self._round_price(stop_price, p_price, side),
                stopLimitPrice=self._round_price(stop_limit_price, p_price, side),
                stopLimitTimeInForce="GTC",
                listClientOrderId=tag,
                sideEffectType="MARGIN_BUY",
            )
            logger.info(f"OCO placed | tag={tag} | symbol={symbol} | side={side} | qty={qty}")
            return True
        except ClientError as e:
            logger.error(f"OCO failed | symbol={symbol} | error={e.error_message}")
            return False
        except ServerError as e:
            logger.error(f"OCO failed (server) | symbol={symbol} | status={e.status_code}")
            return False

    def place_otoco_order(self, symbol: str, side: str, qty: float, entry_price: float, tp_price: float, sl_trigger_price: float, sl_limit_price: float) -> Optional[int]:
        """Places an OTOCO order specifying entry, and nested TP/SL.

        TP/SL prices are directionally rounded using the pending (exit) side:
        TP toward current price (conservative fill), SL trigger away (safe).
        """
        p_qty, p_price, _ = self._get_precisions(symbol)
        try:
            pending_side = "SELL" if side == "BUY" else "BUY"

            # Formulating parameters for SAPI OTOCO
            params = {
                "symbol": symbol,
                "workingType": "LIMIT",
                "workingSide": side,
                "workingPrice": self._round_price(entry_price, p_price, side),
                "workingQuantity": round(qty, p_qty),
                "pendingQuantity": round(qty, p_qty),
                "workingTimeInForce": "GTC",
                "pendingSide": pending_side,
                "pendingAboveTimeInForce": "GTC",
                "pendingBelowTimeInForce": "GTC",
                "sideEffectType": "MARGIN_BUY",
            }

            if side == "BUY":
                # Entry lower -> TP is higher(ABOVE), SL is lower(BELOW)
                params["pendingAboveType"] = "LIMIT_MAKER"
                params["pendingBelowType"] = "STOP_LOSS_LIMIT"

                params["pendingAbovePrice"] = self._round_price(tp_price, p_price, pending_side)
                params["pendingBelowStopPrice"] = self._round_price(sl_trigger_price, p_price, pending_side)
                params["pendingBelowPrice"] = self._round_price(sl_limit_price, p_price, pending_side)
            else:
                # Entry higher -> TP is lower(BELOW), SL is higher(ABOVE)
                params["pendingAboveType"] = "STOP_LOSS_LIMIT"
                params["pendingBelowType"] = "LIMIT_MAKER"

                params["pendingBelowPrice"] = self._round_price(tp_price, p_price, pending_side)
                params["pendingAboveStopPrice"] = self._round_price(sl_trigger_price, p_price, pending_side)
                params["pendingAbovePrice"] = self._round_price(sl_limit_price, p_price, pending_side)
            
            resp = self.client.sign_request("POST", "/sapi/v1/margin/order/otoco", params)
            order_list_id = resp.get("orderListId")
            logger.info(f"OTOCO placed | symbol={symbol} | order_list_id={order_list_id}")
            return order_list_id
        except Exception as e:
            logger.error(f"OTOCO failed | symbol={symbol} | error={e}")
            return None
