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
from src.sniper.trigger import SniperTrigger, TriggerResult, Direction, SignalCard
from run_session import SessionEngine
from src.utils.logger_utils import setup_logger
from src.utils.progress_utils import add_activity_entry, ACTIVE, COMPLETE, ERROR

# Sentinel matching MarginOrderExecutor.EMERGENCY_CLOSED_SENTINEL
_EMERGENCY_CLOSED_SENTINEL = -1
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
                     max_bytes=10 * 1024 * 1024, backup_count=5,
                     console_color=True)

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
                symbol=sym,
            )
            logger.info(f"SniperDaemon [{sym}]: Trigger Cooldown is active at {self.triggers[sym].cooldown_minutes}m.")

        # 2. Initialize Heavyweight Session Engines (one per symbol, always)
        self.session_engines: dict = {}
        for sym in self.symbols:
            self.session_engines[sym] = SessionEngine(sym, args.path, args=args,
                                                      exchange_client=self.futures_client)

        # 3. LLM / Trade execution
        self.llm_enabled = bool(getattr(args, 'llm', False))
        self.trade_enabled = bool(args.trade)
        self.manual_balance = args.trade if isinstance(args.trade, float) else None
        self.executor = None
        self.trade_states: dict[str, dict] = {}
        if self.trade_enabled:
            from src.infrastructure.binance.margin_client import BinanceMarginClient
            from src.agent.order_executor import MarginOrderExecutor
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

        # Pulse counter (persisted to status file for dashboard display)
        pulse_count = 0
        # Path to the daemon status file (same as dashboard API reads)
        from src.utils.path_utils import resolve_project_root
        import json as _json_module
        _status_path = os.path.join(resolve_project_root(), self.args.path,
                                    ".sniper_daemon_status.json")

        def _read_daemon_status():
            try:
                if os.path.exists(_status_path):
                    with open(_status_path, 'r') as f:
                        return _json_module.load(f)
            except Exception:
                pass
            return None

        def _write_daemon_status(s):
            try:
                tmp = _status_path + ".tmp"
                with open(tmp, 'w') as f:
                    _json_module.dump(s, f, default=str)
                os.replace(tmp, _status_path)
            except Exception:
                pass

        while True:
            try:
                metrics: dict[str, dict] = {}
                triggered: list[tuple[str, 'TriggerResult']] = []

                # ── 0. LIGHTWEIGHT HEARTBEAT: written unconditionally, zero API calls ──
                # Always succeeds — proves the daemon is alive even when trade is off
                # or the heavyweight heartbeat fails on a Binance API blip.
                self._write_lightweight_heartbeat()
                pulse_count += 1

                # ── 0.5 GUARDIAN: protect every symbol with skin in the game ──
                guardian_data: dict[str, dict] = {}
                if self.trade_enabled and self.executor:
                    for sym in self.symbols:
                        gs = self._guardian_check(sym)
                        if gs:
                            guardian_data[sym] = gs

                # ── 0.6 HEAVYWEIGHT HEARTBEAT: fed with guardian data, no extra API calls ──
                if self.trade_enabled:
                    self._write_guardian_status(guardian_data)

                # ── 0.7 Update daemon status with pulse count ──
                s = _read_daemon_status()
                if s:
                    s["pulse_count"] = pulse_count
                else:
                    # First pulse or status file missing — seed it
                    s = {
                        "running": True,
                        "symbols": self.symbols,
                        "pid": os.getpid(),
                        "trade_enabled": self.trade_enabled,
                        "started_at": datetime.now(timezone.utc).isoformat(),
                        "pulse_count": pulse_count,
                    }
                _write_daemon_status(s)

                # ── 1. SCOUT: lightweight data collection per symbol (sequential) ──
                for sym in self.symbols:
                    result = self.scouts[sym].scout()
                    if result.metrics:
                        metrics[sym] = result.metrics

                # ── 2. TRIGGER: independent evaluation per symbol ──
                if not metrics:
                    logger.warning("SniperDaemon: All scouts returned empty metrics. Skipping trigger/AI phase.")
                now_str = datetime.now(timezone.utc).strftime("%H:%M:%S")
                symbol_results: dict[str, 'TriggerResult'] = {}

                for sym in self.symbols:
                    if sym not in metrics:
                        continue

                    result = self.triggers[sym].evaluate(
                        metrics[sym], self.prev_metrics.get(sym)
                    )

                    if self.prev_metrics.get(sym) is None:
                        logger.info(f"--- Sniper [{sym}]: Initial Baseline Established ---")

                    symbol_results[sym] = result

                    if not result.triggered:
                        status = result.gate_reason or "SLEEPING"
                        logger.info(f"[{sym}] 💤 {status}")
                    else:
                        logger.info(f"🔫 SNIPER WAKE UP! [{sym}] [{result.confluence_direction.value}] "
                                    f"confluence={result.confluence_score:.2f} "
                                    f"signals={[s.sub_type for s in result.active_signals]} "
                                    f"gate={result.gate_result}")
                        triggered.append((sym, result))

                # ── 2.5 CROSS-SYMBOL: Leader Sync ──
                # If any symbol triggered, boost correlated followers and re-check
                for sym, result in triggered:
                    for follower_sym in self.symbols:
                        if follower_sym == sym or follower_sym not in symbol_results:
                            continue
                        follower = symbol_results[follower_sym]
                        if follower.triggered:
                            continue  # already firing, no boost needed

                        correlation = self.triggers[follower_sym].CROSS_CORRELATIONS.get(
                            follower_sym, 0.30
                        )
                        leader_card = self.triggers[follower_sym].apply_leader_sync(
                            own_signals=follower.signals,
                            leader_confluence_score=result.confluence_score,
                            leader_direction=result.confluence_direction,
                            correlation=correlation,
                            now=datetime.now(timezone.utc),
                        )
                        if leader_card:
                            boosted_signals = list(follower.signals) + [leader_card]
                            new_result = self.triggers[follower_sym].reevaluate_with_boost(
                                boosted_signals,
                                metrics.get(follower_sym, {}),
                            )
                            if new_result:
                                symbol_results[follower_sym] = new_result
                                triggered.append((follower_sym, new_result))
                                logger.info(
                                    f"SniperDaemon [{follower_sym}]: Leader Sync boost from "
                                    f"[{sym}] — confluence {new_result.confluence_score:.2f} "
                                    f"(was {follower.confluence_score:.2f})"
                                )

                # ── 3. AI SESSIONS: serial processing (blocking, ~30-90s each) ──
                for sym, result in triggered:
                    has_active = bool(self.trade_states.get(sym, {}).get("direction"))

                    if self.session_engines.get(sym) and not has_active:
                        if not self.llm_enabled:
                            logger.info(
                                f"SniperDaemon [{sym}]: OBSERVE-ONLY — would fire AI session "
                                f"(direction={result.confluence_direction.value}, "
                                f"confluence={result.confluence_score:.2f}, "
                                f"signals={[s.sub_type for s in result.active_signals]}, "
                                f"gate={result.gate_result})"
                            )
                        else:
                            logger.info(f"SniperDaemon [{sym}]: Activating Binary Star reasoning loop (Blocking Pulse)...")
                            logging.getLogger("src.infrastructure.binance.client").setLevel(logging.INFO)

                            # ── Write active_session to status before execution ──
                            triggered_at = datetime.now(timezone.utc)
                            s = _read_daemon_status()
                            if s:
                                s["active_session"] = {
                                    "symbol": sym,
                                    "triggered_at": triggered_at.strftime("%H:%M:%S"),
                                    "triggered_at_iso": triggered_at.isoformat(),
                                    "progress": {
                                        "status": "running",
                                        "current_stage": 1,
                                        "stage_label": "Data Collection",
                                        "activity": "Fetching kline data…",
                                        "elapsed_seconds": 0,
                                        "activities": [],
                                    },
                                }
                                _write_daemon_status(s)

                            # ── Progress callback for session execution ──
                            def _sniper_progress(stage=None, activity=None, status="running",
                                                  stage_label=None, result=None, error=None):
                                s2 = _read_daemon_status()
                                if not s2 or not s2.get("active_session"):
                                    return
                                now_utc = datetime.now(timezone.utc)
                                trig_iso = s2["active_session"].get("triggered_at_iso", "")
                                elapsed = 0
                                if trig_iso:
                                    try:
                                        trig_dt = datetime.fromisoformat(trig_iso.replace("Z", "+00:00"))
                                        elapsed = round((now_utc - trig_dt).total_seconds())
                                    except Exception:
                                        pass

                                progress = s2["active_session"].get("progress", {})
                                if status == "running":
                                    activities = list(progress.get("activities", []))
                                    add_activity_entry(activities, activity, elapsed)
                                    progress = {
                                        "status": "running",
                                        "current_stage": stage if stage is not None else progress.get("current_stage", 1),
                                        "stage_label": stage_label or progress.get("stage_label", ""),
                                        "activity": activity or progress.get("activity", ""),
                                        "elapsed_seconds": elapsed,
                                        "activities": activities,
                                    }
                                elif status == "completed":
                                    progress = {
                                        "status": "completed",
                                        "current_stage": 5,
                                        "elapsed_seconds": elapsed,
                                        "result": result or {},
                                        "activities": progress.get("activities", []),
                                    }
                                elif status == "failed":
                                    activities = list(progress.get("activities", []))
                                    if activity:
                                        activities.append({
                                            "time": now_utc.strftime("%H:%M:%S"),
                                            "type": ERROR,
                                            "message": activity,
                                        })
                                    progress = {
                                        "status": "failed",
                                        "current_stage": stage if stage is not None else progress.get("current_stage", 1),
                                        "elapsed_seconds": elapsed,
                                        "error": error or activity or "Unknown error",
                                        "activities": activities,
                                    }
                                s2["active_session"]["progress"] = progress
                                _write_daemon_status(s2)

                            session_result = self.session_engines[sym].execute_cycle(
                                situation_brief=result.situation_brief,
                                progress_callback=_sniper_progress,
                            )

                            logging.getLogger("src.infrastructure.binance.client").setLevel(logging.CRITICAL)

                            if self.trade_enabled and self.executor and session_result and "error" not in session_result:
                                self._attempt_trade_execution(sym, session_result)

                            # ── Clear active_session and update recent signals ──
                            s3 = _read_daemon_status()
                            if s3 and s3.get("active_session"):
                                direction = "NEUTRAL"
                                confidence = 0
                                if session_result and "error" not in session_result:
                                    fd = session_result.get("final_decision", {})
                                    direction = str(fd.get("opinion", "NEUTRAL"))
                                    confidence = int(fd.get("confidence_score", 0))
                                else:
                                    direction = "ERROR"

                                recent = list(s3.get("recent_signals", []))
                                recent.insert(0, {
                                    "time": datetime.now(timezone.utc).strftime("%H:%M"),
                                    "direction": direction,
                                    "confidence": confidence,
                                })
                                s3["recent_signals"] = recent[:5]
                                s3["active_session"] = None
                                _write_daemon_status(s3)

                            logger.info(f"SniperDaemon [{sym}]: Session cycle complete. Returning to pulse monitoring.")
                    elif has_active:
                        logger.info(
                            f"SniperDaemon [{sym}]: Active position ({self.trade_states[sym]['direction']}) exists. "
                            f"Skipping AI session — Guardian trailing stop manages the position.")

                    self.triggers[sym].set_triggered(result)

                # ── 4. HOUSEKEEPING ──
                if metrics:
                    self.prev_metrics = metrics

                # ── 5. Refresh heartbeat with latest guardian state ──
                if self.trade_enabled:
                    self._write_guardian_status(guardian_data)

            except KeyboardInterrupt:
                logger.warning("SniperDaemon terminated by user.")
                break
            except Exception as e:
                logger.error(f"SniperDaemon Loop Failure: {e}", exc_info=True)

            # Sleep until next pulse (shorter retry on empty scout)
            sleep_secs = pulse_mins * 60 if metrics else 60
            logger.debug(f"SniperDaemon: Waiting {sleep_secs}s for next check...")
            time.sleep(sleep_secs)

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
            threshold = int(self.global_cfg['binary_star']['session_confidence_threshold'])
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

            # Extract projected holding/waiting time and entry ATR for adaptive guardian
            projected_waiting = tactical.get('projected_waiting_hours', 0)
            projected_holding = tactical.get('projected_holding_hours', 0)
            entry_atr = float((self.prev_metrics.get(symbol) or {}).get('price_dynamics', {}).get('atr_macro', 0))

            logger.info(f"TradeGate [{symbol}]: ALL GATES PASSED. Executing {direction} "
                        f"(Confidence: {confidence}%, Entry: {entry}, TP: {tp}, SL: {sl}, "
                        f"Projected Wait: {projected_waiting}h, Hold: {projected_holding}h)")

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
                    "projected_holding_hours": float(projected_holding),
                    "entry_atr": entry_atr,
                }
                logger.info(f"TradeGate [{symbol}]: Trade state updated. Guardian will monitor order {order_id}.")
            elif order_id == _EMERGENCY_CLOSED_SENTINEL:
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

    def _guardian_check(self, symbol: str) -> dict | None:
        """Delegates to MarginOrderExecutor.guardian_check() and updates trade_states[symbol].

        Passes ATR from the most recent scout metrics for progressive trailing stop calculations.

        Returns a dict with position/order summary for heartbeat use (no extra API calls needed).
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

            # Return guardian snapshot for heartbeat (harvested during check, no extra API calls)
            try:
                pos = self.executor.client.get_symbol_position(symbol)
                active_orders = self.executor.client.get_active_orders(symbol)
                return {
                    "net_qty": pos.net_qty if pos else 0.0,
                    "has_position": abs(pos.net_qty if pos else 0.0) > 1e-8,
                    "active_orders": len(active_orders) if active_orders else 0,
                }
            except Exception as e:
                logger.warning(f"Guardian [{symbol}]: Position/order snapshot failed ({e}) — heartbeat will show idle")
                return {"net_qty": 0.0, "has_position": False, "active_orders": 0}

        except Exception as e:
            logger.error(f"Guardian [{symbol}]: Check failed: {e}", exc_info=True)
            return None

    def _write_lightweight_heartbeat(self):
        """Zero-API-call liveness proof. Always succeeds — never blocks on Binance.

        Written unconditionally every pulse so the dashboard always has a fresh
        pulse timer, regardless of --trade flag or API health.
        """
        try:
            from src.utils.path_utils import resolve_project_root
            import json as _json
            path = os.path.join(resolve_project_root(), self.args.path, ".sniper_alive.json")
            os.makedirs(os.path.dirname(path), exist_ok=True)
            tmp = path + ".tmp"
            with open(tmp, "w") as f:
                _json.dump({"last_pulse_at": datetime.now(timezone.utc).isoformat()}, f)
            os.replace(tmp, path)
        except Exception as e:
            logger.warning(f"SniperDaemon: Lightweight heartbeat write failed: {e}")

    def _write_guardian_status(self, guardian_data: dict[str, dict] | None = None):
        """Write combined guardian heartbeat for all symbols (once per pulse).

        Accepts guardian_data harvested during _guardian_check() to avoid
        duplicate Binance API calls. Falls back to empty per-symbol entries
        for any missing symbols.
        """
        try:
            from src.utils.path_utils import resolve_project_root
            import json as _json

            # Fetch account balance (one API call, shared cross-margin account)
            account_balance = None
            try:
                from src.utils.symbol_utils import get_quote_currency
                quote = get_quote_currency()
                account = self.executor.client.get_cross_margin_account()
                for a in (account.assets or []):
                    if a.asset == quote and a.net_asset > 0:
                        account_balance = round(a.net_asset, 2)
                        break
            except Exception as e:
                logger.warning(f"SniperDaemon: Account balance fetch skipped ({e})")

            # Use guardian data already harvested — no extra position/order API calls
            symbols_data = {}
            for sym in self.symbols:
                gs = (guardian_data or {}).get(sym)
                symbols_data[sym] = gs if gs else {
                    "net_qty": 0.0, "has_position": False, "active_orders": 0,
                }

            guardian = {
                "last_pulse_at": datetime.now(timezone.utc).isoformat(),
                "account_balance": account_balance,
                "symbols": symbols_data,
            }

            # Atomic write
            guardian_path = os.path.join(resolve_project_root(), self.args.path, ".sniper_heartbeat.json")
            os.makedirs(os.path.dirname(guardian_path), exist_ok=True)
            tmp_path = guardian_path + ".tmp"
            with open(tmp_path, "w") as f:
                _json.dump(guardian, f, default=str)
            os.replace(tmp_path, guardian_path)
        except Exception as e:
            logger.warning(f"SniperDaemon: Heavyweight heartbeat write failed: {e}")

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
