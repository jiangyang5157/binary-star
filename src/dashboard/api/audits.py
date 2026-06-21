"""API endpoints for audit data and performance metrics."""
import json
from pathlib import Path

from fastapi import APIRouter, Query

router = APIRouter(prefix="/api")


def _resolve_data_root(value: str) -> str:
    """Resolve data_root: query param > env var > default."""
    import os
    return value or os.environ.get("SINGULARITY_DATA_ROOT", "data/prod")


def _find_audit_files(data_root: str, symbol: str | None = None) -> list[Path]:
    """Discover audit JSON files in {data_root}/audits/."""
    audits_dir = Path(data_root) / "audits"
    if not audits_dir.exists():
        return []
    files = sorted(audits_dir.glob("*_audit_*.json"), reverse=True)
    if symbol:
        files = [f for f in files if symbol.upper() in f.name.upper()]
    return files


def _audit_filename_for_session(session_filename: str) -> str:
    """Derive the expected audit filename from a session filename.

    session: BTCUSDT_session_20260621_025751.json
    audit:   BTCUSDT_audit_20260621_025751.json
    """
    return session_filename.replace("_session_", "_audit_")


def _compute_pnl(entry_price: float, opinion: str, tp_sl_result: str,
                 take_profit: float, stop_loss: float,
                 exit_price: float) -> float:
    """Compute realized P&L percentage from audit outcome data.

    Mirrors LedgerVisualizer._normalize_audit_report() logic.
    """
    if entry_price <= 0:
        return 0.0

    if tp_sl_result == "TP_HIT":
        tp = take_profit or entry_price
        return abs(tp - entry_price) / entry_price * 100
    elif tp_sl_result == "SL_HIT":
        sl = stop_loss or entry_price
        return -abs(entry_price - sl) / entry_price * 100
    else:
        # NEITHER: directional delta from entry to exit
        price_delta = exit_price - entry_price
        if opinion == "BULLISH":
            return (price_delta / entry_price) * 100
        elif opinion == "BEARISH":
            return (-price_delta / entry_price) * 100
        return 0.0


@router.get("/performance")
def get_performance(
    data_root: str = Query(""),
    symbol: str | None = None,
):
    data_root = _resolve_data_root(data_root)
    """Aggregated performance metrics from all audit files.

    Returns KPIs and equity curve data for dashboard rendering.
    """
    audit_files = _find_audit_files(data_root, symbol)

    records = []
    for f in audit_files:
        try:
            data = json.loads(f.read_text())
            outcome = data.get("market_outcome", {})
            session = data.get("session", {})
            decision = session.get("final_decision", {})
            opinion = (decision.get("opinion") or "").upper()

            if opinion not in ("BULLISH", "BEARISH", "NEUTRAL"):
                continue

            tp_params = decision.get("tactical_parameters", {})
            entry_price = float(tp_params.get("entry") or 0)
            is_filled = outcome.get("is_filled", False)
            tp_sl_result = outcome.get("tp_sl_result", "NEITHER")
            forensics = outcome.get("market_forensics", {})
            exit_price = float(forensics.get("price_at_t1") or entry_price)

            pnl = _compute_pnl(
                entry_price=entry_price,
                opinion=opinion,
                tp_sl_result=tp_sl_result,
                take_profit=float(tp_params.get("take_profit") or 0),
                stop_loss=float(tp_params.get("stop_loss") or 0),
                exit_price=exit_price,
            )

            records.append({
                "time": session.get("observation", {}).get("observed_at", ""),
                "symbol": session.get("observation", {}).get("symbol", ""),
                "opinion": opinion,
                "confidence": decision.get("confidence_score", 0),
                "is_filled": is_filled,
                "tp_sl_result": tp_sl_result,
                "pnl_pct": round(pnl, 2),
            })
        except Exception:
            continue

    if not records:
        return {
            "net_pnl_pct": 0.0,
            "win_rate": 0.0,
            "max_drawdown_pct": 0.0,
            "calmar_ratio": 0.0,
            "total_sessions": 0,
            "total_audited": 0,
            "total_filled": 0,
            "total_wins": 0,
            "total_losses": 0,
            "avg_confidence": 0.0,
            "equity_curve": [],
        }

    # Sort chronologically for equity curve
    records.sort(key=lambda r: r["time"])

    # Compute KPIs
    filled = [r for r in records if r["is_filled"]]
    wins = [r for r in filled if r["tp_sl_result"] == "TP_HIT"]
    losses = [r for r in filled if r["tp_sl_result"] == "SL_HIT"]

    total_filled = len(filled)
    total_wins = len(wins)
    win_rate = (total_wins / total_filled * 100) if total_filled > 0 else 0.0

    # Cumulative equity curve + drawdown
    eq = 1.0
    peak = 1.0
    max_dd = 0.0
    equity_curve = []

    for r in records:
        if r["is_filled"]:
            eq *= (1 + r["pnl_pct"] / 100.0)
        if eq > peak:
            peak = eq
        dd = (peak - eq) / peak if peak > 0 else 0.0
        max_dd = max(max_dd, dd)
        equity_curve.append({
            "time": r["time"],
            "cumulative_pnl_pct": round((eq - 1) * 100, 2),
        })

    net_pnl_pct = round((eq - 1) * 100, 2)
    max_drawdown_pct = round(max_dd * 100, 2)
    calmar = round(net_pnl_pct / max_drawdown_pct, 2) if max_drawdown_pct > 0 else 0.0

    confidences = [r["confidence"] for r in records if r["confidence"] and r["confidence"] > 0]
    avg_confidence = round(sum(confidences) / len(confidences), 1) if confidences else 0.0

    return {
        "net_pnl_pct": net_pnl_pct,
        "win_rate": round(win_rate, 1),
        "max_drawdown_pct": max_drawdown_pct,
        "calmar_ratio": calmar,
        "total_sessions": len(records),
        "total_audited": len(records),
        "total_filled": total_filled,
        "total_wins": total_wins,
        "total_losses": len(losses),
        "avg_confidence": avg_confidence,
        "equity_curve": equity_curve,
    }


