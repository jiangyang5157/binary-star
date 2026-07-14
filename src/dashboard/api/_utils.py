"""Shared utility functions for dashboard API endpoints."""

import os
from fastapi import HTTPException


def _resolve_data_root(value: str) -> str:
    """Resolve data_root: query param > env var > default."""
    resolved = value or os.environ.get("BINARY_STAR_DATA_ROOT", "data/prod")
    if ".." in resolved:
        raise HTTPException(status_code=400, detail="data_root contains path traversal")
    return resolved


def _extract_version(session: dict) -> str:
    """Safely extract project_version from session metadata."""
    return (session.get("metadata") or {}).get("version_control", {}).get("project_version", "")


def _is_pid_alive(pid: int) -> bool:
    """Check whether a process is still running."""
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False
