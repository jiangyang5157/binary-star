#!/usr/bin/env python3
import os
import sys
import time
import signal
import argparse
import json
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

    # Fixed list of all 10 signal types — ensures every symbol card has identical rows
    _SIGNAL_TYPES = [
        'cvd_momentum', 'cvd_divergence', 'cvd_absorption',
        'large_trade', 'volatility_surge', 'squeeze',
        'boundary_test', 'liquidation_hunt', 'positioning_extreme',
        'leader_sync',
    ]

    _STATE_FILE = ".sniper_state.json"
    _PULSE_FILE = ".sniper_pulse.json"
    _HISTORY_FILE = ".sniper_pulse_history.json"

    def __init__(self, args):
        from src.utils.symbol_utils import resolve_symbols

        self.args = args
        self.global_cfg = load_global_config()
        self._history_max = (
            self.global_cfg.get('sniper', {})
            .get('heartbeat', {})
            .get('pulse_history_max_entries', 120)
        )

        # Parse CSV symbol list (e.g., "XAUT,BTC" → ["XAUTUSDT", "BTCUSDT"])
        raw_symbols = getattr(args, 'symbol', '') or ''
        self.symbols = resolve_symbols(raw_symbols)

        # Validate all symbols are explicitly configured — no silent fallback
        from src.config.symbol_resolver import is_symbol_configured
        for sym in self.symbols:
            if not is_symbol_configured(sym):
                logger.critical(
                    "symbol '%s' is not configured in symbol_config.yaml | "
                    "add precision_qty, precision_price, min_order_qty, sl_slippage_buffer",
                    sym,
                )
                sys.exit(1)

        # 0. Global Forensic Logging Initialization
        from src.utils.path_utils import resolve_project_root
        _project_root = resolve_project_root()
        _data_root = os.path.join(_project_root, args.path)
        session_log_path = os.path.join(_data_root, "sniper.log")
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
            cfg = self.triggers[sym].sniper_cfg.get('signal_stack', {}).get('cooldown', {})
            mins = cfg.get('regime_base_minutes', {})
            logger.info(f"[{sym}] trigger cooldown configured | regime_mins={mins}")

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
            self.margin_client = BinanceMarginClient()
            self.executor = MarginOrderExecutor(client=self.margin_client, manual_balance_usdt=self.manual_balance)
            if self.manual_balance:
                logger.info(f"manual balance | ${self.manual_balance:.2f} USDT")
            logger.info(f"trade execution ENABLED | symbols={self.symbols}")

        # Per-symbol previous metrics for inter-pulse comparison
        self.prev_metrics: dict[str, dict | None] = {sym: None for sym in self.symbols}

        # Per-symbol partial TP level tracking (in-memory only, lost on restart)
        self._symbol_level: dict[str, int] = {}  # next level to check (0 = L1)
        self._symbol_last_qty: dict[str, float] = {}  # detect manual qty changes

        # Sniper Quiet-Monitoring Protocol
        logging.getLogger("src.infrastructure.binance.client").setLevel(logging.CRITICAL)

        # Persistence paths (reuse _data_root from logger setup above)
        os.makedirs(_data_root, exist_ok=True)
        self._state_path = os.path.join(_data_root, self._STATE_FILE)
        self._pulse_path = os.path.join(_data_root, self._PULSE_FILE)
        self._history_path = os.path.join(_data_root, self._HISTORY_FILE)

        self._setup_signals()

    def _setup_signals(self):
        for sig in (signal.SIGINT, signal.SIGTERM):
            signal.signal(sig, self._handle_termination)

    def _handle_termination(self, signum, frame):
        logger.warning("termination signal received | shutting down")
        try:
            self._write_state(running=False)
        except Exception:
            pass
        try:
            self.futures_client.close()
        except Exception as e:
            logger.warning(f"failed to close futures client during shutdown | error={e}")
        try:
            if self.executor is not None:
                self.executor.client.close()
        except Exception as e:
            logger.warning(f"failed to close margin client during shutdown | error={e}")
        try:
            if os.path.exists(self._history_path):
                os.remove(self._history_path)
        except Exception:
            pass
        sys.exit(0)

    def run_forever(self):
        pulse_mins = self.global_cfg['sniper']['heartbeat']['pulse_interval_minutes']
        if pulse_mins <= 0:
            raise ValueError(f"pulse_interval_minutes must be > 0, got {pulse_mins}")
        sym_list = ", ".join(self.symbols)
        logger.info(f"═══ SNIPER MONITORING STARTED | symbols={sym_list} | pulse={pulse_mins}m ═══")

        # Truncate pulse history to clean slate on each sniper run
        if not getattr(self, '_history_cleared', False):
            self._history_cleared = True
            try:
                with open(self._history_path, 'w') as f:
                    f.write('[]\n')
            except Exception as e:
                logger.warning(f"history file truncate failed | error={e}")

        while True:
            try:
                metrics: dict[str, dict] = {}
                triggered: list[tuple[str, 'TriggerResult']] = []

                # ── 0. STATE: pulse timestamp (unconditional, zero API calls) ──
                self._write_state(last_pulse_at=datetime.now(timezone.utc).isoformat())

                # Seed state on first pulse if dashboard didn't pre-populate it
                # (e.g., sniper started from CLI instead of dashboard API)
                if not getattr(self, '_state_seeded', False):
                    self._state_seeded = True
                    if "running" not in self._read_state():
                        self._write_state(
                            running=True,
                            symbols=self.symbols,
                            pid=os.getpid(),
                            trade_enabled=self.trade_enabled,
                            balance=self.manual_balance,
                            started_at=datetime.now(timezone.utc).isoformat(),
                        )

                # ── 0.5 GUARDIAN: protect every symbol with skin in the game ──
                guardian_data: dict[str, dict] = {}
                if self.trade_enabled and self.executor:
                    for sym in self.symbols:
                        gs = self._guardian_check(sym)
                        if gs:
                            guardian_data[sym] = gs

                # ── 1. SCOUT: lightweight data collection per symbol (sequential) ──
                for sym in self.symbols:
                    result = self.scouts[sym].scout()
                    if result.metrics:
                        metrics[sym] = result.metrics

                # ── 2. TRIGGER: independent evaluation per symbol ──
                if not metrics:
                    logger.warning("all scouts returned empty metrics | skipping trigger/AI phase")
                symbol_results: dict[str, 'TriggerResult'] = {}

                for sym in self.symbols:
                    if sym not in metrics:
                        continue

                    result = self.triggers[sym].evaluate(
                        metrics[sym], self.prev_metrics.get(sym)
                    )

                    if self.prev_metrics.get(sym) is None:
                        logger.info(f"[{sym}] initial baseline established")

                    symbol_results[sym] = result

                    if not result.triggered:
                        status = result.gate_reason or "SLEEPING"
                        logger.debug(f"[{sym}] 💤 {status}")
                    else:
                        logger.info(f"🔫 [{sym}] WAKE UP | dir={result.confluence_direction.value} | "
                                    f"confluence={result.confluence_score:.2f} | "
                                    f"signals={[s.sub_type for s in result.active_signals]}")
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

                        # Matrix lookup: leader → {follower: coefficient}
                        correlation = self.triggers[follower_sym].CROSS_CORRELATIONS.get(
                            sym, {}
                        ).get(follower_sym, 0)
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
                                    f"[{follower_sym}] leader sync boost from [{sym}] | "
                                    f"confluence={new_result.confluence_score:.2f} | "
                                    f"was={follower.confluence_score:.2f}"
                                )

                # ── 2.8 PULSE: combined guardian + signal state (single atomic write) ──
                triggered_syms = {sym for sym, _ in triggered}
                self._write_pulse(guardian_data, symbol_results, triggered_syms)
                self._write_pulse_history(symbol_results, triggered_syms)

                # ── 3. AI SESSIONS: serial processing (blocking, ~30-90s each) ──
                for sym, result in triggered:
                    # Block new sessions only when the bot itself has an active trade.
                    # Manual positions (no trade_state) are allowed through — the
                    # session's sync_with_opinion handles conflicts (pivot block or
                    # optimize), and cooldown regulates frequency.
                    has_active = bool(self.trade_states.get(sym, {}).get("direction"))
                    trigger_type: str = "NEUTRAL"  # default fallback

                    if self.session_engines.get(sym) and not has_active:
                        if not self.llm_enabled:
                            trigger_type = "OBSERVE_ONLY"
                            logger.info(
                                f"[{sym}] OBSERVE-ONLY | would fire AI session | "
                                f"dir={result.confluence_direction.value} | "
                                f"confluence={result.confluence_score:.2f} | "
                                f"signals={[s.sub_type for s in result.active_signals]}"
                            )
                        else:
                            logger.info(f"[{sym}] activating Binary Star reasoning loop")
                            logging.getLogger("src.infrastructure.binance.client").setLevel(logging.INFO)

                            # ── Write active_session to state before execution ──
                            triggered_at = datetime.now(timezone.utc)
                            self._write_state(active_session={
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
                            })

                            # ── Progress callback for session execution ──
                            def _sniper_progress(stage=None, activity=None, status="running",
                                                  stage_label=None, result=None, error=None):
                                current = self._read_state()
                                active_session = current.get("active_session") if current else None
                                if not active_session:
                                    return
                                now_utc = datetime.now(timezone.utc)
                                trig_iso = active_session.get("triggered_at_iso", "")
                                elapsed = 0
                                if trig_iso:
                                    try:
                                        trig_dt = datetime.fromisoformat(trig_iso.replace("Z", "+00:00"))
                                        elapsed = round((now_utc - trig_dt).total_seconds())
                                    except Exception:
                                        pass

                                progress = active_session.get("progress", {})
                                if status == "running":
                                    activities = list(progress.get("activities", []))
                                    add_activity_entry(activities, activity)
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
                                active_session["progress"] = progress
                                self._write_state(active_session=active_session)

                            try:
                                session_result = self.session_engines[sym].execute_cycle(
                                    situation_brief=result.situation_brief,
                                    progress_callback=_sniper_progress,
                                )

                                logging.getLogger("src.infrastructure.binance.client").setLevel(logging.CRITICAL)

                                if self.trade_enabled and self.executor and session_result and "error" not in session_result:
                                    self._attempt_trade_execution(sym, session_result)

                                # Outcome-aware cooldown: TRADED vs NEUTRAL
                                opinion = (
                                    session_result.get("final_decision", {}).get("opinion", "NEUTRAL")
                                    if session_result else "NEUTRAL"
                                )
                                trigger_type = (
                                    "TRADED" if (opinion in ("BULLISH", "BEARISH") and self.trade_enabled)
                                    else "NEUTRAL"
                                )
                            finally:
                                # ── Always clear active_session, even if execute_cycle raises ──
                                self._write_state(active_session=None)

                            logger.info(f"[{sym}] session complete — returning to monitoring")
                    elif has_active:
                        trigger_type = "ACTIVE_POSITION"
                        logger.info(
                            f"[{sym}] active trade ({self.trade_states[sym]['direction']}) | "
                            f"skipping AI session — Guardian manages")

                    self.triggers[sym].set_triggered(result, trigger_type)

                # ── 4. HOUSEKEEPING ──
                if metrics:
                    self.prev_metrics = metrics

            except KeyboardInterrupt:
                logger.warning("terminated by user")
                break
            except Exception as e:
                logger.error(f"loop failure | error={e}", exc_info=True)

            # Sleep until next pulse (shorter retry on empty scout).
            if metrics:
                sleep_secs = pulse_mins * 60
            else:
                sleep_secs = 60
            logger.debug(f"waiting {sleep_secs}s for next pulse")
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

            logger.info(f"[{symbol}] evaluating session | opinion={opinion} | confidence={confidence}%")

            # Gate 1: Directional opinion required
            if opinion not in ('BULLISH', 'BEARISH'):
                logger.info(f"[{symbol}] opinion is {opinion} | no trade action")
                return

            # Gate 2: Confidence threshold
            threshold = int(self.global_cfg['binary_star']['confidence_threshold'])
            if confidence < threshold:
                logger.info(f"[{symbol}] confidence {confidence}% < threshold {threshold}% | skipping trade")
                return

            # Gate 3: Tactical parameters must be present
            entry = tactical.get('entry')
            tp = tactical.get('take_profit')
            sl = tactical.get('stop_loss')
            if not all([entry, tp, sl]):
                logger.warning(f"[{symbol}] missing tactical parameters | entry={entry} | tp={tp} | sl={sl} | skipping trade")
                return

            # Map AI opinion to executor direction
            direction = 'LONG' if opinion == 'BULLISH' else 'SHORT'

            # Extract projected holding/waiting time and entry ATR for adaptive guardian
            projected_waiting = tactical.get('projected_waiting_hours', 0)
            projected_holding = tactical.get('projected_holding_hours', 0)
            logger.info(f"[{symbol}] ALL GATES PASSED | executing {direction} | "
                        f"confidence={confidence}% | entry={entry} | tp={tp} | sl={sl} | "
                        f"wait={projected_waiting}h | hold={projected_holding}h")

            result = self.executor.sync_with_opinion(
                symbol=symbol,
                opinion_direction=direction,
                entry_price=float(entry),
                tp_price=float(tp),
                sl_price=float(sl)
            )

            # Update trade state for Guardian tracking
            if result == _EMERGENCY_CLOSED_SENTINEL:
                self.trade_states.pop(symbol, None)
                logger.warning(f"[{symbol}] emergency-closed by executor (OCO re-place failure) | trade state cleared")
            elif isinstance(result, dict):
                # _optimize_same_direction returned state update — merge into existing trade_state
                existing = self.trade_states.get(symbol, {})
                existing.update(result)
                self.trade_states[symbol] = existing
                logger.info(f"[{symbol}] trade_state updated from optimize | {existing}")
            elif isinstance(result, int) and result > 0:
                self.trade_states[symbol] = {
                    "direction": direction,
                    "entry_price": float(entry),
                    "tp_price": float(tp),
                    "sl_price": float(sl),
                    "otoco_placed_at": datetime.now(timezone.utc),
                    "projected_waiting_hours": float(projected_waiting),
                    "projected_holding_hours": float(projected_holding),
                }
                logger.info(f"[{symbol}] trade state updated | order={result}")
            else:
                if not self.trade_states.get(symbol, {}).get("direction"):
                    logger.info(f"[{symbol}] no entry order placed | no active trade state")

        except Exception as e:
            logger.error(f"[{symbol}] trade execution failed | error={e}", exc_info=True)

    # ================================================================
    # GUARDIAN: Position protection every pulse
    # ================================================================

    def _guardian_check(self, symbol: str) -> dict | None:
        """Delegates to MarginOrderExecutor.guardian_check() and updates trade_states[symbol].

        Tracks partial TP level in memory (not persisted to trade_state).
        Detects manual qty changes and re-finds level from exchange state.
        """
        try:
            logger.debug(f"[{symbol}] checking position state")

            trade_state = self.trade_states.get(symbol, {})

            # Detect qty changes that invalidate level memory
            pos = self.executor.client.get_symbol_position(symbol)
            net_qty = abs(pos.net_qty) if pos else 0.0
            last_qty = self._symbol_last_qty.get(symbol, 0.0)
            if net_qty > 1e-8 and abs(net_qty - last_qty) > 1e-8:
                # Qty changed: level may be stale → reset
                self._symbol_level.pop(symbol, None)
            self._symbol_last_qty[symbol] = net_qty

            # Determine current level
            next_level = self._symbol_level.get(symbol)
            if next_level is None and trade_state.get("direction"):
                # Level uninitialized: find from exchange, sync SL, skip TP
                next_level = self.executor.find_level_and_sync_sl(
                    symbol, trade_state
                )
                self._symbol_level[symbol] = next_level
                logger.info(f"[{symbol}] level initialized | next_level={next_level}")

            # Guardian check with known level (default 0 = start from L1)
            updated_state, new_level = self.executor.guardian_check(
                symbol, trade_state, current_level=next_level if next_level is not None else 0
            )

            # Update level if partial TP advanced it
            if new_level is not None and new_level != next_level:
                self._symbol_level[symbol] = new_level

            if not updated_state:
                if trade_state:
                    logger.info(f"[{symbol}] trade state cleared (position closed or entry expired)")
                    self.trade_states.pop(symbol, None)
                    self._symbol_level.pop(symbol, None)
                    self._symbol_last_qty.pop(symbol, None)
                    # Reset cooldown so a fresh signal can fire immediately —
                    # bot has no skin in the game. Emergency close paths
                    # (EMERGENCY_CLOSED_SENTINEL) do not go through here.
                    if symbol in self.triggers:
                        self.triggers[symbol].last_trigger_time = None
                        self.triggers[symbol].cooldown_active = False
                        logger.info(f"[{symbol}] cooldown reset (trade cleared)")
            elif updated_state != trade_state:
                self.trade_states[symbol] = updated_state

            # Return guardian snapshot for heartbeat (harvested during check, no extra API calls)
            try:
                return {
                    "net_qty": pos.net_qty if pos else 0.0,
                    "active_orders": len(self.executor.client.get_active_orders(symbol)),
                }
            except Exception as e:
                logger.warning(f"[{symbol}] heartbeat snapshot failed | error={e}")
                return {"net_qty": pos.net_qty if pos else 0.0, "active_orders": 0}

        except Exception as e:
            logger.error(f"[{symbol}] guardian check failed | error={e}", exc_info=True)
            return None

    # ── Persistence ───────────────────────────────────────────────────────

    def _read_state(self) -> dict:
        """Read .sniper_state.json, returning empty dict on any failure."""
        try:
            if os.path.exists(self._state_path):
                with open(self._state_path, 'r') as f:
                    return json.load(f)
        except Exception:
            pass
        return {}

    def _write_state(self, **kwargs):
        """Atomically update .sniper_state.json with given key-value pairs.

        Reads current state, merges kwargs, writes atomically via tmp+rename.
        Used for: pulse timestamp (every pulse), active_session lifecycle.
        """
        try:
            state = self._read_state()
            state.update(kwargs)
            tmp = self._state_path + ".tmp"
            with open(tmp, 'w') as f:
                json.dump(state, f, default=str, indent=2)
            os.replace(tmp, self._state_path)
        except Exception as e:
            logger.warning(f"state write failed | error={e}")

    def _write_pulse(self, guardian_data: dict[str, dict] | None,
                     symbol_results: dict, triggered_syms: set):
        """Write .sniper_pulse.json — guardian state + signal diagnostics.

        Guardian data comes from the pre-collected guardian_data dict
        (no extra API calls). Signal data is extracted from trigger
        evaluation results. Single atomic write per pulse.
        """
        try:
            # Account balance (one API call, shared cross-margin account)
            account_balance = None
            if self.trade_enabled and self.executor:
                try:
                    from src.utils.symbol_utils import get_quote_currency
                    quote = get_quote_currency()
                    account = self.executor.client.get_cross_margin_account()
                    for a in (account.assets or []):
                        if a.asset == quote and a.net_asset > 0:
                            account_balance = round(a.net_asset, 2)
                            break
                except Exception as e:
                    logger.warning(f"account balance fetch skipped | error={e}")

            symbols_data = {}
            for sym in self.symbols:
                # ── Guardian fields ──
                gs = (guardian_data or {}).get(sym)
                entry = dict(gs) if gs else {"net_qty": 0.0, "active_orders": 0}

                trigger = self.triggers.get(sym)
                cooldown_active = trigger.cooldown_active if trigger else False

                # ── Signal fields ──
                result = symbol_results.get(sym)
                if result:
                    active_types = {sig.sub_type for sig in result.active_signals}
                    sig_by_type = {sig.sub_type: sig for sig in result.signals}

                    all_signals = []
                    for sub_type in self._SIGNAL_TYPES:
                        sig = sig_by_type.get(sub_type)
                        if sig:
                            all_signals.append({
                                "type": sig.sub_type,
                                "score": round(sig.weighted_score, 2),
                                "strength": round(sig.strength, 2),
                                "direction": sig.direction.value,
                                "is_active": sig.sub_type in active_types,
                            })
                        else:
                            all_signals.append({
                                "type": sub_type,
                                "score": 0,
                                "strength": 0,
                                "direction": "NEUTRAL",
                                "is_active": False,
                            })

                    cooldown_total_s = int(result.cooldown_minutes * 60)
                    if cooldown_active and trigger and trigger.last_trigger_time:
                        elapsed_cd = (datetime.now(timezone.utc) - trigger.last_trigger_time).total_seconds()
                        cooldown_remaining = max(0, int(cooldown_total_s - elapsed_cd))
                    else:
                        cooldown_remaining = cooldown_total_s

                    entry.update({
                        "triggered": sym in triggered_syms,
                        "confluence_score": round(result.confluence_score, 2),
                        "threshold": round(trigger.engine.effective_threshold, 2),
                        "direction": result.confluence_direction.value,
                        "signals": all_signals,
                        "cooldown_active": cooldown_active,
                        "cooldown_remaining_seconds": cooldown_remaining,
                        "gate_reason": result.gate_reason or "",
                    })
                else:
                    # No trigger result for this symbol — fill defaults
                    if cooldown_active and trigger and trigger.last_trigger_time:
                        cd_cfg = trigger.sniper_cfg.get('signal_stack', {}).get('cooldown', {})
                        regime_mins = cd_cfg['regime_base_minutes']
                        cd_minutes = max(regime_mins.values())
                        cd_remaining = max(0, int(
                            cd_minutes * 60 -
                            (datetime.now(timezone.utc) - trigger.last_trigger_time).total_seconds()
                        ))
                    else:
                        cd_remaining = 0
                    entry.update({
                        "triggered": False,
                        "confluence_score": 0.0,
                        "threshold": round(trigger.engine.effective_threshold, 2),
                        "direction": "NEUTRAL",
                        "signals": [{"type": t, "score": 0, "strength": 0,
                                      "direction": "NEUTRAL", "is_active": False}
                                     for t in self._SIGNAL_TYPES],
                        "cooldown_active": cooldown_active,
                        "cooldown_remaining_seconds": cd_remaining,
                        "gate_reason": "",
                    })

                symbols_data[sym] = entry

            payload = {
                "pulse_at": datetime.now(timezone.utc).isoformat(),
                "account_balance": account_balance,
                "symbols": symbols_data,
            }

            tmp = self._pulse_path + ".tmp"
            with open(tmp, 'w') as f:
                json.dump(payload, f, default=str, indent=2)
            os.replace(tmp, self._pulse_path)
        except Exception as e:
            logger.warning(f"pulse write failed | error={e}")

    def _write_pulse_history(self, symbol_results: dict, triggered_syms: set):
        """Append current pulse snapshot to .sniper_pulse_history.json ring buffer."""
        try:
            entry = {
                "at": datetime.now(timezone.utc).isoformat(),
                "symbols": {},
            }
            for sym in self.symbols:
                result = symbol_results.get(sym)
                trigger = self.triggers.get(sym)
                entry["symbols"][sym] = {
                    "confluence_score": round(result.confluence_score, 2) if result else 0.0,
                    "threshold": round(trigger.engine.effective_threshold, 2) if trigger and trigger.engine else 0.0,
                    "direction": result.confluence_direction.value if result else "NEUTRAL",
                    "session_active": sym in triggered_syms,
                }

            # Read existing, append, trim
            history = []
            try:
                with open(self._history_path, 'r') as f:
                    history = json.loads(f.read() or '[]')
            except (FileNotFoundError, json.JSONDecodeError):
                pass

            history.append(entry)
            if len(history) > self._history_max:
                history = history[-self._history_max:]

            # Atomic write (tmp + rename)
            tmp = self._history_path + ".tmp"
            with open(tmp, 'w') as f:
                json.dump(history, f, default=str, indent=2)
            os.replace(tmp, self._history_path)
        except Exception as e:
            logger.warning(f"pulse history write failed | error={e}")

def main():
    parser = argparse.ArgumentParser(description="Singularity Sniper Daemon")
    parser.add_argument("--symbol", type=str, required=True, help="Trading pair prefix(es), CSV for multiple (e.g. BTC,XAUT)")
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
