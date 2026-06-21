"""API endpoints — reads audit files as the single source of truth.

Each audit JSON contains: { session, market_outcome, forensic_verdict, metadata }.
The session key holds the full session (decision, debate, observation, etc.).
"""

import json
from pathlib import Path

from fastapi import APIRouter, Query

router = APIRouter(prefix="/api")


def _resolve_data_root(value: str) -> str:
    import os
    return value or os.environ.get("SINGULARITY_DATA_ROOT", "data/prod")


def _find_audit_files(data_root: str) -> list[Path]:
    audit_dir = Path(data_root) / "audits"
    if not audit_dir.exists():
        return []
    return sorted(audit_dir.glob("*_audit_*.json"), reverse=True)



def _compute_pnl(entry_price: float, opinion: str, tp_sl_result: str,
                 take_profit: float, stop_loss: float,
                 exit_price: float) -> float:
    if entry_price <= 0:
        return 0.0
    if tp_sl_result == "TP_HIT":
        tp = take_profit or entry_price
        return abs(tp - entry_price) / entry_price * 100
    elif tp_sl_result == "SL_HIT":
        sl = stop_loss or entry_price
        return -abs(entry_price - sl) / entry_price * 100
    else:
        delta = exit_price - entry_price
        if opinion == "BULLISH":
            return (delta / entry_price) * 100
        elif opinion == "BEARISH":
            return (-delta / entry_price) * 100
        return 0.0


@router.get("/sessions")
def list_sessions(
    data_root: str = Query(""),
    symbol: str | None = None,
    limit: int = 50,
):
    data_root = _resolve_data_root(data_root)
    files = _find_audit_files(data_root)
    if symbol:
        files = [f for f in files if symbol.upper() in f.name.upper()]
    results = []
    for f in files[:limit]:
        try:
            audit = json.loads(f.read_text())
            session = audit.get("session", {})
            decision = session.get("final_decision", {})
            outcome = audit.get("market_outcome", {})
            forensics = outcome.get("market_forensics", {})
            metrics = outcome.get("trade_execution_metrics", {})
            verdict = audit.get("forensic_verdict", {})

            opinion = (decision.get("opinion") or "").upper()
            tp_params = decision.get("tactical_parameters", {})
            entry_price = float(tp_params.get("entry") or 0)
            is_filled = outcome.get("is_filled", False)
            tp_sl_result = outcome.get("tp_sl_result", "NEITHER")

            pnl = 0.0
            if is_filled and entry_price > 0:
                exit_price = float(forensics.get("price_at_t1") or entry_price)
                pnl = _compute_pnl(
                    entry_price=entry_price,
                    opinion=opinion,
                    tp_sl_result=tp_sl_result,
                    take_profit=float(tp_params.get("take_profit") or 0),
                    stop_loss=float(tp_params.get("stop_loss") or 0),
                    exit_price=exit_price,
                )

            results.append({
                "filename": f.name,
                "symbol": session.get("observation", {}).get("symbol", ""),
                "observed_at": session.get("observation", {}).get("observed_at", ""),
                "opinion": opinion or "UNKNOWN",
                "confidence": decision.get("confidence_score"),
                "tactical": tp_params,
                "audit": {
                    "is_filled": is_filled,
                    "tp_sl_result": tp_sl_result,
                    "pnl_pct": round(pnl, 2),
                    "mfe_pct": forensics.get("max_favorable_runup_pct"),
                    "mae_pct": forensics.get("max_adverse_drawdown_pct"),
                    "actual_holding_hours": metrics.get("actual_holding_hours"),
                    "is_justified_surrender": verdict.get("is_justified_surrender"),
                    "is_catastrophic_miss": verdict.get("is_catastrophic_miss"),
                },
            })
        except Exception:
            results.append({"filename": f.name, "error": "Failed to parse"})
    return {"sessions": results, "total": len(files)}


@router.get("/sessions/{filename}")
def get_session(filename: str, data_root: str = Query("")):
    """Return the full audit JSON for the given audit filename."""
    data_root = _resolve_data_root(data_root)
    path = Path(data_root) / "audits" / filename
    if not path.exists():
        return {"error": "Not found"}
    try:
        return json.loads(path.read_text())
    except Exception:
        return {"error": "Failed to parse"}
