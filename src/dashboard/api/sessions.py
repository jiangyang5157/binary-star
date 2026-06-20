"""API endpoints for session data."""
import json
from pathlib import Path

from fastapi import APIRouter, Query

router = APIRouter(prefix="/api")


def _find_session_files(data_root: str) -> list[Path]:
    sessions_dir = Path(data_root) / "sessions"
    if not sessions_dir.exists():
        return []
    return sorted(sessions_dir.glob("*_session_*.json"), reverse=True)


@router.get("/sessions")
def list_sessions(
    data_root: str = Query("data/prod"),
    symbol: str | None = None,
    limit: int = 50,
):
    files = _find_session_files(data_root)
    if symbol:
        files = [f for f in files if symbol.upper() in f.name.upper()]
    results = []
    for f in files[:limit]:
        try:
            data = json.loads(f.read_text())
            decision = data.get("final_decision", {})
            results.append({
                "filename": f.name,
                "symbol": data.get("observation", {}).get("symbol", ""),
                "observed_at": data.get("observation", {}).get("observed_at", ""),
                "opinion": decision.get("opinion", "UNKNOWN"),
                "confidence": decision.get("confidence_score"),
                "tactical": decision.get("tactical_parameters", {}),
            })
        except Exception:
            results.append({"filename": f.name, "error": "Failed to parse"})
    return {"sessions": results, "total": len(files)}


@router.get("/sessions/{filename}")
def get_session(filename: str, data_root: str = Query("data/prod")):
    path = Path(data_root) / "sessions" / filename
    if not path.exists():
        return {"error": "Not found"}
    return json.loads(path.read_text())
