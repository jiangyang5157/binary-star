#!/usr/bin/env python3
"""
Standalone OTOCO order placer — reads a session report JSON and places an
OTOCO (entry + nested TP/SL) order via Binance Spot Margin SAPI.

Independent of the Sniper daemon. Before running, ensure the target symbol
has no existing positions or conflicting orders — this script does NOT check
position state and places the order unconditionally.

Usage:
    python scripts/place_otoco.py -f data/prod/sessions/XAUTUSDT_session_20260706_031700.json -qty 0.179
"""

import argparse
import json
import os
import sys

# Ensure src/ is importable regardless of cwd
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_src = os.path.join(_PROJECT_ROOT, "src")
if _src not in sys.path:
    sys.path.insert(0, _src)
_scripts = os.path.join(_PROJECT_ROOT, "scripts")
if _scripts not in sys.path:
    sys.path.insert(0, _scripts)

from dotenv import load_dotenv
load_dotenv()

import yaml
from src.config.symbol_resolver import get_symbol_trade_params, is_symbol_configured
from src.infrastructure.binance.margin_client import BinanceMarginClient
from src.utils.logger_utils import setup_logger
from src.utils.path_utils import resolve_project_root

logger = setup_logger(__name__)
from calculate_qty import calculate_sized_qty  # noqa: E402 — sibling import


# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------

def _load_symbol_config() -> dict:
    path = os.path.join(resolve_project_root(), "config", "symbol_config.yaml")
    with open(path) as f:
        return yaml.safe_load(f)

def _get_sl_buffer(symbol: str) -> float:
    cfg = _load_symbol_config()
    sym = cfg.get(symbol)
    if not sym:
        raise KeyError(f"Symbol '{symbol}' not found in symbol_config.yaml")
    return float(sym["sl_slippage_buffer"])


# ---------------------------------------------------------------------------
# Pre-condition checks
# ---------------------------------------------------------------------------

def _check_direction_sanity(opinion: str, entry: float, sl: float, tp: float) -> tuple[bool, str]:
    """Verify entry/SL/TP have the correct directional relationship."""
    if opinion == "BULLISH":
        if entry <= sl:
            return False, f"BULLISH: entry ({entry}) must be ABOVE SL ({sl})"
        if entry >= tp:
            return False, f"BULLISH: entry ({entry}) must be BELOW TP ({tp})"
    elif opinion == "BEARISH":
        if entry >= sl:
            return False, f"BEARISH: entry ({entry}) must be BELOW SL ({sl})"
        if entry <= tp:
            return False, f"BEARISH: entry ({entry}) must be ABOVE TP ({tp})"
    else:
        return False, f"Unknown opinion '{opinion}' — expected BULLISH or BEARISH"
    return True, "OK"


