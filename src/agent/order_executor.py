import os
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any
from src.infrastructure.binance.margin_client import BinanceMarginClient
from src.infrastructure.exchange.models import MarginOrder
from src.utils.logger_utils import setup_logger

logger = setup_logger(__name__)

# Sentinel returned by sync_with_opinion when the position is emergency-closed
EMERGENCY_CLOSED_SENTINEL = -1

class MarginOrderExecutor:
    """
    Orchestrates the order management lifecycle for Margin trading.
    Implements the "Conflict Decider" logic to protect Net Qty, pivot positions,
    and handle OCO/LIMIT executions.
    
    Architecture: Two-Step Execution
    1. Entry via LIMIT order (since OTOCO is unavailable on Margin SAPI)
    2. Protection via OCO order (placed by Guardian on next Sniper pulse)
    """
    def __init__(self, client: Optional[BinanceMarginClient] = None, manual_balance_usdt: Optional[float] = None, global_config: Optional[dict] = None):
        self.client = client or BinanceMarginClient()
        self.manual_balance_usdt = manual_balance_usdt
        # Cache global_config to avoid re-reading from disk on every guardian/trade call
        if global_config is not None:
            self._global_config_raw = global_config
        else:
            import yaml, os
            from src.utils.path_utils import resolve_project_root
            config_path = os.path.join(resolve_project_root(), "config", "global_config.yaml")
            with open(config_path, 'r') as f:
                self._global_config_raw = yaml.safe_load(f)

    def _is_symbol_whitelisted(self, symbol: str) -> bool:
        """Checks if the symbol is defined in symbol_config.yaml."""
        from src.config.symbol_resolver import is_symbol_configured
        return is_symbol_configured(symbol)

    # ================================================================
    # ENTRY LOGIC: Called when AI issues a new directional opinion
    # ================================================================

    def sync_with_opinion(self, symbol: str, opinion_direction: str, entry_price: float, tp_price: float, sl_price: float) -> Optional[int]:
        """
        The central brain for syncing the current Binance state with a newly generated AI Opinion.
        Returns the entry order_id if a new LIMIT entry was placed, or None.
        """
        logger.info(f"Executor [{symbol}]: Syncing with new Opinion: {opinion_direction} (Entry: {entry_price}, TP: {tp_price}, SL: {sl_price})")
        
        # [SAFETY GUARD] Explicit Whitelist Check
        if not self._is_symbol_whitelisted(symbol):
            logger.warning(f"Executor: [ABORT] Symbol {symbol} is NOT configured in symbol_config.yaml. Operation halted globally.")
            return None
            
        pos = self.client.get_symbol_position(symbol)
        active_orders = self.client.get_active_orders(symbol)
        
        net_qty = pos.net_qty if pos else 0.0
        
        # Load logic limits with strict fail-fast error handling
        try:
            cfg = self._get_trade_config(symbol)
            tolerance = cfg["net_qty_tolerance"]
        except Exception as e:
            logger.error(f"Executor: [ABORT] Configuration error: {e}. Cannot safely execute orders without strict parameters.")
            return None
        
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
                    return None
            
            logger.info("Executor: [Action] Placing new LIMIT entry order.")
            return self._place_entry_order(symbol, opinion_direction, entry_price, sl_price)

        # Scenario A: PIVOT (Opposite Direction)
        if current_direction != opinion_direction:
            logger.warning(f"Executor: [Action] PIVOT detected! Current: {current_direction}, New: {opinion_direction}")
            
            # Determine if the opposing position has a stop loss order (i.e., it is protected)
            exit_side_of_current = "BUY" if current_direction == "SHORT" else "SELL"
            existing_sl_order = next(
                (o for o in active_orders
                 if o.side == exit_side_of_current
                 and o.type in ["STOP_LOSS", "STOP_LOSS_LIMIT"]
                 and o.stop_price > 0),
                None
            )
            
            if existing_sl_order:
                # Case A-2: Opposing position is protected → preserve it with adjusted TP + new entry
                original_sl_trigger = existing_sl_order.stop_price
                logger.info(
                    f"Executor: [Pivot-Preserve] Opposing {current_direction} has a stop loss at "
                    f"{original_sl_trigger}. Preserving position and adjusting TP."
                )
                
                # 2. Determine if the flip point has already been overshot
                current_price = self.client.get_ticker_price(symbol)
                is_overshot = (
                    (current_direction == "SHORT" and current_price <= entry_price) or
                    (current_direction == "LONG" and current_price >= entry_price)
                )

                if is_overshot:
                    logger.warning(
                        f"Executor: [Pivot-Overshot] Price {current_price} already past entry {entry_price}. "
                        f"Executing immediate Market Close for {current_direction}."
                    )
                    if not self.client.cancel_all_symbol_orders(symbol):
                        logger.error("Executor: [ABORT Pivot-Overshot] Failed to cancel orders.")
                        return None
                    if not self.client.execute_market_close(symbol):
                        logger.error("Executor: [ABORT Pivot-Overshot] Failed to Market Close.")
                        return None
                    
                    # Proceed to place new entry
                    logger.info(f"Executor: [Pivot-Overshot] Placing new {opinion_direction} LIMIT entry at {entry_price}.")
                    return self._place_entry_order(symbol, opinion_direction, entry_price, sl_price)

                # 3. Standard Case: Re-hang OCO with TP aligned to new entry
                pivot_tp = entry_price
                logger.info(f"Executor: [Pivot-Preserve] Protecting existing {current_direction} volume. Set its TP to {pivot_tp} (aligned with new entry for seamless flip).")
                
                # 1. Cancel all existing orders (clean slate before re-hanging)
                if not self.client.cancel_all_symbol_orders(symbol):
                    logger.error("Executor: [ABORT Pivot-Preserve] Failed to cancel existing orders.")
                    return None

                # Format to precision
                p_price = cfg["precision_price"]
                pivot_tp = round(pivot_tp, p_price)
                
                # 4. Re-hang OCO for the existing opposing position
                #    (original SL trigger + pivot TP)
                buffer = cfg.get("sl_slippage_buffer", 0.0)
                # SHORT SL is a BUY above current → limit is trigger + buffer
                # LONG  SL is a SELL below current → limit is trigger - buffer
                buffered_sl = original_sl_trigger + (buffer if current_direction == "SHORT" else -buffer)
                
                oco_success = self.client.place_oco_order(
                    symbol=symbol,
                    side=exit_side_of_current,
                    qty=abs(net_qty),
                    price=pivot_tp,
                    stop_price=original_sl_trigger,
                    stop_limit_price=buffered_sl
                )
                if not oco_success:
                    logger.critical(
                        "Executor: [EMERGENCY Pivot-Preserve] Failed to place OCO after cancel — "
                        "existing position is now naked. Emergency market closing + placing new entry."
                    )
                    self.client.execute_market_close(symbol)
                    # Position is closed but AI opinion is still valid — place new entry
                    logger.info(f"Executor: [Pivot-Preserve] Emergency close complete. Entering new {opinion_direction} at {entry_price}.")
                    return self._place_entry_order(symbol, opinion_direction, entry_price, sl_price)

                # 4. Place the new opinion's LIMIT entry alongside the preserved position
                logger.info(f"Executor: [Pivot-Preserve] Pivot setup complete. Entering new {opinion_direction} at {entry_price} (SL: {sl_price}).")
                return self._place_entry_order(symbol, opinion_direction, entry_price, sl_price)
            
            else:
                # Case A-1: No stop loss → opposing position is unprotected → force close
                logger.warning(
                    f"Executor: [Pivot-ForceClose] Opposing {current_direction} has NO stop loss. "
                    f"Cancelling all and market closing."
                )
                if not self.client.cancel_all_symbol_orders(symbol):
                    logger.error("Executor: [ABORT PIVOT] Failed to cancel existing orders. Halting pivot.")
                    return None
                    
                if not self.client.execute_market_close(symbol):
                    logger.error("Executor: [ABORT PIVOT] Failed to Market Close existing position. Halting new order placement.")
                    return None
                
                logger.info("Executor: [Pivot-ForceClose] Placing new LIMIT entry after force-close.")
                return self._place_entry_order(symbol, opinion_direction, entry_price, sl_price)

        # Scenario B: SAME DIRECTION (Optimization & Net Qty Protection)
        logger.info("Executor: [Action] Same direction detected. Optimizing existing position protection.")
        position_intact = self._optimize_same_direction(symbol, current_direction, net_qty, active_orders, tp_price, sl_price)
        if not position_intact:
            # Emergency close was triggered — return sentinel to signal caller that trade_state should be cleared
            logger.critical("Executor: [EMERGENCY Same-Direction] Position emergency-closed after OCO failure. Returning sentinel.")
            return EMERGENCY_CLOSED_SENTINEL
        return None

    # ================================================================
    # GUARDIAN LOGIC: Called every Sniper pulse to protect positions
    # ================================================================

    def guardian_check(self, symbol: str, trade_state: Dict[str, Any], atr_macro: Optional[float] = None) -> Dict[str, Any]:
        """
        Position Guardian: Runs every Sniper pulse to ensure positions are protected.
        
        Responsibilities:
        1. If PENDING entry order → check timeout (projected_waiting_hours) → cancel if expired
        2. If FILLED position with NO OCO → place OCO or emergency close
        3. If position already protected → progressive trailing stop migration
        
        Args:
            symbol: Trading pair identifier.
            trade_state: Current in-memory trade state dictionary.
            atr_macro: Current ATR value for trailing stop calculations.
        
        Returns updated trade_state.
        """

        # --- STEP 0: Heartbeat Reporting (Always runs if called) ---
        pos = self.client.get_symbol_position(symbol)
        net_qty = pos.net_qty if pos else 0.0
        active_orders = self.client.get_active_orders(symbol)
        
        try:
            cfg = self._get_trade_config(symbol)
            tolerance = cfg["net_qty_tolerance"]
        except Exception as e:
            logger.error(f"Guardian: [ABORT] Configuration error: {e}")
            return trade_state

        has_position = abs(net_qty) > tolerance
        logger.info(f"Guardian Pulse [{symbol}]: NetQty={net_qty}, HasPosition={has_position}, ActiveOrders={len(active_orders)}")

        # --- STEP 1: Intent Check (Early exit if robot has no skin in the game) ---
        if not trade_state or not trade_state.get("direction"):
            return trade_state  # Nothing to protect for now
        
        direction = trade_state["direction"]
        
        # Determine if OCO protection exists
        exit_side = "SELL" if direction == "LONG" else "BUY"
        has_oco = any(
            o.side == exit_side and o.type in ["STOP_LOSS", "STOP_LOSS_LIMIT"]
            for o in active_orders
        )

        # --- Case 1: No position yet (entry pending or expired) ---
        if not has_position:
            entry_order_id = trade_state.get("entry_order_id")
            if entry_order_id:
                # Check timeout
                placed_at = trade_state.get("entry_placed_at")
                timeout_hours = trade_state.get("projected_waiting_hours", 24.0)
                
                if placed_at:
                    elapsed_hours = (datetime.now(timezone.utc) - placed_at).total_seconds() / 3600
                    if elapsed_hours > timeout_hours:
                        logger.warning(f"Guardian: Entry order {entry_order_id} expired ({elapsed_hours:.1f}h > {timeout_hours}h). Cancelling.")
                        self.client.cancel_order(symbol, entry_order_id)
                        return {}  # Clear trade state
                    else:
                        logger.info(f"Guardian: Entry order {entry_order_id} still pending ({elapsed_hours:.1f}h / {timeout_hours}h).")
            return trade_state

        # --- Case 2: Has position -> Direction Sanity Check ---
        # Safeguard: Ensure reality's NetQty aligns with robot's Intent
        is_long_pos = net_qty > tolerance
        is_short_pos = net_qty < -tolerance
        intent = trade_state["direction"]

        if (intent == "LONG" and not is_long_pos) or (intent == "SHORT" and not is_short_pos):
            logger.warning(f"Guardian: [ORIENTATION CONFLICT] Intent={intent} but NetQty={net_qty}. "
                           f"Robot will NOT adopt this manual position and will keep tracking entry {trade_state.get('entry_order_id')}.")
            return trade_state

        # --- Case 3: Has position and direction matches -> Protect Position ---
        if not has_oco:
            tp = trade_state.get("tp_price")
            sl = trade_state.get("sl_price")
            
            if not tp or not sl:
                logger.error("Guardian: Has position but no TP/SL in trade_state. Cannot protect!")
                return trade_state

            # Check if price has already breached SL
            current_price = self.client.get_ticker_price(symbol)
            
            sl_breached = (
                (direction == "LONG" and current_price <= sl) or
                (direction == "SHORT" and current_price >= sl)
            )
            
            if sl_breached:
                logger.critical(f"Guardian: [EMERGENCY] Price {current_price} has breached SL {sl}! Market closing position.")
                self.client.cancel_all_symbol_orders(symbol)
                self.client.execute_market_close(symbol)
                return {}  # Clear trade state
            
            # Normal case: place OCO protection
            logger.info(f"Guardian: Position detected ({direction}, {net_qty}). Placing OCO protection (TP: {tp}, SL: {sl}).")
            
            # Clear any stale entry orders first
            entry_order_id = trade_state.get("entry_order_id")
            if entry_order_id:
                self.client.cancel_order(symbol, entry_order_id)
            
            buffer = cfg.get("sl_slippage_buffer", 0.0)
            buffered_sl = sl + (buffer if direction == "SHORT" else -buffer)
            
            success = self.client.place_oco_order(
                symbol=symbol,
                side=exit_side,
                qty=abs(net_qty),
                price=tp,
                stop_price=sl,
                stop_limit_price=buffered_sl
            )
            
            if success:
                logger.info("Guardian: OCO protection successfully placed.")
                # Update state: remove entry tracking, keep direction/prices
                trade_state.pop("entry_order_id", None)
                trade_state.pop("entry_placed_at", None)
                # Record fill time for time-based stop tracking
                if not trade_state.get("entry_filled_at"):
                    trade_state["entry_filled_at"] = datetime.now(timezone.utc).isoformat()
            else:
                logger.error("Guardian: [CRITICAL] Failed to place OCO protection! Position remains unprotected.")
            
            return trade_state

        # --- Case 4: Position is already protected → Progressive Trailing Stop ---
        logger.debug(f"Guardian: Position {direction} ({net_qty}) is protected.")
        
        if atr_macro and atr_macro > 0:
            trade_state = self._migrate_trailing_stop(symbol, direction, trade_state, active_orders, atr_macro)
        
        return trade_state

    # ================================================================
    # TRAILING STOP: Progressive SL migration
    # ================================================================

    def _migrate_trailing_stop(self, symbol: str, direction: str, trade_state: Dict[str, Any],
                                active_orders: List[MarginOrder], atr_macro: float) -> Dict[str, Any]:
        """
        Progressive Trailing Stop Migration (Deterministic, No AI).

        Moves SL based on unrealized profit measured in ATR units.
        Thresholds and offsets are read from global_config.yaml → guardian.
        Also enforces TIME-BASED STOP when holding exceeds the configured limit.

        WARNING: Canceling OCO and re-placing creates a brief naked window.
        On failure to re-place, falls back to emergency market close.
        """
        # Load guardian config
        gc = self._get_guardian_config()

        entry_price = trade_state.get("entry_price")
        current_sl = trade_state.get("sl_price")
        current_tp = trade_state.get("tp_price")
        current_level = trade_state.get("trailing_sl_level", 0)

        if not entry_price or not current_sl or not current_tp:
            return trade_state

        # --- 1. Time-Based Stop ---
        entry_filled_at_str = trade_state.get("entry_filled_at")
        projected_holding = trade_state.get("projected_holding_hours")
        if entry_filled_at_str and projected_holding:
            entry_filled_at = datetime.fromisoformat(entry_filled_at_str)
            elapsed_hours = (datetime.now(timezone.utc) - entry_filled_at).total_seconds() / 3600
            time_limit = float(projected_holding) * gc["time_stop_multiplier"]

            if elapsed_hours > time_limit:
                logger.warning(
                    f"Guardian: [TIME_STOP] Position held {elapsed_hours:.1f}h > limit {time_limit:.1f}h. "
                    f"Market closing {symbol}.")
                self.client.cancel_all_symbol_orders(symbol)
                self.client.execute_market_close(symbol)
                return {}  # Clear trade state

        # --- 2. Progressive Trailing Stop ---
        current_price = self.client.get_ticker_price(symbol)
        if not current_price or current_price <= 0:
            return trade_state

        # Safeguard: Prevent division by zero or extremely small ATR values
        if not atr_macro or atr_macro < 1e-6:
            logger.warning(f"Guardian: [TRAIL] Invalid or extremely small ATR value ({atr_macro}). Skipping migration.")
            return trade_state

        if direction == "LONG":
            unrealized_atr = (current_price - entry_price) / atr_macro
        else:  # SHORT
            unrealized_atr = (entry_price - current_price) / atr_macro

        # Determine target trailing level (thresholds from config)
        l1 = gc["trailing_profit_atr_level_1"]
        l2 = gc["trailing_profit_atr_level_2"]
        l3 = gc["trailing_profit_atr_level_3"]
        offset_2 = gc["trailing_sl_offset_atr_level_2"]
        offset_3 = gc["trailing_sl_offset_atr_level_3"]

        target_level = 0
        target_sl = current_sl

        if unrealized_atr >= l3:
            target_level = 3
            if direction == "LONG":
                target_sl = entry_price + offset_3 * atr_macro
            else:
                target_sl = entry_price - offset_3 * atr_macro
        elif unrealized_atr >= l2:
            target_level = 2
            if direction == "LONG":
                target_sl = entry_price + offset_2 * atr_macro
            else:
                target_sl = entry_price - offset_2 * atr_macro
        elif unrealized_atr >= l1:
            target_level = 1
            target_sl = entry_price  # Breakeven
        
        # Only migrate forward (never move SL backwards, never redundant migration)
        if target_level <= current_level:
            logger.debug(f"Guardian: [TRAIL] Unrealized={unrealized_atr:.1f}ATR, Level={current_level}. No migration.")
            return trade_state
        
        logger.info(
            f"Guardian: [TRAIL] Migrating SL Level {current_level} → {target_level} | "
            f"Unrealized={unrealized_atr:.1f}ATR | New SL={target_sl:.2f}")
        
        # --- 3. OCO Migration (Cancel + Re-place) ---
        try:
            cfg = self._get_trade_config(symbol)
            buffer = cfg.get("sl_slippage_buffer", 0.0)
            exit_side = "SELL" if direction == "LONG" else "BUY"
            
            # Step A: Cancel all existing orders
            if not self.client.cancel_all_symbol_orders(symbol):
                logger.error("Guardian: [TRAIL] Failed to cancel OCO. Keeping existing protection.")
                return trade_state
            
            # Step B: Place new OCO with migrated SL
            # Direction-aware buffer: LONG SL is SELL (limit < trigger), SHORT SL is BUY (limit > trigger)
            buffered_sl = target_sl + (buffer if direction == "SHORT" else -buffer)
            success = self.client.place_oco_order(
                symbol=symbol,
                side=exit_side,
                qty=abs(self.client.get_symbol_position(symbol).net_qty),
                price=current_tp,
                stop_price=target_sl,
                stop_limit_price=buffered_sl
            )
            
            if success:
                trade_state["sl_price"] = target_sl
                trade_state["trailing_sl_level"] = target_level
                logger.info(f"Guardian: [TRAIL] SL successfully migrated to {target_sl:.2f} (Level {target_level}).")
            else:
                # Step C: EMERGENCY — OCO re-placement failed, position is now NAKED
                logger.critical(
                    f"Guardian: [TRAIL][CRITICAL] OCO re-placement FAILED after cancel! "
                    f"Position is unprotected. Emergency market closing {symbol}.")
                self.client.execute_market_close(symbol)
                return {}  # Clear trade state
                
        except Exception as e:
            logger.error(f"Guardian: [TRAIL] Migration failed: {e}", exc_info=True)
        
        return trade_state

    # ================================================================
    # SAME-DIRECTION OPTIMIZATION
    # ================================================================

    def _optimize_same_direction(self, symbol: str, direction: str, net_qty: float, active_orders: List[MarginOrder], new_tp: float, new_sl: float) -> bool:
        """
        Calculates the best TP/SL comparing existing manual/script orders vs new opinion.
        Protects the ENTIRE net_qty.

        Returns:
            True if position remains protected, False if emergency-closed due to OCO failure.
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

        if current_tps:
            logger.info(f"Executor: Found existing TPs for {direction}: {current_tps}")
        if current_sls:
            logger.info(f"Executor: Found existing SLs for {direction}: {current_sls}")

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

        logger.info(f"Executor: Final Strategic Targets -> TP: {best_tp} (Opinion: {new_tp}), SL: {best_sl} (Opinion: {new_sl})")

        # Clean slate the orders to apply the unified OCO over the entire Net Qty
        logger.info(f"Executor: Cancelling existing orders to wrap entire Net Qty ({net_qty}) with new OCO.")
        if not self.client.cancel_all_symbol_orders(symbol):
            logger.error("Executor: [ABORT OPTIMIZATION] Failed to cancel existing OCOs. Original protection remains active.")
            return True  # Position still intact (original OCOs untouched)

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
            logger.critical("Executor: [EMERGENCY Same-Direction] Cancelled old OCO but failed to place new OCO. Position is now naked. Emergency market closing.")
            self.client.execute_market_close(symbol)
            return False  # Signal caller: position was emergency-closed

        return True  # Position remains protected

    # ================================================================
    # INTERNAL HELPERS
    # ================================================================

    def _get_guardian_config(self) -> dict:
        """Returns guardian (trailing stop + time-stop) config from cached global_config."""
        gc = self._global_config_raw.get("guardian", {})
        trailing = gc.get("trailing", {})
        time_stop = gc.get("time_stop", {})
        return {
            "trailing_profit_atr_level_1": float(trailing.get("trailing_profit_atr_level_1", 1.5)),
            "trailing_profit_atr_level_2": float(trailing.get("trailing_profit_atr_level_2", 2.5)),
            "trailing_profit_atr_level_3": float(trailing.get("trailing_profit_atr_level_3", 4.0)),
            "trailing_sl_offset_atr_level_2": float(trailing.get("trailing_sl_offset_atr_level_2", 0.5)),
            "trailing_sl_offset_atr_level_3": float(trailing.get("trailing_sl_offset_atr_level_3", 1.5)),
            "time_stop_multiplier": float(time_stop.get("time_stop_multiplier", 1.5)),
        }

    def _get_trade_config(self, symbol: str):
        """Returns strict trade configuration. Raises KeyError if symbol not configured."""
        from src.config.symbol_resolver import load_symbol_config, get_symbol_trade_params

        full_cfg = self._global_config_raw

        cfg = {}
        # Strict parsing: intentionally raises KeyError if keys are missing
        cfg["benchmark_symbol"] = "BTCUSDT"

        tm = full_cfg["trade_management"]
        cfg["risk_per_trade"] = tm["risk_per_trade"]
        cfg["net_qty_tolerance"] = tm["net_qty_tolerance"]

        # Verify the symbol is explicitly configured (not just getting defaults)
        sym_raw = load_symbol_config().get(symbol, {})
        if "precision_qty" not in sym_raw:
            raise KeyError(
                f"Symbol '{symbol}' is not configured in symbol_config.yaml. "
                f"Add an entry with precision_qty, precision_price, min_order_qty, and sl_slippage_buffer."
            )

        sym_cfg = get_symbol_trade_params(symbol)
        cfg["precision_qty"] = sym_cfg["precision_qty"]
        cfg["precision_price"] = sym_cfg["precision_price"]
        cfg["min_order_qty"] = sym_cfg["min_order_qty"]
        cfg["sl_slippage_buffer"] = sym_cfg["sl_slippage_buffer"]
        
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
        if self.manual_balance_usdt is not None:
            total_equity_usdt = self.manual_balance_usdt
        else:
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

    def _place_entry_order(self, symbol: str, direction: str, entry_price: float, sl_price: float) -> Optional[int]:
        """Places a LIMIT entry order. Returns order_id for Guardian tracking."""
        dynamic_qty = self._calculate_target_qty(symbol, entry_price, sl_price)
        
        logger.info(f"Executor: [DEPLOYING] Polarity: {direction} | Entry: {entry_price} | SL Trigger: {sl_price} | Qty: {dynamic_qty}")
        
        side = "BUY" if direction == "LONG" else "SELL"
        order_id = self.client.place_limit_order(
            symbol=symbol,
            side=side,
            qty=dynamic_qty,
            price=entry_price
        )
        return order_id