@router.get("/trades")
def get_trades(
    data_root: str = Query(""),
    symbol: str | None = None,
):
    data_root = _resolve_data_root(data_root)
    """Return individual trade records from all audit files for charting.

    Each record includes time, symbol, opinion, confidence, fill status,
    TP/SL result, P&L, and projected holding hours.
    """
    audit_files = _find_audit_files(data_root, symbol)
    trades = []

    for f in audit_files:
        try:
            data = json.loads(f.read_text())
            outcome = data.get("market_outcome", {})
            session = data.get("session", {})
            decision = session.get("final_decision", {})
            opinion = (decision.get("opinion") or "").upper()

            if opinion not in ("BULLISH", "BEARISH", "NEUTRAL"):
                continue

            tp_params = decision.get("tactical_parameters", {})
            entry_price = float(tp_params.get("entry") or 0)
            is_filled = outcome.get("is_filled", False)
            tp_sl_result = outcome.get("tp_sl_result", "NEITHER")
            forensics = outcome.get("market_forensics", {})
            exit_price = float(forensics.get("price_at_t1") or entry_price)

            pnl = _compute_pnl(
                entry_price=entry_price,
                opinion=opinion,
                tp_sl_result=tp_sl_result,
                take_profit=float(tp_params.get("take_profit") or 0),
                stop_loss=float(tp_params.get("stop_loss") or 0),
                exit_price=exit_price,
            )

            trades.append({
                "time": session.get("observation", {}).get("observed_at", ""),
                "symbol": session.get("observation", {}).get("symbol", ""),
                "opinion": opinion,
                "confidence": decision.get("confidence_score", 0),
                "is_filled": is_filled,
                "tp_sl_result": tp_sl_result,
                "pnl_pct": round(pnl, 2),
                "projected_holding_hours": tp_params.get("projected_holding_hours") or 0,
                "session_filename": f.name.replace("_audit_", "_session_"),
            })
        except Exception:
            continue

    trades.sort(key=lambda t: t["time"])
    return {"trades": trades, "total": len(trades)}


@router.get("/audits/{session_filename}")
def get_audit_for_session(
    session_filename: str,
    data_root: str = Query(""),
):
    data_root = _resolve_data_root(data_root)
    """Return the full audit JSON for a given session filename."""
    audit_filename = _audit_filename_for_session(session_filename)
    path = Path(data_root) / "audits" / audit_filename
    if not path.exists():
        return {"error": "Audit not found", "audit_filename": audit_filename}
    try:
        return json.loads(path.read_text())
    except Exception:
        return {"error": "Failed to parse audit file"}
