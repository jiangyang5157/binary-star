import logging
import os
from typing import Optional, List
from src.infrastructure.binance.margin_client import BinanceMarginClient
from src.infrastructure.exchange.models import MarginOrder
from src.utils.logger_utils import setup_logger

logger = setup_logger(__name__)

class MarginOrderExecutor:
    """
    Orchestrates the order management lifecycle for Margin trading.
    Implements the "Conflict Decider" logic to protect Net Qty, pivot positions,
    and handle OCO/OTOCO executions.
    """
    def __init__(self, client: Optional[BinanceMarginClient] = None):
        self.client = client or BinanceMarginClient()

    def _is_symbol_whitelisted(self, symbol: str) -> bool:
        """Checks if the symbol is explicitly defined in global_config.yaml's trade_management block."""
        import yaml, os
        from src.utils.path_utils import resolve_project_root
        try:
            config_path = os.path.join(resolve_project_root(), "config", "global_config.yaml")
            if os.path.exists(config_path):
                with open(config_path, 'r') as f:
                    cfg = yaml.safe_load(f)
                    tm = cfg.get("trade_management", {})
                    # Explicit checking: symbol must be a registered dict inside trade_management
                    if symbol in tm and isinstance(tm[symbol], dict):
                        return True
        except Exception as e:
            logger.error(f"Executor: Error verifying whitelist for {symbol}: {e}")
        return False

    def sync_with_opinion(self, symbol: str, opinion_direction: str, entry_price: float, tp_price: float, sl_price: float):
        """
        The central brain for syncing the current Binance state with a newly generated AI Opinion.
        """
        logger.info(f"Executor: Syncing {symbol} with new Opinion: {opinion_direction} (Entry: {entry_price}, TP: {tp_price}, SL: {sl_price})")
        
        # [SAFETY GUARD] Explicit Whitelist Check
        if not self._is_symbol_whitelisted(symbol):
            logger.warning(f"Executor: [ABORT] Symbol {symbol} is NOT configured in trade_management. Operation halted globally.")
            return
            
        pos = self.client.get_symbol_position(symbol)
        active_orders = self.client.get_active_orders(symbol)
        
        net_qty = pos.net_qty if pos else 0.0
        
        # Load logic limits with strict fail-fast error handling
        try:
            cfg = self._get_trade_config(symbol)
            tolerance = cfg["net_qty_tolerance"]
        except Exception as e:
            logger.error(f"Executor: [ABORT] Configuration error: {e}. Cannot safely execute orders without strict parameters.")
            return
        
        # Determine Current Direction
        current_direction = "FLAT"
        if net_qty > tolerance:
            current_direction = "LONG"
        elif net_qty < -tolerance:
            current_direction = "SHORT"

        logger.info(f"Executor: Current State -> Direction: {current_direction}, Net Qty: {net_qty}")

        # Scenario C: FLAT
        if current_direction == "FLAT":
            if active_orders:
                logger.info("Executor: [Action] Flat but found active orders. Cancelling all to clear the slate.")
                if not self.client.cancel_all_symbol_orders(symbol):
                    logger.error("Executor: [ABORT] Failed to clear stale orders. Halting new order placement for safety.")
                    return
            
            logger.info("Executor: [Action] Placing new OTOCO order.")
            self._place_otoco(symbol, opinion_direction, entry_price, tp_price, sl_price)
            return

        # Scenario A: PIVOT (Opposite Direction)
        if current_direction != opinion_direction:
            logger.warning(f"Executor: [Action] BIG PIVOT detected! Current: {current_direction}, New: {opinion_direction}")
            logger.warning("Executor: Cancelling all orders and forcefully closing current position.")
            
            if not self.client.cancel_all_symbol_orders(symbol):
                logger.error("Executor: [ABORT PIVOT] Failed to cancel existing orders. Halting pivot to prevent duplicate exposure.")
                return
                
            if not self.client.execute_market_close(symbol):
                logger.error("Executor: [ABORT PIVOT] Failed to Market Close existing position. Halting new order placement.")
                return
            
            logger.info("Executor: [Action] Placing new OTOCO order after successful pivot clean-up.")
            self._place_otoco(symbol, opinion_direction, entry_price, tp_price, sl_price)
            return

        # Scenario B: SAME DIRECTION (Optimization & Net Qty Protection)
        logger.info("Executor: [Action] Same direction detected. Optimizing existing position protection.")
        self._optimize_same_direction(symbol, current_direction, net_qty, active_orders, tp_price, sl_price)

    def _optimize_same_direction(self, symbol: str, direction: str, net_qty: float, active_orders: List[MarginOrder], new_tp: float, new_sl: float):
        """
        Calculates the best TP/SL comparing existing manual/script orders vs new opinion.
        Protects the ENTIRE net_qty.
        """
        current_tps = []
        current_sls = []

        # Analyze current active orders for existing TP/SL
        exit_side = "SELL" if direction == "LONG" else "BUY"
        for order in active_orders:
            if order.side == exit_side:
                if order.type in ["LIMIT", "LIMIT_MAKER"]:
                    current_tps.append(order.price)
                elif order.type in ["STOP_LOSS", "STOP_LOSS_LIMIT"]:
                    current_sls.append(order.stop_price if order.stop_price > 0 else order.price)

        best_tp = new_tp
        best_sl = new_sl

        # Pick the tightest SL (less risk) and widest TP (more reward)
        if direction == "LONG":
            if current_tps:
                best_tp = max(max(current_tps), new_tp) # Higher TP is better
            if current_sls:
                best_sl = max(max(current_sls), new_sl) # Higher SL is less loss
        else: # SHORT
            if current_tps:
                best_tp = min(min(current_tps), new_tp) # Lower TP is better
            if current_sls:
                best_sl = min(min(current_sls), new_sl) # Lower SL is less loss

        logger.info(f"Executor: Optimized TP -> {best_tp} (Opinion was {new_tp})")
        logger.info(f"Executor: Optimized SL -> {best_sl} (Opinion was {new_sl})")

        # Clean slate the orders to apply the unified OCO over the entire Net Qty
        logger.info(f"Executor: Cancelling existing orders to wrap entire Net Qty ({net_qty}) with new OCO.")
        if not self.client.cancel_all_symbol_orders(symbol):
            logger.error("Executor: [ABORT OPTIMIZATION] Failed to cancel existing OCOs. Original protection remains active.")
            return

        # Calculate buffered SL Limit (Slippage protection)
        trade_cfg = self._get_trade_config(symbol)
        buffer = trade_cfg.get("sl_slippage_buffer", 0.0)
        # LONG SL (Sell): Limit < Trigger | SHORT SL (Buy): Limit > Trigger
        buffered_sl = best_sl + (buffer if direction == "SHORT" else -buffer)

        # Place the OCO for the full position
        success = self.client.place_oco_order(
            symbol=symbol,
            side=exit_side,
            qty=abs(net_qty),
            price=best_tp,
            stop_price=best_sl,
            stop_limit_price=buffered_sl 
        )
        if not success:
             logger.error("Executor: [CRITICAL] Cancelled old OCO but failed to place new OCO. Position may be unprotected!")

    def _get_trade_config(self, symbol: str):
        """Loads and returns strict configuration. Raises Exception if missing."""
        import yaml, os
        from src.utils.path_utils import resolve_project_root
        
        config_path = os.path.join(resolve_project_root(), "config", "global_config.yaml")
        if not os.path.exists(config_path):
            raise FileNotFoundError(f"Global configuration file missing at {config_path}")
            
        with open(config_path, 'r') as f:
            full_cfg = yaml.safe_load(f)
            
        cfg = {}
        # Strict parsing: intentionally raises KeyError if keys are missing
        cfg["benchmark_symbol"] = full_cfg["system"]["default_symbol"]
        
        tm = full_cfg["trade_management"]
        cfg["risk_per_trade"] = tm["risk_per_trade"]
        cfg["net_qty_tolerance"] = tm["net_qty_tolerance"]
        
        sym_cfg = tm[symbol]
        cfg["precision_qty"] = sym_cfg["precision_qty"]
        cfg["precision_price"] = sym_cfg["precision_price"]
        cfg["min_order_qty"] = sym_cfg["min_order_qty"]
        cfg["sl_slippage_buffer"] = sym_cfg.get("sl_slippage_buffer", 0.0)
        
        return cfg

    def _calculate_target_qty(self, symbol: str, entry_price: float, sl_price: float) -> float:
        """
        Calculates the target quantity based on Risk % and Stop Loss distance.
        """
        # 1. Load config
        trade_cfg = self._get_trade_config(symbol)
        risk_pct = trade_cfg["risk_per_trade"]
        p_qty = trade_cfg["precision_qty"]
        min_qty = trade_cfg["min_order_qty"]
        benchmark_symbol = trade_cfg["benchmark_symbol"]

        # 2. Get Total Net Equity in USDT
        account = self.client.get_cross_margin_account()
        # Converts absolute BTC equity value into USDT
        current_price = self.client.get_ticker_price(benchmark_symbol) 
        
        total_equity_btc = account.total_net_asset_of_btc
        total_equity_usdt = total_equity_btc * current_price
        
        # 3. Calculate Risk Amount
        max_loss_usdt = total_equity_usdt * risk_pct
        
        # 4. Calculate Distance
        price_delta = abs(entry_price - sl_price)
        if price_delta <= 0:
            logger.error(f"Executor: Invalid Stop Loss (Delta = 0). Fallback to minimal qty: {min_qty}")
            return min_qty

        # 5. Determine Quantity
        target_qty = max_loss_usdt / price_delta
        target_qty = round(target_qty, p_qty)
        
        # Ensure it meets minimum
        target_qty = max(target_qty, min_qty)
        
        logger.info(f"Executor [Risk Management]: Equity=${total_equity_usdt:.2f}, Risk=%.2f%%, MaxLoss=${max_loss_usdt:.2f}" % (risk_pct * 100))
        logger.info(f"Executor [Risk Management]: Entry={entry_price}, SL={sl_price}, Delta=${price_delta:.2f} -> Sized Qty={target_qty}")
        return target_qty

    def _place_otoco(self, symbol: str, direction: str, entry_price: float, tp_price: float, sl_price: float):
        dynamic_qty = self._calculate_target_qty(symbol, entry_price, sl_price)
        
        # Calculate buffered SL Limit
        trade_cfg = self._get_trade_config(symbol)
        buffer = trade_cfg.get("sl_slippage_buffer", 0.0)
        # LONG SL: Limit < Trigger | SHORT SL: Limit > Trigger
        buffered_sl = sl_price + (buffer if direction == "SHORT" else -buffer)
        
        side = "BUY" if direction == "LONG" else "SELL"
        self.client.place_otoco_order(
            symbol=symbol, 
            side=side, 
            qty=dynamic_qty, 
            entry_price=entry_price, 
            tp_price=tp_price, 
            sl_trigger_price=sl_price,
            sl_limit_price=buffered_sl
        )