def _check_price_in_range(opinion: str, current: float, sl: float, tp: float) -> tuple[bool, str]:
    """Verify the current price is between SL and TP (direction-aware)."""
    if opinion == "BULLISH":
        if current >= tp:
            return False, f"Price ({current}) >= TP ({tp}) — take-profit already hit"
        if current <= sl:
            return False, f"Price ({current}) <= SL ({sl}) — stop-loss already hit"
        return True, f"Price ({current}) is between SL ({sl}) and TP ({tp}) ✓"
    elif opinion == "BEARISH":
        if current <= tp:
            return False, f"Price ({current}) <= TP ({tp}) — take-profit already hit"
        if current >= sl:
            return False, f"Price ({current}) >= SL ({sl}) — stop-loss already hit"
        return True, f"Price ({current}) is between TP ({tp}) and SL ({sl}) ✓"
    return True, "OK"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Standalone OTOCO placer — place entry+TP+SL from a session report"
    )
    parser.add_argument(
        "-f", "--session", required=True,
        help="Path to session report JSON (e.g. data/prod/sessions/XAUTUSDT_session_*.json)",
    )
    parser.add_argument(
        "-qty", "--quantity", type=float,
        help="Order quantity in base asset units (mutually exclusive with -balance)",
    )
    parser.add_argument(
        "-b", "--balance", type=float,
        help="Account equity in USDT — auto-calculates qty from session risk params",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Run all checks but skip placing the actual order",
    )
    args = parser.parse_args()

    # Resolve quantity: -qty, -balance, or error
    if args.quantity is not None and args.balance is not None:
        parser.error("Use either -qty (explicit quantity) or -balance (auto-calculate), not both.")
    if args.quantity is None and args.balance is None:
        parser.error("Must provide either -qty (explicit quantity) or -balance (auto-calculate).")
    if args.quantity is not None and args.quantity <= 0:
        parser.error("Quantity must be positive.")
    if args.balance is not None and args.balance <= 0:
        parser.error("Balance must be positive.")

    # ---- 1. Load session JSON ----
    session_path = os.path.abspath(args.session)
    if not os.path.exists(session_path):
        logger.error(f"Session file not found: {session_path}")
        sys.exit(1)

    with open(session_path) as f:
        session = json.load(f)

    try:
        symbol = session["observation"]["symbol"]
        fd = session["final_decision"]
        opinion = fd["opinion"]
        tp = fd["tactical_parameters"]
        entry = float(tp["entry"])
        take_profit = float(tp["take_profit"])
        stop_loss = float(tp["stop_loss"])
        confidence = float(fd.get("confidence_score", 0))
    except (KeyError, ValueError) as e:
        logger.error(f"Missing or invalid field in session JSON: {e}")
        sys.exit(1)

    if opinion == "NEUTRAL":
        logger.error(f"Session opinion is NEUTRAL — nothing to execute")
        sys.exit(1)

    logger.info(
        "Session loaded | symbol=%s | opinion=%s | confidence=%.1f%% | "
        "entry=%.2f | tp=%.2f | sl=%.2f",
        symbol, opinion, confidence, entry, take_profit, stop_loss,
    )

    # ---- 2. Resolve quantity: -qty vs -balance ----
    if args.balance is not None:
        root = resolve_project_root()
        cfg_path = os.path.join(root, "config", "global_config.yaml")
        with open(cfg_path) as f:
            gcfg = yaml.safe_load(f)

        try:
            risk_per_trade = gcfg["trade_management"]["risk_per_trade"]
            taker_fee_rate = gcfg["trade_management"].get("taker_fee_rate", 0.0)
        except KeyError as e:
            logger.error("Missing field in global_config.yaml: %s", e)
            sys.exit(1)

        if not is_symbol_configured(symbol):
            logger.error("Symbol %s not configured in symbol_config.yaml", symbol)
            sys.exit(1)
        sym_cfg = get_symbol_trade_params(symbol)
        p_qty = sym_cfg["precision_qty"]
        min_qty = sym_cfg.get("min_order_qty", 0.0)
        buffer = sym_cfg.get("sl_slippage_buffer", 0.0)

        # Direction sanity before quantity calc — catch entry==SL early
        ok, msg = _check_direction_sanity(opinion, entry, stop_loss, take_profit)
        if not ok:
            logger.error("Direction sanity: %s", msg)
            sys.exit(1)

        try:
            _, qty = calculate_sized_qty(
                args.balance, risk_per_trade, entry, stop_loss,
                p_qty, min_qty, taker_fee_rate,
            )
        except ValueError as e:
            logger.error("Quantity calculation: %s", e)
            sys.exit(1)

        risk_per_unit = abs(entry - stop_loss)
        max_loss_actual = risk_per_unit * qty
        logger.info(
            "Auto-calculated qty from balance=%.2f | risk=%.2f%% | qty=%s | "
            "max_loss=%.2f",
            args.balance, risk_per_trade * 100, f"{qty:.{p_qty}f}",
            max_loss_actual,
        )
    else:
        qty = args.quantity

    # ---- 3. Get current price ----
    client = BinanceMarginClient()
    current_price = client.get_ticker_price(symbol)
    if not current_price or current_price <= 0:
        logger.error(f"Failed to fetch current price for {symbol}")
        sys.exit(1)
    logger.info("Current price | %s = %.4f", symbol, current_price)

    # ---- 4. Pre-checks ----
    # 4a. Symbol config buffer (already loaded on -balance path)
    if args.balance is None:
        try:
            buffer = _get_sl_buffer(symbol)
        except KeyError as e:
            logger.error(f"Symbol config check: {e}")
            sys.exit(1)

    # 4b. Direction sanity (already checked on -balance path)
    if args.balance is None:
        ok, msg = _check_direction_sanity(opinion, entry, stop_loss, take_profit)
        if not ok:
            logger.error(f"Direction sanity: {msg}")
            sys.exit(1)
        logger.info("Direction sanity: %s", msg)

    # 4c. Current price within SL↔TP range
    ok, msg = _check_price_in_range(opinion, current_price, stop_loss, take_profit)
    if not ok:
        logger.error(f"Price range: {msg}")
        sys.exit(1)
    logger.info("Price range: %s", msg)

    # 4d. Active orders (warn only)
    active_orders = client.get_active_orders(symbol)
    if active_orders:
        logger.warning("⚠ Existing active orders for %s (%d order(s))", symbol, len(active_orders))
        for o in active_orders[:10]:  # cap at 10 to avoid spam
            logger.warning(
                "  order_id=%s | side=%s | type=%s | orig_qty=%s | price=%s",
                o.order_id, o.side, o.type, o.orig_qty, o.price,
            )
    else:
        logger.info("No active orders for %s", symbol)

    # 4e. Entry distance
    distance = abs(current_price - entry)
    distance_pct = (distance / current_price) * 100
    logger.info(
        "Entry distance | current=%.4f | entry=%.2f | gap=%.2f (%.2f%%)",
        current_price, entry, distance, distance_pct,
    )

    # ---- 5. Risk/reward summary ----
    risk_per_unit = abs(entry - stop_loss)
    reward_per_unit = abs(entry - take_profit)
    max_loss = risk_per_unit * qty
    max_gain = reward_per_unit * qty
    rr_ratio = reward_per_unit / risk_per_unit if risk_per_unit > 0 else 0
    logger.info(
        "Risk/Reward | max_loss=$%.2f | max_gain=$%.2f | RR=1:%.2f | "
        "risk_per_unit=%.2f | reward_per_unit=%.2f",
        max_loss, max_gain, rr_ratio, risk_per_unit, reward_per_unit,
    )

    # ---- 6. Place OTOCO ----
    side = "BUY" if opinion == "BULLISH" else "SELL"
    sl_trigger = stop_loss
    sl_limit = stop_loss + (buffer if side == "SELL" else -buffer)

    logger.info(
        "Deploying | symbol=%s | side=%s | qty=%s | entry=%.2f | tp=%.2f | "
        "sl_trigger=%.2f | sl_limit=%.2f (buffer=%.1f)",
        symbol, side, qty, entry, take_profit, sl_trigger, sl_limit, buffer,
    )

    if args.dry_run:
        logger.info("DRY RUN — skipping order placement")
        print("\n🔍 Dry run complete — all checks passed, no order placed.")
        return

    order_list_id = client.place_otoco_order(
        symbol=symbol,
        side=side,
        qty=qty,
        entry_price=entry,
        tp_price=take_profit,
        sl_trigger_price=sl_trigger,
        sl_limit_price=sl_limit,
    )

    if order_list_id:
        logger.info("OTOCO placed | order_list_id=%d", order_list_id)
        print(
            f"\n✅ OTOCO placed — order_list_id={order_list_id}\n"
            f"   max_loss=${max_loss:.2f} | max_gain=${max_gain:.2f} | RR=1:{rr_ratio:.2f}"
        )
    else:
        logger.error("OTOCO placement failed — see Binance error above")
        print("\n❌ OTOCO placement failed")
        sys.exit(1)


if __name__ == "__main__":
    main()
