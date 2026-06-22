"""API endpoints for active (not-yet-audited) session data."""

import json
from pathlib import Path
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Query

router = APIRouter(prefix="/api")


def _resolve_data_root(value: str) -> str:
    import os
    return value or os.environ.get("SINGULARITY_DATA_ROOT", "data/prod")


# ── Helpers ──────────────────────────────────────────────────────────

def _format_time_remaining(seconds: float) -> str:
    """Human-readable time remaining string."""
    if seconds is None:
        return "—"
    if seconds <= 0:
        prefix = "-" if seconds < 0 else ""
        total_seconds = abs(int(seconds))
        days, rem = divmod(total_seconds, 86400)
        hours, rem = divmod(rem, 3600)
        minutes = rem // 60
        parts = []
        if days > 0:
            parts.append(f"{days}d")
        if hours > 0:
            parts.append(f"{hours}h")
        if minutes > 0 and days == 0:
            parts.append(f"{minutes}m")
        if not parts:
            return "Expired"
        return f"{prefix}{' '.join(parts)}"
    total_seconds = int(seconds)
    days, rem = divmod(total_seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes = rem // 60
    parts = []
    if days > 0:
        parts.append(f"{days}d")
    if hours > 0:
        parts.append(f"{hours}h")
    if minutes > 0 and days == 0:
        parts.append(f"{minutes}m")
    return " ".join(parts) if parts else "<1m"


def _parse_session_timestamp(t0_str: str) -> datetime | None:
    """Parse a session timestamp string to UTC datetime. Returns None on failure."""
    if not t0_str:
        return None
    try:
        if "_" in t0_str and "-" not in t0_str:
            return datetime.strptime(t0_str, "%Y%m%d_%H%M%S").replace(tzinfo=timezone.utc)
        else:
            return datetime.fromisoformat(t0_str.replace("Z", "+00:00"))
    except Exception:
        return None


# ── Endpoints ────────────────────────────────────────────────────────

@router.get("/active")
def list_active(data_root: str = Query(""), include_neutral: bool = Query(True), include_expired: bool = Query(True)):
    """Return sessions with BULLISH/BEARISH/NEUTRAL opinion.

    Optionally include NEUTRAL sessions (no time window) and expired
    BULLISH/BEARISH sessions (past their projected time window).

    Reads session JSONs from {data_root}/sessions/ and excludes
    sessions that already have an audit.
    """
    data_root_dir = _resolve_data_root(data_root)
    sessions_dir = Path(data_root_dir) / "sessions"
    audits_dir = Path(data_root_dir) / "audits"

    if not sessions_dir.exists():
        return {"active": [], "total": 0}

    now = datetime.now(timezone.utc)
    active = []

    for f in sorted(sessions_dir.glob("*.json")):
        try:
            session = json.loads(f.read_text())
        except Exception:
            continue

        obs = session.get("observation", {})
        decision = session.get("final_decision", {})
        opinion = (decision.get("opinion") or "").upper()

        if opinion not in ("BULLISH", "BEARISH"):
            if not (include_neutral and opinion == "NEUTRAL"):
                continue

        t0_str = obs.get("observed_at", "")
        t0 = _parse_session_timestamp(t0_str)
        if t0 is None:
            continue

        tp = decision.get("tactical_parameters", {})

        if opinion == "NEUTRAL":
            # NEUTRAL sessions have no time window — skip expiry check
            holding_hours = 0.0
            waiting_hours = 0.0
            expiry = t0  # dummy value, not used elsewhere
            time_left_seconds = None
        else:
            holding_hours = float(tp.get("projected_holding_hours", 0) or 0)
            waiting_hours = float(tp.get("projected_waiting_hours", 0) or 0)
            expiry = t0 + timedelta(hours=holding_hours + waiting_hours)

            if now >= expiry:
                if not include_expired:
                    continue
                # Expired — still include, time_left_seconds will be negative

            time_left_seconds = (expiry - now).total_seconds()

        # Skip if already audited
        if t0_str:
            from src.utils.datetime_utils import format_timestamp_for_filename
            compact = format_timestamp_for_filename(t0_str)
            audit_name = f"{obs.get('symbol', '')}_audit_{compact}.json"
            if (audits_dir / audit_name).exists():
                continue

        active.append({
            "symbol": obs.get("symbol", ""),
            "observed_at": t0_str,
            "opinion": opinion,
            "confidence": decision.get("confidence_score"),
            "entry": tp.get("entry"),
            "take_profit": tp.get("take_profit"),
            "stop_loss": tp.get("stop_loss"),
            "rr_ratio": tp.get("rr_ratio"),
            "projected_holding_hours": holding_hours,
            "projected_waiting_hours": waiting_hours,
            "expiry_at": expiry.isoformat(),
            "time_remaining": _format_time_remaining(time_left_seconds),
            "time_remaining_seconds": None if time_left_seconds is None else round(time_left_seconds),
        })

    active.sort(key=lambda s: s["observed_at"], reverse=True)
    return {"active": active, "total": len(active)}
