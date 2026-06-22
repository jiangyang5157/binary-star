"""API endpoints for audit data and performance metrics."""
import json
import logging
import concurrent.futures
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



def _compute_pnl(entry_price: float, opinion: str, tp_sl_result: str,
                 take_profit: float, stop_loss: float,
                 exit_price: float) -> float:
    """Compute realized P&L percentage from audit outcome data."""
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
            forensics = outcome.get("market_forensics") or {}
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
            forensics = outcome.get("market_forensics") or {}
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
                "session_filename": f.name,
            })
        except Exception:
            continue

    trades.sort(key=lambda t: t["time"])
    return {"trades": trades, "total": len(trades)}


@router.get("/audits")
def list_audits(
    data_root: str = Query(""),
    symbol: str | None = None,
    limit: int = 50,
):
    """List audit summaries for the dashboard session table."""
    data_root = _resolve_data_root(data_root)
    files = _find_audit_files(data_root, symbol)
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
                    "mfe_pct": forensics.get("max_favorable_runup_pct") if forensics else None,
                    "mae_pct": forensics.get("max_adverse_drawdown_pct") if forensics else None,
                    "actual_holding_hours": metrics.get("actual_holding_hours") if metrics else None,
                    "is_justified_surrender": verdict.get("is_justified_surrender") if verdict else None,
                    "is_catastrophic_miss": verdict.get("is_catastrophic_miss") if verdict else None,
                },
            })
        except Exception:
            results.append({"filename": f.name, "error": "Failed to parse"})
    return {"sessions": results, "total": len(files)}


@router.get("/audits/{filename}")
def get_audit(filename: str, data_root: str = Query("")):
    """Return the full audit JSON for the given audit filename."""
    data_root = _resolve_data_root(data_root)
    path = Path(data_root) / "audits" / filename
    if not path.exists():
        return {"error": "Not found"}
    try:
        return json.loads(path.read_text())
    except Exception:
        return {"error": "Failed to parse"}


@router.post("/audits/run")
def run_audits(data_root: str = Query("")):
    """Trigger forensic audit against all un-audited sessions (all symbols).

    Scans {data_root}/sessions/ for every .json file, skips sessions
    that already have an audit report, and runs forensic analysis on
    the rest.  Returns a summary of what was done.
    """
    data_root = _resolve_data_root(data_root)
    log = logging.getLogger("AuditAPI")

    sessions_dir = Path(data_root) / "sessions"
    if not sessions_dir.exists():
        return {"error": f"Sessions directory not found: {sessions_dir}"}

    session_files = sorted(
        [f for f in sessions_dir.glob("*.json")],
        key=lambda f: f.name,
    )

    if not session_files:
        return {"audited": 0, "skipped": 0, "failed": 0, "total": 0}

    # Build AuditController (one per request — lightweight)
    from src.utils.pipeline_utils import load_combined_config
    from src.analyzer.audit_controller import AuditController

    config = load_combined_config()
    controller = AuditController(config_dict=config, data_root=str(data_root), logger=log)

    log.info("Run-audit triggered: %d session files found in %s", len(session_files), sessions_dir)

    audited = 0
    skipped = 0
    waiting = 0
    empty = 0
    failed = 0

    def _audit_one(session_path: Path) -> str:
        """Audit a single session file. Returns one of audited|skipped|waiting|empty|failed."""
        nonlocal audited, skipped, waiting, empty, failed
        try:
            with open(session_path, "r", encoding="utf-8") as fh:
                session = json.load(fh)
            obs = session.get("observation", {})
            symbol = obs.get("symbol", "UNKNOWN")
            obs_ts = obs.get("observed_at")

            from src.utils.datetime_utils import format_timestamp_for_filename
            ts_compact = format_timestamp_for_filename(obs_ts)

            if controller.is_already_audited(symbol, ts_compact):
                log.debug("Skipped (exists): %s", session_path.name)
                skipped += 1
                return "skipped"

            audit_bundle = controller.run_manual_audit(str(session_path), force=False)
            controller.save_report(audit_bundle)

            outcome = audit_bundle.get("market_outcome", {})
            result_str = outcome.get("tp_sl_result", "N/A")
            log.info("Audited: %s → %s", session_path.name, result_str)
            audited += 1
            return "audited"
        except Exception as e:
            msg = str(e)
            if "SESSION_MATURING" in msg:
                log.info("Waiting (maturing): %s — %s", session_path.name, msg)
                waiting += 1
                return "waiting"
            if "EMPTY_KLINES" in msg:
                log.info("Empty (no data): %s — %s", session_path.name, msg)
                empty += 1
                return "empty"
            log.exception("Audit failed: %s", session_path.name)
            failed += 1
            return "failed"

    # Run audits in parallel with ThreadPoolExecutor
    max_workers = min(4, len(session_files))
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as pool:
        list(pool.map(_audit_one, session_files))

    done = audited + skipped
    log.info("Run-audit complete: done=%d waiting=%d empty=%d failed=%d total=%d",
             done, waiting, empty, failed, len(session_files))

    return {
        "audited": audited,
        "skipped": skipped,
        "waiting": waiting,
        "empty": empty,
        "failed": failed,
        "done": done,
        "total": len(session_files),
    }


@router.get("/config")
def get_config():
    """Return UI-relevant config values (confidence threshold, etc.)."""
    from src.utils.pipeline_utils import load_combined_config
    config = load_combined_config()
    threshold = int(config["llm"]["binary_star"]["session_confidence_threshold"])
    return {"session_confidence_threshold": threshold}
