import math
import os
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any
from src.infrastructure.binance.margin_client import BinanceMarginClient
from src.infrastructure.exchange.models import MarginOrder
from src.utils.logger_utils import setup_logger

logger = setup_logger(__name__)

# Sentinel returned by sync_with_opinion when the position is emergency-closed
# during a failed synthetic-OCO repair. See MarginOrderExecutor docstring for
# why synthetic OCO is used instead of native OCO (Binance SAPI limitation).
_EMERGENCY_CLOSED_SENTINEL = -1

class MarginOrderExecutor:
    """
    Orchestrates the order management lifecycle for Margin trading.
    Implements the "Conflict Decider" logic to protect Net Qty, pivot positions,
    and handle OCO/LIMIT executions.

    Architecture: Synthetic OCO via Two-Step Execution
    1. Entry via LIMIT order
    2. Protection via two separate LIMIT orders (TP + SL) treated as a synthetic OCO

    Why synthetic OCO instead of native OCO?
    This account uses Binance Spot Margin (SAPI), which does NOT expose the
    advanced OCO/OTOCO endpoints (those require the Futures or unified API).
    The approach: place a LIMIT entry, then on the NEXT Guardian pulse, place
    two independent LIMIT orders — a take-profit limit and a stop-loss limit.
    Guardian manually cross-manages them: if one fills, the other is cancelled.
    Trailing stop migration = cancel old SL → place new SL.

    RISK: Between cancelling old orders and placing new OCO legs, the position
    is NAKED. If any re-place step fails, Guardian performs an EMERGENCY market
    close to avoid running unprotected. This is the reason for the
    _EMERGENCY_CLOSED_SENTINEL sentinel value — it signals the SniperDaemon
    that the position was force-closed during a failed OCO repair.
    """
    def __init__(self, client: Optional[BinanceMarginClient] = None, manual_balance_usdt: Optional[float] = None, global_config: Optional[dict] = None):
        self.client = client or BinanceMarginClient()
        self.manual_balance_usdt = manual_balance_usdt
        # Cache global_config to avoid re-reading from disk on every guardian/trade call
        self._last_conflict_key: dict[str, str] = {}  # throttle orientation conflict logs
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
        logger.info(f"[{symbol}] syncing opinion | dir={opinion_direction} | entry={entry_price} | tp={tp_price} | sl={sl_price}")

        # [SAFETY GUARD] NEUTRAL opinions require no order action
        if opinion_direction == "NEUTRAL":
            logger.info(f"[{symbol}] opinion NEUTRAL — no order placement")
            return None

        # [SAFETY GUARD] Explicit Whitelist Check
        if not self._is_symbol_whitelisted(symbol):
            logger.warning(f"[{symbol}] symbol not in config — aborting")
            return None

        pos = self.client.get_symbol_position(symbol)
        active_orders = self.client.get_active_orders(symbol)

        net_qty = pos.net_qty if pos else 0.0

        # Load logic limits with strict fail-fast error handling
        try:
            cfg = self._get_trade_config(symbol)
            tolerance = cfg["net_qty_tolerance"]
        except Exception as e:
            logger.error(f"[{symbol}] config error — aborting | error={e}")
            return None

        # Determine Current Direction
        current_direction = "FLAT"
        if net_qty > tolerance:
            current_direction = "LONG"
        elif net_qty < -tolerance:
            current_direction = "SHORT"

        logger.info(f"[{symbol}] current state | dir={current_direction} | net_qty={net_qty}")

        # Scenario C: FLAT
        if current_direction == "FLAT":
            if active_orders:
                logger.info(f"[{symbol}] position flat — cleaning orders")
                if not self.client.cancel_all_symbol_orders(symbol):
                    logger.error(f"[{symbol}] failed to clear stale orders — aborting")
                    return None

            logger.info(f"[{symbol}] placing LIMIT entry | dir={opinion_direction}")
            return self._place_entry_order(symbol, opinion_direction, entry_price, sl_price)

        # Scenario A: PIVOT (Opposite Direction)
        if current_direction != opinion_direction:
            logger.warning(f"[{symbol}] pivot detected | current={current_direction} | new={opinion_direction}")

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
                    f"[{symbol}] pivot-preserve | {current_direction} SL at {original_sl_trigger}"
                )

                # 2. Determine if the flip point has already been overshot
                current_price = self.client.get_ticker_price(symbol)
                if current_price is None or current_price <= 0:
                    logger.error(f"[{symbol}] pivot-preserve failed — no ticker price")
                    return None
                is_overshot = (
                    (current_direction == "SHORT" and current_price <= entry_price) or
                    (current_direction == "LONG" and current_price >= entry_price)
                )

                if is_overshot:
                    logger.warning(
                        f"[{symbol}] pivot-overshot | price={current_price} past entry={entry_price} | closing {current_direction}"
                    )
                    if not self.client.cancel_all_symbol_orders(symbol):
                        logger.error(f"[{symbol}] pivot-overshot — failed to cancel orders")
                        return None
                    if not self.client.execute_market_close(symbol):
                        logger.error(f"[{symbol}] pivot-overshot — failed to market close")
                        return None

                    # Proceed to place new entry
                    logger.info(f"[{symbol}] pivot-overshot — placing LIMIT entry | dir={opinion_direction} | entry={entry_price}")
                    return self._place_entry_order(symbol, opinion_direction, entry_price, sl_price)

                # 3. Standard Case: Re-hang OCO with TP aligned to new entry
                pivot_tp = entry_price
                logger.info(f"[{symbol}] pivot-preserve | protecting {current_direction} | tp={pivot_tp}")

                # Format to precision
                p_price = cfg["precision_price"]
                pivot_tp = round(pivot_tp, p_price)

                # 4. Re-hang OCO for the existing opposing position
                #    (original SL trigger + pivot TP)
                #    Place new OCO BEFORE cancelling old — avoids naked window.
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
                        f"[{symbol}] Guardian EMERGENCY close — OCO failure"
                    )
                    if not self.client.execute_market_close(symbol):
                        logger.error(f"[{symbol}] pivot-preserve — emergency market close failed")
                        return None
                    logger.info(f"[{symbol}] pivot-preserve — emergency close done, entering {opinion_direction}")
                    return self._place_entry_order(symbol, opinion_direction, entry_price, sl_price)

                # New OCO is live — now safe to clean up old orders
                if not self.client.cancel_all_symbol_orders(symbol):
                    logger.warning(f"[{symbol}] pivot-preserve — failed to cancel old orders (new OCO already active)")

                # 4. Place the new opinion's LIMIT entry alongside the preserved position
                logger.info(f"[{symbol}] pivot-preserve — placing entry | dir={opinion_direction} | entry={entry_price}")
                return self._place_entry_order(symbol, opinion_direction, entry_price, sl_price)

            else:
                # Case A-1: No stop loss → opposing position is unprotected → force close
                logger.warning(
                    f"[{symbol}] pivot-forceclose | {current_direction} unprotected — closing"
                )
                if not self.client.cancel_all_symbol_orders(symbol):
                    logger.error(f"[{symbol}] pivot — failed to cancel orders")
                    return None

                if not self.client.execute_market_close(symbol):
                    logger.error(f"[{symbol}] pivot — failed to market close")
                    return None

                logger.info(f"[{symbol}] pivot-forceclose — placing LIMIT entry | dir={opinion_direction}")
                return self._place_entry_order(symbol, opinion_direction, entry_price, sl_price)

        # Scenario B: SAME DIRECTION (Optimization & Net Qty Protection)
        logger.info(f"[{symbol}] same direction — optimizing protection")
        position_intact, state_update = self._optimize_same_direction(
            symbol, current_direction, net_qty, active_orders, tp_price, sl_price
        )
        if not position_intact:
            # Emergency close was triggered — return sentinel to signal caller that trade_state should be cleared
            logger.critical(f"[{symbol}] Guardian CRITICAL — failed OCO, emergency closing")
            return _EMERGENCY_CLOSED_SENTINEL
        # Return state_update so _attempt_trade_execution can merge into trade_state
        return state_update

    # ================================================================
    # GUARDIAN LOGIC: Called every Sniper pulse to protect positions
    # ================================================================

    def guardian_check(self, symbol: str, trade_state: Dict[str, Any],
                        atr_macro: Optional[float] = None,
                        current_level: int = 0) -> tuple:
        """
        Position Guardian: Runs every Sniper pulse to ensure positions are protected.

        Responsibilities:
        1. If PENDING entry order → check timeout → cancel if expired
        2. If FILLED position with NO OCO → place OCO or emergency close
        3. If position already protected → multi-level partial TP + dynamic trailing

        Args:
            symbol: Trading pair identifier.
            trade_state: Current in-memory trade state dictionary.
            atr_macro: Current ATR value for trailing stop calculations.
            current_level: Partial TP level known to daemon memory.

        Returns (updated_trade_state: dict, level: int|None).
        level is the current partial TP level for the daemon to track.
        """

        # --- STEP 0: Heartbeat Reporting (Always runs if called) ---
        pos = self.client.get_symbol_position(symbol)
        net_qty = pos.net_qty if pos else 0.0
        active_orders = self.client.get_active_orders(symbol)

        try:
            cfg = self._get_trade_config(symbol)
            tolerance = cfg["net_qty_tolerance"]
        except Exception as e:
            logger.error(f"[{symbol}] guardian config error | error={e}")
            return trade_state, None

        has_position = abs(net_qty) > tolerance
        logger.debug(f"[{symbol}] guardian pulse | net_qty={net_qty} | has_position={has_position} | active_orders={len(active_orders)}")

        # --- STEP 1: Intent Check (Early exit if robot has no skin in the game) ---
        if not trade_state or not trade_state.get("direction"):
            # Restart gap: if position + OCO exist on exchange, reconstruct minimal trade_state
            if has_position:
                has_sl = any(
                    o.type in ("STOP_LOSS", "STOP_LOSS_LIMIT") and o.stop_price > 0
                    for o in active_orders
                )
                if has_sl:
                    reconstructed = {"direction": "LONG" if net_qty > tolerance else "SHORT"}
                    for o in active_orders:
                        if o.type in ("LIMIT", "LIMIT_MAKER") and o.price > 0:
                            reconstructed["tp_price"] = o.price
                        if o.type in ("STOP_LOSS", "STOP_LOSS_LIMIT") and o.stop_price > 0:
                            reconstructed["sl_price"] = o.stop_price
                    logger.info(f"[{symbol}] trade_state reconstructed from exchange | dir={reconstructed['direction']}")
                    trade_state = reconstructed
                else:
                    return trade_state, None
            else:
                return trade_state, None

        direction = trade_state["direction"]

        # Determine if OCO protection exists
        exit_side = "SELL" if direction == "LONG" else "BUY"
        has_oco = any(
            o.side == exit_side and o.type in ["STOP_LOSS", "STOP_LOSS_LIMIT"]
            for o in active_orders
        )

        # --- STEP 0: Refresh avg_entry from exchange (cached, only calls API on qty change) ---
        avg_entry = self.client.get_avg_entry_price(symbol, net_qty)

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
                        logger.warning(f"[{symbol}] entry order expired | id={entry_order_id} | elapsed={elapsed_hours:.1f}h > {timeout_hours}h")
                        self.client.cancel_order(symbol, entry_order_id)
                        return {}, None  # Clear trade state
                    else:
                        logger.info(f"[{symbol}] entry order pending | id={entry_order_id} | elapsed={elapsed_hours:.1f}h / {timeout_hours}h")
            else:
                # Position was entered and then closed (net≈0, no entry order).
                # Possible causes: Pivot-Preserve flip, SL partial fill that left
                # a residual that was subsequently closed, or bidirectional unwind.
                # Cancel any stray orders and clear stale trade state.
                if trade_state.get("entry_filled_at"):
                    logger.info(f"[{symbol}] position flat — cleaning orders")
                self.client.cancel_all_symbol_orders(symbol)
                return {}, None
            return trade_state, None

        # --- Case 2: Has position -> Direction Sanity Check ---
        # Safeguard: Ensure reality's NetQty aligns with robot's Intent
        is_long_pos = net_qty > tolerance
        is_short_pos = net_qty < -tolerance
        intent = trade_state["direction"]

        if (intent == "LONG" and not is_long_pos) or (intent == "SHORT" and not is_short_pos):
            conflict_key = f"{intent}_{net_qty}"
            if self._last_conflict_key.get(symbol) != conflict_key:
                logger.warning(f"[{symbol}] orientation conflict | intent={intent} | net_qty={net_qty} — cancelling all orders")
                self._last_conflict_key[symbol] = conflict_key
            # Cancel wrong-side orders — next pulse Case 3 will emergency-close
            self.client.cancel_all_symbol_orders(symbol)
            return trade_state, None

        # --- Case 3: Has position and direction matches -> Protect Position ---
        if not has_oco:
            tp = trade_state.get("tp_price")
            sl = trade_state.get("sl_price")

            if not tp or not sl:
                logger.critical(f"[{symbol}] Guardian CRITICAL — position has no TP/SL, emergency closing")
                self.client.cancel_all_symbol_orders(symbol)
                if not self.client.execute_market_close(symbol):
                    logger.critical(f"[{symbol}] emergency close FAILED — keeping trade state for retry")
                    return trade_state, None
                return {}, None

            # Check if price has already breached SL
            current_price = self.client.get_ticker_price(symbol)
            if not current_price or current_price <= 0:
                logger.error(f"[{symbol}] ticker unavailable (price={current_price}) — deferring SL breach check")
                return trade_state, None

            sl_breached = (
                (direction == "LONG" and current_price <= sl) or
                (direction == "SHORT" and current_price >= sl)
            )

            if sl_breached:
                logger.critical(f"[{symbol}] Guardian EMERGENCY close — price breached SL | price={current_price} | sl={sl}")
                self.client.cancel_all_symbol_orders(symbol)
                if not self.client.execute_market_close(symbol):
                    logger.critical(f"[{symbol}] emergency close FAILED — keeping trade state for retry")
                    return trade_state, None
                return {}, None  # Clear trade state

            # Normal case: place OCO protection
            logger.info(f"[{symbol}] Guardian activated | dir={direction} | qty={net_qty}")

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
                logger.info(f"[{symbol}] Guardian OCO placed | tp={tp} | sl={sl}")
                # Update state: remove entry tracking, keep direction/prices
                trade_state.pop("entry_order_id", None)
                trade_state.pop("entry_placed_at", None)
                # Record fill time for time-based stop tracking
                if not trade_state.get("entry_filled_at"):
                    trade_state["entry_filled_at"] = datetime.now(timezone.utc).isoformat()
                return trade_state, None  # Position just protected, defer trailing to next pulse
            else:
                logger.critical(f"[{symbol}] Guardian CRITICAL — failed to place OCO, emergency closing")
                self.client.cancel_all_symbol_orders(symbol)
                if not self.client.execute_market_close(symbol):
                    logger.critical(f"[{symbol}] emergency close FAILED — keeping trade state for retry")
                    return trade_state, None
                return {}, None

        # --- Case 4: Position is already protected → Partial TP + Dynamic Trailing ---
        logger.debug(f"[{symbol}] position protected | dir={direction} | net_qty={net_qty}")

        # OCO qty sanity: re-align if position changed since OCO was placed
        oco_sl_qty = sum(
            o.orig_qty for o in active_orders
            if o.side == exit_side and o.type in ("STOP_LOSS", "STOP_LOSS_LIMIT")
        )
        if abs(oco_sl_qty - abs(net_qty)) > tolerance:
            logger.info(
                f"[{symbol}] OCO qty mismatch | oco_qty={oco_sl_qty} | position={abs(net_qty)} — re-aligning"
            )
            oco_tp = trade_state.get("tp_price", 0)
            oco_sl = trade_state.get("sl_price", 0)
            for o in active_orders:
                if o.side != exit_side:
                    continue
                if o.type in ("LIMIT", "LIMIT_MAKER") and o.price > 0:
                    oco_tp = o.price
                elif o.type in ("STOP_LOSS", "STOP_LOSS_LIMIT") and o.stop_price > 0:
                    oco_sl = o.stop_price
            if oco_tp > 0 and oco_sl > 0:
                self.client.cancel_all_symbol_orders(symbol)
                buffer = cfg.get("sl_slippage_buffer", 0.0)
                buffered_sl = oco_sl + (buffer if direction == "SHORT" else -buffer)
                success = self.client.place_oco_order(
                    symbol=symbol,
                    side=exit_side,
                    qty=abs(net_qty),
                    price=oco_tp,
                    stop_price=oco_sl,
                    stop_limit_price=buffered_sl
                )
                if success:
                    logger.info(f"[{symbol}] OCO re-aligned | qty={abs(net_qty)} | tp={oco_tp} | sl={oco_sl}")
                    trade_state["tp_price"] = oco_tp
                    trade_state["sl_price"] = oco_sl
                else:
                    logger.critical(f"[{symbol}] OCO re-align failed, emergency closing")
                    self.client.cancel_all_symbol_orders(symbol)
                    if not self.client.execute_market_close(symbol):
                        logger.critical(f"[{symbol}] emergency close FAILED — keeping trade state for retry")
                        return trade_state, None
                    return {}, None
            else:
                logger.critical(f"[{symbol}] OCO qty mismatch but no TP/SL available | tp={oco_tp} | sl={oco_sl}")

        new_level = current_level  # unchanged unless partial TP advances it

        if atr_macro is not None and not math.isnan(atr_macro) and atr_macro > 0:
            # Extract live SL/TP from active orders (source of truth)
            current_sl = trade_state.get("sl_price", 0)
            current_tp = trade_state.get("tp_price", 0)
            for o in active_orders:
                if o.side != exit_side:
                    continue
                if o.type in ("LIMIT", "LIMIT_MAKER") and o.price > 0:
                    current_tp = o.price
                elif o.type in ("STOP_LOSS", "STOP_LOSS_LIMIT") and o.stop_price > 0:
                    current_sl = o.stop_price

            current_price = self.client.get_ticker_price(symbol)
            if current_price and current_price > 0:
                # Load multi-level config
                gc = self._get_guardian_config()
                levels = gc["levels"]

                # Step 2: Multi-level partial TP (sequential, loop-driven)
                intact, tp_update = self._try_partial_tp(
                    symbol, direction, net_qty, avg_entry,
                    current_sl, current_tp, current_price, cfg, atr_macro,
                    levels, current_level
                )
                if not intact:
                    return {}, None  # Emergency-closed

                if tp_update is not None:
                    if not tp_update:
                        # Position fully closed by partial TP — clear trade state
                        return {}, None
                    # Merge sl/tp into trade_state (not partial_tp_level — that's daemon memory)
                    for key in ("sl_price", "tp_price"):
                        if key in tp_update:
                            trade_state[key] = tp_update[key]
                    current_sl = trade_state.get("sl_price", current_sl)
                    current_tp = trade_state.get("tp_price", current_tp)
                    if "partial_tp_level" in tp_update:
                        new_level = tp_update["partial_tp_level"]

                # Step 3: Dynamic trailing — uses the LAST triggered level's
                # distance. new_level is "next to check", so active = new_level - 1.
                # When no TP yet (new_level=0): no trailing (SL is AI's original).
                active_sl_distance = 0.0
                active_idx = new_level - 1
                if 0 <= active_idx < len(levels):
                    active_sl_distance = levels[active_idx]["sl_distance_atr"]

                if active_sl_distance > 0:
                    intact, new_sl = self._migrate_dynamic_sl(
                        symbol, direction, current_sl, current_tp, current_price,
                        cfg, active_sl_distance, atr_macro
                    )
                    if not intact:
                        return {}, None  # Emergency-closed

                    if new_sl is not None:
                        trade_state["sl_price"] = new_sl

        return trade_state, new_level

    # ================================================================
    # SAME-DIRECTION OPTIMIZATION
    # ================================================================

    def _optimize_same_direction(self, symbol: str, direction: str, net_qty: float, active_orders: List[MarginOrder], new_tp: float, new_sl: float) -> tuple:
        """
        Calculates the best TP/SL comparing existing manual/script orders vs new opinion.
        Protects the ENTIRE net_qty.

        Returns:
            (position_intact: bool, state_update: dict|None)
            state_update carries {tp_price, sl_price} for the caller to merge into trade_state.
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
            logger.info(f"[{symbol}] existing TPs | tps={current_tps}")
        if current_sls:
            logger.info(f"[{symbol}] existing SLs | sls={current_sls}")

        best_tp = new_tp
        best_sl = new_sl

        # TP: greedy mode — keep widest TP (more reward)
        # SL: risk mode — keep tightest SL (less loss)
        if direction == "LONG":
            if current_tps:
                best_tp = max(max(current_tps), new_tp)  # Higher TP = wider
            if current_sls:
                best_sl = max(max(current_sls), new_sl)  # Higher SL = tighter
        else:  # SHORT
            if current_tps:
                best_tp = min(min(current_tps), new_tp)  # Lower TP = wider
            if current_sls:
                best_sl = min(min(current_sls), new_sl)  # Lower SL = tighter

        logger.info(f"[{symbol}] final targets | tp={best_tp} (opinion={new_tp}) | sl={best_sl} (opinion={new_sl})")

        # Clean slate the orders to apply the unified OCO over the entire Net Qty
        logger.info(f"[{symbol}] cancelling orders to wrap net_qty={net_qty} with OCO")
        if not self.client.cancel_all_symbol_orders(symbol):
            logger.error(f"[{symbol}] optimize — failed to cancel OCOs, original protection remains")
            return True, {"tp_price": best_tp, "sl_price": best_sl}

        # Re-verify position after cancel — a fill during the cancel window can change qty
        trade_cfg = self._get_trade_config(symbol)
        pos = self.client.get_symbol_position(symbol)
        live_qty = abs(pos.net_qty) if pos else 0.0
        if live_qty <= 0:
            logger.warning(f"[{symbol}] optimize — position vanished after cancel")
            return True, None
        if abs(live_qty - abs(net_qty)) > trade_cfg.get("net_qty_tolerance", 1e-8):
            logger.warning(f"[{symbol}] optimize — qty changed after cancel | {net_qty} → {live_qty}")

        # Calculate buffered SL Limit (Slippage protection)
        buffer = trade_cfg.get("sl_slippage_buffer", 0.0)
        # LONG SL (Sell): Limit < Trigger | SHORT SL (Buy): Limit > Trigger
        buffered_sl = best_sl + (buffer if direction == "SHORT" else -buffer)

        # Place the OCO for the full position
        success = self.client.place_oco_order(
            symbol=symbol,
            side=exit_side,
            qty=live_qty,
            price=best_tp,
            stop_price=best_sl,
            stop_limit_price=buffered_sl
        )
        if not success:
            logger.critical(f"[{symbol}] Guardian CRITICAL — cancelled OCO, failed to place new, emergency closing")
            if not self.client.execute_market_close(symbol):
                logger.critical(f"[{symbol}] emergency close FAILED — keeping trade state for retry")
                return True, None  # Signal caller: position still open
            return False, None  # Signal caller: position was emergency-closed

        return True, {"tp_price": best_tp, "sl_price": best_sl}

    # ================================================================
    # INTERNAL HELPERS
    # ================================================================

    def _get_guardian_config(self) -> dict:
        """Returns guardian partial TP levels config.

        Dynamic trailing distance is per-level (sl_distance_atr field);
        before any partial TP fires, no trailing occurs (SL = AI's original).
        """
        gc = self._global_config_raw.get("guardian", {})
        partial_tp = gc.get("partial_tp", {})

        levels = []
        for lv in partial_tp.get("levels", []):
            levels.append({
                "atr_threshold": float(lv.get("atr_threshold", 1.5)),
                "tp_ratio": float(lv.get("tp_ratio", 0.5)),
                "sl_distance_atr": float(lv.get("sl_distance_atr", 0.0)),
            })

        return {"levels": levels}

    def _get_trade_config(self, symbol: str):
        """Returns strict trade configuration. Raises KeyError if symbol not configured."""
        from src.config.symbol_resolver import load_symbol_config, get_symbol_trade_params

        full_cfg = self._global_config_raw

        cfg = {}
        # Strict parsing: intentionally raises KeyError if keys are missing
        from src.utils.symbol_utils import get_quote_currency
        cfg["benchmark_symbol"] = "BTC" + get_quote_currency()

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

    def find_level_and_sync_sl(self, symbol: str, trade_state: dict,
                                atr_macro: Optional[float] = None) -> int:
        """
        Called by daemon when level memory is uninitialized (startup, qty change).

        Determines the NEXT level to check from exchange state:
          - If SL outside entry → L1 hasn't fired → return 0 (check L1 next)
          - If SL at/beyond entry → scan |price-entry| → return the first
            un-triggered level index as next-to-check (1=L2, 2=L3, 3=done).

        Syncs SL to match the found level's trailing configuration.
        Does NOT execute any TP closes — that happens on the next pulse.
        """
        direction = trade_state.get("direction")
        if not direction:
            return 0

        pos = self.client.get_symbol_position(symbol)
        net_qty = pos.net_qty if pos else 0.0
        active_orders = self.client.get_active_orders(symbol)
        avg_entry = self.client.get_avg_entry_price(symbol, net_qty)

        if avg_entry <= 0:
            return 0

        exit_side = "SELL" if direction == "LONG" else "BUY"
        current_sl = trade_state.get("sl_price", 0)
        current_tp = trade_state.get("tp_price", 0)
        for o in active_orders:
            if o.side != exit_side:
                continue
            if o.type in ("LIMIT", "LIMIT_MAKER") and o.price > 0:
                current_tp = o.price
            elif o.type in ("STOP_LOSS", "STOP_LOSS_LIMIT") and o.stop_price > 0:
                current_sl = o.stop_price

        if current_sl <= 0 or current_tp <= 0:
            return 0

        current_price = self.client.get_ticker_price(symbol)
        if not current_price or current_price <= 0:
            return 0

        cfg = self._get_trade_config(symbol)
        gc = self._get_guardian_config()
        levels = gc["levels"]
        if not levels:
            return 0

        if atr_macro is None or math.isnan(atr_macro) or atr_macro <= 0:
            return 0

        deviation = abs(current_price - avg_entry)

        # Step 1: Has L1 fired? (SL at/beyond entry = breakeven placed)
        l1_fired = ((direction == "LONG" and current_sl >= avg_entry) or
                     (direction == "SHORT" and current_sl <= avg_entry))

        if not l1_fired:
            logger.info(f"[{symbol}] find_level: L1 not yet fired | "
                        f"sl={current_sl:.2f} entry={avg_entry:.2f}")
            return 0  # next to check = L1

        # Step 2: Scan to find highest triggered level
        # next_level = first un-triggered level index (1=L2, 2=L3, 3=done)
        next_level = 1  # L1 has fired, at least L2 is next
        for i in range(1, len(levels)):
            if deviation >= levels[i]["atr_threshold"] * atr_macro:
                next_level = i + 1
            else:
                break

        # Step 3: Sync SL to match the last triggered level's trailing distance
        active_idx = next_level - 1
        target_distance = levels[active_idx]["sl_distance_atr"]
        if target_distance > 0:
            if direction == "LONG":
                target_sl = max(avg_entry, current_price - target_distance * atr_macro)
            else:
                target_sl = min(avg_entry, current_price + target_distance * atr_macro)
        else:
            target_sl = avg_entry

        p_price = cfg["precision_price"]
        target_sl = round(target_sl, p_price)

        if abs(target_sl - current_sl) > 10 ** (-p_price):
            logger.info(f"[{symbol}] find_level: syncing SL | {current_sl} -> {target_sl} | "
                        f"level={active_idx} distance={target_distance}")
            if not self.client.cancel_all_symbol_orders(symbol):
                logger.error(f"[{symbol}] find_level: cancel failed, SL not synced")
                return next_level

            pos = self.client.get_symbol_position(symbol)
            if pos and abs(pos.net_qty) > 0:
                buffer = cfg.get("sl_slippage_buffer", 0.0)
                buffered_sl = target_sl + (buffer if direction == "SHORT" else -buffer)
                if not self.client.place_oco_order(
                    symbol=symbol, side=exit_side,
                    qty=abs(pos.net_qty), price=current_tp,
                    stop_price=target_sl, stop_limit_price=buffered_sl
                ):
                    logger.critical(f"[{symbol}] find_level: OCO re-place failed, emergency closing")
                    if not self.client.execute_market_close(symbol):
                        logger.critical(f"[{symbol}] find_level: emergency close FAILED")
        else:
            logger.info(f"[{symbol}] find_level: SL correct | "
                        f"next_level={next_level} sl={current_sl:.2f}")

        return next_level

    def _try_partial_tp(self, symbol: str, direction: str, net_qty: float,
                        avg_entry: float, current_sl: float,
                        current_tp: float, current_price: float,
                        cfg: dict, atr_macro: float, levels: list,
                        start_level: int) -> tuple:
        """Step 2: Multi-level partial take-profit.

        Loops through configured levels sequentially (start_level → end).
        Each level triggers when |price - entry| >= atr_threshold * ATR.
        Multiple levels CAN fire in a single pulse if price has moved far enough.

        Returns (position_intact: bool, trade_state_update: dict|None).
        trade_state_update carries sl_price, tp_price, partial_tp_level.
        """
        if avg_entry <= 0 or current_sl <= 0 or atr_macro <= 0:
            return True, None

        if not levels:
            return True, None

        deviation = abs(current_price - avg_entry)
        state_update = {}
        live_net_qty = net_qty

        for i in range(start_level, len(levels)):
            level = levels[i]

            threshold = level["atr_threshold"] * atr_macro

            if deviation < threshold:
                break  # Sequential: stop at first unmet threshold

            ratio = level["tp_ratio"]
            tp_qty = abs(live_net_qty) * ratio
            p_qty = cfg["precision_qty"]
            tp_qty = max(round(tp_qty, p_qty), cfg["min_order_qty"])

            logger.info(
                f"[{symbol}] partial TP L{i+1} triggered | "
                f"deviation={deviation:.2f} | tp_qty={tp_qty}"
            )

            # Step A: Cancel all existing orders
            if not self.client.cancel_all_symbol_orders(symbol):
                logger.error(f"[{symbol}] partial TP L{i+1} — cancel failed, aborting")
                return True, state_update if state_update else None

            # Step B: Market-sell partial qty
            close_side = "SELL" if direction == "LONG" else "BUY"
            close_success = self.client.execute_partial_market_close(
                symbol=symbol,
                side=close_side,
                qty=tp_qty
            )
            if not close_success:
                logger.critical(
                    f"[{symbol}] partial TP L{i+1} — market close failed, emergency closing all"
                )
                if not self.client.execute_market_close(symbol):
                    logger.critical(f"[{symbol}] emergency close FAILED — keeping trade state")
                    return True, None
                return False, None

            # Step C: Re-verify remaining position
            pos = self.client.get_symbol_position(symbol)
            live_qty = abs(pos.net_qty) if pos else 0.0
            if live_qty <= 0:
                logger.info(f"[{symbol}] partial TP L{i+1} — position fully closed")
                return True, {}  # Clear trade state

            sign = 1 if direction == "LONG" else -1
            live_net_qty = live_qty * sign

            # Step D: Place new OCO for remaining qty (SL = entry, TP = original TP)
            exit_side = "SELL" if direction == "LONG" else "BUY"
            buffer = cfg.get("sl_slippage_buffer", 0.0)
            buffered_sl = avg_entry + (buffer if direction == "SHORT" else -buffer)

            oco_success = self.client.place_oco_order(
                symbol=symbol,
                side=exit_side,
                qty=live_qty,
                price=current_tp,
                stop_price=avg_entry,
                stop_limit_price=buffered_sl
            )
            if not oco_success:
                logger.critical(
                    f"[{symbol}] partial TP L{i+1} — OCO re-place failed, emergency closing"
                )
                if not self.client.execute_market_close(symbol):
                    logger.critical(f"[{symbol}] emergency close FAILED — keeping trade state")
                    return True, None
                return False, None

            logger.info(
                f"[{symbol}] partial TP L{i+1} complete | "
                f"remaining={live_qty} | sl={avg_entry}"
            )
            state_update["sl_price"] = avg_entry
            state_update["tp_price"] = current_tp
            state_update["partial_tp_level"] = i + 1  # next level to check

        return True, state_update if state_update else None

    def _migrate_dynamic_sl(self, symbol: str, direction: str, current_sl: float,
                             current_tp: float, current_price: float,
                             cfg: dict, sl_distance_atr: float,
                             atr_macro: float) -> tuple:
        """Step 3: Dynamic trailing SL — distance-based, SL itself as anchor.

        LONG:  new_sl = max(current_sl, price - N * ATR)
        SHORT: new_sl = min(current_sl, price + N * ATR)

        sl_distance_atr is passed explicitly from the active partial-TP level.
        This call is a no-op when distance <= 0.

        Returns (position_intact: bool, new_sl_or_None: float|None).
        None means no migration needed. position_intact=False means emergency-closed.
        """
        if current_sl <= 0 or atr_macro <= 0 or sl_distance_atr <= 0:
            return True, None

        distance = sl_distance_atr * atr_macro

        if direction == "LONG":
            new_sl = max(current_sl, current_price - distance)
        else:
            new_sl = min(current_sl, current_price + distance)

        # Round toward safety
        p_price = cfg["precision_price"]
        if direction == "LONG":
            new_sl = round(new_sl, p_price)  # floor-ish via round
        else:
            new_sl = round(new_sl, p_price)

        if abs(new_sl - current_sl) < 1e-8:
            return True, None  # No change

        logger.info(
            f"[{symbol}] dynamic SL migrating | {current_sl:.2f} -> {new_sl:.2f} | "
            f"distance={distance:.2f}"
        )

        # Cancel -> re-place
        if not self.client.cancel_all_symbol_orders(symbol):
            logger.error(f"[{symbol}] dynamic SL -- cancel failed, keeping existing")
            return True, None

        pos = self.client.get_symbol_position(symbol)
        if not pos or abs(pos.net_qty) <= 0:
            logger.critical(f"[{symbol}] dynamic SL -- position vanished, emergency closing")
            if not self.client.execute_market_close(symbol):
                logger.critical(f"[{symbol}] emergency close FAILED — keeping trade state")
                return True, None
            return False, None

        exit_side = "SELL" if direction == "LONG" else "BUY"
        buffer = cfg.get("sl_slippage_buffer", 0.0)
        buffered_sl = new_sl + (buffer if direction == "SHORT" else -buffer)

        success = self.client.place_oco_order(
            symbol=symbol,
            side=exit_side,
            qty=abs(pos.net_qty),
            price=current_tp,
            stop_price=new_sl,
            stop_limit_price=buffered_sl
        )
        if not success:
            logger.critical(f"[{symbol}] dynamic SL -- OCO re-place failed, emergency closing")
            if not self.client.execute_market_close(symbol):
                logger.critical(f"[{symbol}] emergency close FAILED — keeping trade state for retry")
                return True, None
            return False, None

        return True, new_sl

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
        if price_delta < 1e-12:
            logger.error(f"[{symbol}] invalid SL delta=0 | fallback qty={min_qty}")
            return min_qty

        # 5. Determine Quantity
        target_qty = max_loss_usdt / price_delta
        target_qty = round(target_qty, p_qty)

        # Ensure it meets minimum
        target_qty = max(target_qty, min_qty)

        logger.info(f"[{symbol}] risk check | equity=${total_equity_usdt:.2f} | risk=%.2f%% | max_loss=${max_loss_usdt:.2f}" % (risk_pct * 100))
        logger.info(f"[{symbol}] position sizing | entry={entry_price} | sl={sl_price} | delta=${price_delta:.2f} | qty={target_qty}")
        return target_qty

    def _place_entry_order(self, symbol: str, direction: str, entry_price: float, sl_price: float) -> Optional[int]:
        """Places a LIMIT entry order. Returns order_id for Guardian tracking."""
        dynamic_qty = self._calculate_target_qty(symbol, entry_price, sl_price)

        logger.info(f"[{symbol}] deploying | dir={direction} | entry={entry_price} | sl={sl_price} | qty={dynamic_qty}")

        side = "BUY" if direction == "LONG" else "SELL"
        order_id = self.client.place_limit_order(
            symbol=symbol,
            side=side,
            qty=dynamic_qty,
            price=entry_price
        )
        return order_id
