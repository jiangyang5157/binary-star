"""
Single source of truth for Binance HTTP transport settings.

Why this module exists
----------------------
The two clients reach the HTTP layer in different ways, and both defaults are
wrong for a long-running daemon:

  * ``binance.um_futures`` (``UMFutures``) defaults to ``timeout=None`` in
    ``binance/api.py``, which ``requests`` treats as "wait forever".  A stalled
    connection therefore blocks the caller indefinitely — the pulse loop froze
    for good once the host suspended.
  * ``binance.spot`` (``Spot``) hardcodes a class-level ``REQUEST_TIMEOUT``
    that our config never touched.

Both are now driven by ``network.binance.api_timeout_seconds``.
"""
from __future__ import annotations

import os
from typing import Any, Dict

import yaml

from src.utils.logger_utils import setup_logger
from src.utils.path_utils import resolve_project_root

logger = setup_logger(__name__)

DEFAULT_API_TIMEOUT_SECONDS = 30
DEFAULT_RETRY_COUNT = 3


def load_binance_net_config() -> Dict[str, Any]:
    """Return the ``network.binance`` config block ({} when unreadable)."""
    try:
        cfg_path = os.path.join(resolve_project_root(), "config", "global_config.yaml")
        with open(cfg_path, "r") as f:
            cfg = yaml.safe_load(f) or {}
        return cfg.get("network", {}).get("binance", {}) or {}
    except Exception as e:
        logger.error(f"load binance net config failed | error={e}")
        return {}


def get_api_timeout_seconds() -> int:
    """HTTP timeout (seconds) applied to every Binance REST call."""
    raw = load_binance_net_config().get("api_timeout_seconds", DEFAULT_API_TIMEOUT_SECONDS)
    try:
        timeout = int(raw)
    except (TypeError, ValueError):
        logger.error(f"invalid api_timeout_seconds={raw!r} | falling back to {DEFAULT_API_TIMEOUT_SECONDS}")
        return DEFAULT_API_TIMEOUT_SECONDS
    if timeout <= 0:
        logger.error(f"non-positive api_timeout_seconds={timeout} | falling back to {DEFAULT_API_TIMEOUT_SECONDS}")
        return DEFAULT_API_TIMEOUT_SECONDS
    return timeout
