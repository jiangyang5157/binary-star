"""API endpoints for session data."""
import json
from pathlib import Path

from fastapi import APIRouter, Query

router = APIRouter(prefix="/api")


def _resolve_data_root(value: str) -> str:
    """Resolve data_root: query param > env var > default."""
    import os
    return value or os.environ.get("SINGULARITY_DATA_ROOT", "data/prod")


def _find_session_files(data_root: str) -> list[Path]:
    sessions_dir = Path(data_root) / "sessions"
    if not sessions_dir.exists():
        return []
    return sorted(sessions_dir.glob("*_session_*.json"), reverse=True)


def _audit_filename_for_session(session_filename: str) -> str:
    """Derive the expected audit filename from a session filename."""
    return session_filename.replace("_session_", "_audit_")


def _load_audit_enrichment(data_root: str, session_filename: str) -> dict | None:
    """Try to load audit outcome data for a session. Returns None if unavailable."""
    audit_filename = _audit_filename_for_session(session_filename)
    audit_path = Path(data_root) / "audits" / audit_filename
    if not audit_path.exists():
        return None
    try:
        audit_data = json.loads(audit_path.read_text())
        outcome = audit_data.get("market_outcome", {})
        forensics = outcome.get("market_forensics", {})
        metrics = outcome.get("trade_execution_metrics", {})
        verdict = audit_data.get("forensic_verdict", {})

        # Compute P&L
        session = audit_data.get("session", {})
        decision = session.get("final_decision", {})
        opinion = (decision.get("opinion") or "").upper()
        tp_params = decision.get("tactical_parameters", {})
        entry_price = float(tp_params.get("entry") or 0)
        is_filled = outcome.get("is_filled", False)
        tp_sl_result = outcome.get("tp_sl_result", "NEITHER")

        pnl = 0.0
        if is_filled and entry_price > 0:
            exit_price = float(forensics.get("price_at_t1") or entry_price)
            if tp_sl_result == "TP_HIT":
                tp = float(tp_params.get("take_profit") or entry_price)
                pnl = abs(tp - entry_price) / entry_price * 100
            elif tp_sl_result == "SL_HIT":
                sl = float(tp_params.get("stop_loss") or entry_price)
                pnl = -abs(entry_price - sl) / entry_price * 100
            else:
                price_delta = exit_price - entry_price
                if opinion == "BULLISH":
                    pnl = (price_delta / entry_price) * 100
                elif opinion == "BEARISH":
                    pnl = (-price_delta / entry_price) * 100

        return {
            "is_filled": is_filled,
            "tp_sl_result": tp_sl_result,
            "pnl_pct": round(pnl, 2),
            "mfe_pct": forensics.get("max_favorable_runup_pct"),
            "mae_pct": forensics.get("max_adverse_drawdown_pct"),
            "actual_holding_hours": metrics.get("actual_holding_hours"),
            "is_justified_surrender": verdict.get("is_justified_surrender"),
            "is_catastrophic_miss": verdict.get("is_catastrophic_miss"),
            "audit_filename": audit_filename,
        }
    except Exception:
        return None


@router.get("/sessions")
def list_sessions(
    data_root: str = Query(""),
    symbol: str | None = None,
    limit: int = 50,
    enriched: bool = False,
):
    data_root = _resolve_data_root(data_root)
    files = _find_session_files(data_root)
    if symbol:
        files = [f for f in files if symbol.upper() in f.name.upper()]
    results = []
    for f in files[:limit]:
        try:
            data = json.loads(f.read_text())
            decision = data.get("final_decision", {})
            row = {
                "filename": f.name,
                "symbol": data.get("observation", {}).get("symbol", ""),
                "observed_at": data.get("observation", {}).get("observed_at", ""),
                "opinion": decision.get("opinion", "UNKNOWN"),
                "confidence": decision.get("confidence_score"),
                "tactical": decision.get("tactical_parameters", {}),
            }
            if enriched:
                audit = _load_audit_enrichment(data_root, f.name)
                row["audit"] = audit
            results.append(row)
        except Exception:
            results.append({"filename": f.name, "error": "Failed to parse"})
    return {"sessions": results, "total": len(files)}


@router.get("/sessions/{filename}")
def get_session(filename: str, data_root: str = Query("")):
    data_root = _resolve_data_root(data_root)
    path = Path(data_root) / "sessions" / filename
    if not path.exists():
        return {"error": "Not found"}
    return json.loads(path.read_text())
