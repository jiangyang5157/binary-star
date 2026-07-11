"""Shared status-file helpers used by both the dashboard API layer and
the subprocess that runs ``run.py session --dashboard``.

The two places that read/write ``.session_run_status.json`` previously had
independent implementations with different atomicity strategies.  Converging
on this shared module prevents drift and gives both paths the safer
tmp+rename atomic write.
"""

import json
from pathlib import Path

SESSION_RUN_STATUS_FILENAME = ".session_run_status.json"


def read_status(data_root: str, filename: str = SESSION_RUN_STATUS_FILENAME) -> dict | None:
    """Read a status JSON file.  Returns None if missing or corrupt."""
    path = Path(data_root) / filename
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except Exception:
        return None


def write_status(data_root: str, status: dict,
                 filename: str = SESSION_RUN_STATUS_FILENAME) -> None:
    """Atomically write a status dict to a JSON file (tmp + rename)."""
    path = Path(data_root) / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(status, default=str, indent=2))
    tmp.replace(path)
