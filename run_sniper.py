#!/usr/bin/env python3
import os
import sys
import time
import argparse
import logging
from datetime import datetime, timezone
from dotenv import load_dotenv

# Setup absolute project paths
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# Load environment
load_dotenv()

from src.infrastructure.binance.client import BinanceFuturesClient
from src.sniper.scout import SniperScout
from src.sniper.trigger import SniperTrigger
from run_session import SessionEngine
from src.utils.logger_utils import setup_logger
from src.utils.pipeline_utils import load_global_config

logger = setup_logger("SniperDaemon")

class SniperDaemon:
    """
    The Intelligence-Led Pulse Micro-Orchestrator.
    
    Monitors market topography at high-frequency (Lightweight) and 
    activates the 'Binary Star' reasoning engine (Heavyweight) 
    only when a Wake-Up Matrix condition is met.
    
    When --trade is enabled, also acts as the Position Guardian,
    protecting open positions with OCO orders every pulse cycle.
    """
    
    def __init__(self, args):
        from src.utils.symbol_utils import resolve_symbols

        self.args = args
        self.global_cfg = load_global_config()

        # Parse CSV symbol list (e.g., "BTC,ETH,XAUT" → ["BTCUSDT", "ETHUSDT", "XAUTUSDT"])
        raw_symbols = getattr(args, 'symbol', '') or ''
        self.symbols = resolve_symbols(raw_symbols)

        # 0. Global Forensic Logging Initialization
        from src.utils.path_utils import resolve_project_root
        session_log_path = os.path.join(resolve_project_root(), args.path, "sniper.log")
        setup_logger("", log_level=logging.INFO, log_file=session_log_path,
                     max_bytes=10 * 1024 * 1024, backup_count=5)

        # Shared Infrastructure: Centralized client (shared across all symbols)
        self.futures_client = BinanceFuturesClient()

        # 1. Initialize Lightweight Sniper Tools (one per symbol)
        self.scouts: dict[str, SniperScout] = {}
        self.triggers: dict[str, SniperTrigger] = {}
        for sym in self.symbols:
            self.scouts[sym] = SniperScout(sym, exchange_client=self.futures_client)
            self.triggers[sym] = SniperTrigger(
                strategy_cfg=self.scouts[sym].strategy_cfg,
                global_cfg=self.scouts[sym].global_cfg,
            )
            logger.info(f"SniperDaemon [{sym}]: Trigger Cooldown is active at {self.triggers[sym].cooldown_minutes}m.")

        # 2. Initialize Heavyweight Session Engines (one per symbol, always)
        self.session_engines: dict = {}
        for sym in self.symbols:
            self.session_engines[sym] = SessionEngine(sym, args.path, args=args,
                                                      exchange_client=self.futures_client)

        # 3. Initialize Trade Execution (shared executor is symbol-aware)
        self.trade_enabled = bool(args.trade)
        self.manual_balance = args.trade if isinstance(args.trade, float) else None
        self.executor = None
        self.trade_states: dict[str, dict] = {}
        if self.trade_enabled:
            from src.infrastructure.binance.margin_client import BinanceMarginClient
            from src.agent.order_executor import MarginOrderExecutor, EMERGENCY_CLOSED_SENTINEL
            margin_client = BinanceMarginClient()
            self.executor = MarginOrderExecutor(client=margin_client, manual_balance_usdt=self.manual_balance)
            if self.manual_balance:
                logger.info(f"SniperDaemon: Using manual balance ${self.manual_balance:.2f} USDT for position sizing.")
            logger.info(f"SniperDaemon: Trade execution ENABLED for {self.symbols}. Guardian will monitor every pulse.")

        # Per-symbol previous metrics for inter-pulse comparison
        self.prev_metrics: dict[str, dict | None] = {sym: None for sym in self.symbols}

        # Sniper Quiet-Monitoring Protocol
        logging.getLogger("src.infrastructure.binance.client").setLevel(logging.CRITICAL)

    def run_forever(self):
        pulse_mins = self.global_cfg['sniper']['heartbeat']['pulse_interval_minutes']
        if pulse_mins <= 0:
            raise ValueError(f"pulse_interval_minutes must be > 0, got {pulse_mins}")
        sym_list = ", ".join(self.symbols)
        logger.info(f"--- Sniper Monitoring Started: {sym_list} (Pulse: {pulse_mins}m) ---")

        while True:
            try:
                # ── 0. GUARDIAN: protect every symbol with skin in the game ──
                if self.trade_enabled and self.executor:
                    for sym in self.symbols:
                        self._guardian_check(sym)

                # ── 0.5 HEARTBEAT: write before any blocking AI sessions ──
                # Ensures the dashboard always has fresh position data, even if
                # sessions run long or the daemon crashes mid-pulse.
                if self.trade_enabled:
                    self._write_guardian_status()

                # ── 1. SCOUT: lightweight data collection per symbol (sequential) ──
                metrics: dict[str, dict] = {}
                for sym in self.symbols:
                    result = self.scouts[sym].scout()
                    if result.metrics:
                        metrics[sym] = result.metrics

                if not metrics:
                    logger.warning("SniperDaemon: All scouts returned empty metrics. Skipping pulse.")
                    time.sleep(60)
                    continue

                # ── 2. TRIGGER: independent evaluation per symbol ──
                triggered: list[tuple[str, str, str]] = []
                now_str = datetime.now().strftime("%H:%M:%S")

                for sym in self.symbols:
                    if sym not in metrics:
                        continue

                    is_noteworthy, t_type, reason = self.triggers[sym].evaluate(
                        metrics[sym], self.prev_metrics.get(sym)
                    )

                    if self.prev_metrics.get(sym) is None:
                        logger.info(f"--- Sniper [{sym}]: Initial Baseline Established ---")

                    if not is_noteworthy:
                        status = reason if "COOLDOWN" in reason else "SLEEPING"
                        print(f"[{now_str}] [{sym}] 💤 {status} | No actionable asymmetry detected.")
                    else:
                        print("\n" + "!" * 60)
                        print(f"       🔫 SNIPER WAKE UP! [{sym}] [{t_type}]")
                        print("!" * 60)
                        print(f"[{sym}] REASON: {reason}")
                        print("!" * 60 + "\n")
                        triggered.append((sym, t_type, reason))

                # ── 3. AI SESSIONS: serial processing (blocking, ~30-90s each) ──
                for sym, t_type, reason in triggered:
                    has_active = bool(self.trade_states.get(sym, {}).get("direction"))

                    if self.session_engines.get(sym) and not has_active:
                        logger.info(f"SniperDaemon [{sym}]: Activating Binary Star reasoning loop (Blocking Pulse)...")
                        logging.getLogger("src.infrastructure.binance.client").setLevel(logging.INFO)

                        session_result = self.session_engines[sym].execute_cycle()

                        logging.getLogger("src.infrastructure.binance.client").setLevel(logging.CRITICAL)

                        if self.trade_enabled and self.executor and session_result and "error" not in session_result:
                            self._attempt_trade_execution(sym, session_result)

                        # Refresh heartbeat so UI sees order/position changes immediately
                        if self.trade_enabled:
                            self._write_guardian_status()

                        logger.info(f"SniperDaemon [{sym}]: Session cycle complete. Returning to pulse monitoring.")
                    elif has_active:
                        logger.info(
                            f"SniperDaemon [{sym}]: Active position ({self.trade_states[sym]['direction']}) exists. "
                            f"Skipping AI session — Guardian trailing stop manages the position.")

                    self.triggers[sym].set_triggered(t_type)

                # ── 4. HOUSEKEEPING ──
                self.prev_metrics = metrics

                # ── 5. Guardian heartbeat file (once per pulse, all symbols) ──
                if self.trade_enabled:
                    self._write_guardian_status()

                # Sleep until next pulse
                logger.debug(f"SniperDaemon: Waiting {pulse_mins}m for next check...")
                time.sleep(pulse_mins * 60)

            except KeyboardInterrupt:
                logger.warning("SniperDaemon terminated by user.")
                break
            except Exception as e:
                logger.error(f"SniperDaemon Loop Failure: {e}", exc_info=True)
                time.sleep(60)

    # ================================================================
    # TRADE GATE: Evaluates AI decision and triggers entry
    # ================================================================

    def _attempt_trade_execution(self, symbol: str, session_result: dict):
        """
        Evaluates session result against confidence threshold and triggers trade execution.
        Keyed by symbol for multi-symbol trade state management.
        """
        try:
            final_decision = session_result.get('final_decision', {})
            opinion = str(final_decision.get('opinion', 'NEUTRAL')).upper()
            confidence = float(final_decision.get('confidence_score', 0))
            tactical = final_decision.get('tactical_parameters', {})

            logger.info(f"TradeGate [{symbol}]: Evaluating session -> Opinion={opinion}, Confidence={confidence}%")

            # Gate 1: Directional opinion required
            if opinion not in ('BULLISH', 'BEARISH'):
                logger.info(f"TradeGate [{symbol}]: Opinion is {opinion}. No trade action.")
                return

            # Gate 2: Confidence threshold
            threshold = int(self.global_cfg['llm']['binary_star']['session_confidence_threshold'])
            if confidence < threshold:
                logger.info(f"TradeGate [{symbol}]: Confidence {confidence}% < threshold {threshold}%. Skipping trade.")
                return

            # Gate 3: Tactical parameters must be present
            entry = tactical.get('entry')
            tp = tactical.get('take_profit')
            sl = tactical.get('stop_loss')
            if not all([entry, tp, sl]):
                logger.warning(f"TradeGate [{symbol}]: Missing tactical parameters (Entry={entry}, TP={tp}, SL={sl}). Skipping trade.")
                return

            # Map AI opinion to executor direction
            direction = 'LONG' if opinion == 'BULLISH' else 'SHORT'

            # Extract projected waiting time for Guardian timeout
            projected_waiting = tactical.get('projected_waiting_hours', 4.0)

            logger.info(f"TradeGate [{symbol}]: ALL GATES PASSED. Executing {direction} "
                        f"(Confidence: {confidence}%, Entry: {entry}, TP: {tp}, SL: {sl}, "
                        f"Projected Wait: {projected_waiting}h)")

            order_id = self.executor.sync_with_opinion(
                symbol=symbol,
                opinion_direction=direction,
                entry_price=float(entry),
                tp_price=float(tp),
                sl_price=float(sl)
            )

            # Update trade state for Guardian tracking
            if order_id and order_id > 0:
                self.trade_states[symbol] = {
                    "direction": direction,
                    "entry_price": float(entry),
                    "tp_price": float(tp),
                    "sl_price": float(sl),
                    "entry_order_id": order_id,
                    "entry_placed_at": datetime.now(timezone.utc),
                    "projected_waiting_hours": float(projected_waiting),
                }
                logger.info(f"TradeGate [{symbol}]: Trade state updated. Guardian will monitor order {order_id}.")
            elif order_id == EMERGENCY_CLOSED_SENTINEL:
                self.trade_states.pop(symbol, None)
                logger.warning(f"TradeGate [{symbol}]: Position was emergency-closed by executor (OCO re-place failure). Trade state cleared.")
            else:
                if not self.trade_states.get(symbol, {}).get("direction"):
                    logger.info(f"TradeGate [{symbol}]: No entry order placed and no active trade state.")

        except Exception as e:
            logger.error(f"TradeGate [{symbol}]: Trade execution failed: {e}", exc_info=True)

    # ================================================================
    # GUARDIAN: Position protection every pulse
    # ================================================================

    def _guardian_check(self, symbol: str):
        """Delegates to MarginOrderExecutor.guardian_check() and updates trade_states[symbol].

        Passes ATR from the most recent scout metrics for progressive trailing stop calculations.
        """
        try:
            logger.debug(f"Guardian [{symbol}]: Checking position state...")

            # Extract ATR from previous scout metrics for trailing stop
            atr = None
            prev = self.prev_metrics.get(symbol)
            if prev:
                atr = prev.get('price_dynamics', {}).get('atr_macro')

            trade_state = self.trade_states.get(symbol, {})
            updated_state = self.executor.guardian_check(symbol, trade_state, atr_macro=atr)

            if updated_state != trade_state:
                if not updated_state:
                    logger.info(f"Guardian [{symbol}]: Trade state cleared (position closed or entry expired).")
                    self.trade_states.pop(symbol, None)
                else:
                    self.trade_states[symbol] = updated_state

        except Exception as e:
            logger.error(f"Guardian [{symbol}]: Check failed: {e}", exc_info=True)

    def _write_guardian_status(self):
        """Write combined guardian heartbeat for all symbols (once per pulse)."""
        try:
            from src.utils.path_utils import resolve_project_root
            import json as _json

            # Fetch account balance once (shared cross-margin account)
            account_balance = None
            try:
                from src.utils.symbol_utils import get_quote_currency
                quote = get_quote_currency()
                account = self.executor.client.get_cross_margin_account()
                for a in (account.assets or []):
                    if a.asset == quote and a.net_asset > 0:
                        account_balance = round(a.net_asset, 2)
                        break
            except Exception:
                pass

            symbols_data = {}
            for sym in self.symbols:
                try:
                    pos = self.executor.client.get_symbol_position(sym)
                    net_qty = pos.net_qty if pos else 0.0
                    active_orders = self.executor.client.get_active_orders(sym)
                    symbols_data[sym] = {
                        "net_qty": net_qty,
                        "has_position": abs(net_qty) > 1e-8,
                        "active_orders": len(active_orders) if active_orders else 0,
                    }
                except Exception:
                    symbols_data[sym] = {"net_qty": 0.0, "has_position": False, "active_orders": 0}

            guardian = {
                "last_pulse_at": datetime.now(timezone.utc).isoformat(),
                "account_balance": account_balance,
                "symbols": symbols_data,
            }

            # Atomic write
            guardian_path = os.path.join(resolve_project_root(), self.args.path, ".sniper_heartbeat.json")
            tmp_path = guardian_path + ".tmp"
            with open(tmp_path, "w") as f:
                _json.dump(guardian, f, default=str)
            os.replace(tmp_path, guardian_path)
        except Exception:
            pass  # Dashboard may not be running; silently skip

def main():
    parser = argparse.ArgumentParser(description="Singularity Sniper Daemon")
    parser.add_argument("--symbol", type=str, required=True, help="Trading pair prefix(es), CSV for multiple (e.g. BTC,ETH,XAUT)")
    parser.add_argument("--trade", nargs='?', const=True, default=False, type=float,
                        help="Enable automated margin trading. Optionally specify manual balance (e.g. --trade 1000). "
                             "Without a value, uses real Binance cross-margin balance.")
    from src.utils.pipeline_utils import add_data_path_argument
    add_data_path_argument(parser)

    args = parser.parse_args()
    
    if not args.path:
        args.path = "data/prod"
    
    daemon = SniperDaemon(args)
    daemon.run_forever()

if __name__ == "__main__":
    main()
