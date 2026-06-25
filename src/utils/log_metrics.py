"""
Minimal observable logging infrastructure. No logic changes — only
output hygiene, colorized console, and structured metrics sidecar.

Design rules:
- Never modify existing logger call sites.
- Metrics collector is a passive observer — hooks into existing log stream.
- Colorized console formatter wraps the same format string.
"""

import json
import logging
import os
import sys
from collections import deque
from datetime import datetime, timezone
from typing import Optional

# ── Constants ────────────────────────────────────────────────────────────────

METRICS_FILE = None  # set via init_metrics()

# ── Colorized Console Formatter ──────────────────────────────────────────────

class ColorFormatter(logging.Formatter):
    """Terminal-only: wraps the standard format with ANSI color codes."""

    COLORS = {
        logging.DEBUG:    "\033[90m",     # grey
        logging.INFO:     "\033[36m",     # cyan
        logging.WARNING:  "\033[93m",     # yellow
        logging.ERROR:    "\033[91m",     # red
        logging.CRITICAL: "\033[91;1m",   # bold red
    }
    RESET = "\033[0m"
    LEVEL_SHORT = {  # compact level labels
        logging.DEBUG:    "DBG",
        logging.INFO:     "INF",
        logging.WARNING:  "WRN",
        logging.ERROR:    "ERR",
        logging.CRITICAL: "CRT",
    }

    def __init__(self, fmt: str = "%(asctime)s [%(shortlevel)s] %(name)s | %(message)s",
                 datefmt: str = "%H:%M:%S"):
        super().__init__(fmt=fmt, datefmt=datefmt)

    def format(self, record: logging.LogRecord) -> str:
        record.shortlevel = self.LEVEL_SHORT.get(record.levelno, record.levelname[:3])
        color = self.COLORS.get(record.levelno, "")
        formatted = super().format(record)
        if color and sys.stdout.isatty():
            return f"{color}{formatted}{self.RESET}"
        return formatted


# ── Structured Metrics Sidecar ───────────────────────────────────────────────

class MetricsCollector:
    """
    Passive: call .pulse() after each scout-trigger-guardian cycle.
    Writes one JSON line to <data_root>/metrics.jsonl per pulse.
    Also emits a compact INFO summary every `summary_every` pulses.
    """

    def __init__(self, data_root: str, summary_every: int = 10,
                 max_bytes: int = 10 * 1024 * 1024, backup_count: int = 5):
        self.data_root = data_root
        self.summary_every = summary_every
        self.max_bytes = max_bytes
        self.backup_count = backup_count
        self._count = 0
        self._triggers_since_summary = 0
        self._sessions_since_summary = 0
        self._trades_since_summary = 0
        self._errors_since_summary = 0
        self._warnings_since_summary = 0
        self._pulse_latencies: deque[float] = deque(maxlen=summary_every)

    def _rotate_if_needed(self):
        """Rotate metrics.jsonl if it exceeds max_bytes. Keeps backup_count old files."""
        try:
            if os.path.exists(self.metrics_path):
                if os.path.getsize(self.metrics_path) >= self.max_bytes:
                    for i in range(self.backup_count - 1, 0, -1):
                        src = f"{self.metrics_path}.{i}"
                        dst = f"{self.metrics_path}.{i + 1}"
                        if os.path.exists(src):
                            os.replace(src, dst)
                    bak = f"{self.metrics_path}.1"
                    os.replace(self.metrics_path, bak)
        except Exception:
            pass  # best-effort; never crash the main loop

    @property
    def metrics_path(self) -> str:
        return os.path.join(self.data_root, "metrics.jsonl")

    def pulse(self, *, symbol_states: dict, trigger_fired: bool = False,
              session_result: Optional[dict] = None, errors: int = 0,
              warnings: int = 0, pulse_latency_ms: float = 0.0):
        """Record one pulse cycle. All fields optional — collector does the counting."""
        self._count += 1
        self._pulse_latencies.append(pulse_latency_ms)  # deque(maxlen) auto-drops oldest
        if trigger_fired:
            self._triggers_since_summary += 1
        if session_result:
            self._sessions_since_summary += 1
            if session_result.get("trade_executed"):
                self._trades_since_summary += 1
        self._errors_since_summary += errors
        self._warnings_since_summary += warnings

        # Write JSONL entry (with size-based rotation)
        self._rotate_if_needed()
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "pulse": self._count,
            "latency_ms": round(pulse_latency_ms, 1),
            "symbols": {
                sym: {"state": s.get("state", "?"), "position": s.get("position", False)}
                for sym, s in symbol_states.items()
            },
            "trigger": trigger_fired,
            "session": bool(session_result),
            "trade": bool(session_result and session_result.get("trade_executed")),
            "errors": errors,
            "warnings": warnings,
        }
        try:
            with open(self.metrics_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception:
            pass  # metrics are best-effort; never crash the main loop

        # Periodic summary
        if self._count % self.summary_every == 0 and self._pulse_latencies:
            avg_lat = sum(self._pulse_latencies) / len(self._pulse_latencies)
            logger = logging.getLogger("Metrics")
            logger.info(
                f"Pulse #{self._count} | "
                f"avg_lat={avg_lat:.0f}ms | "
                f"triggers={self._triggers_since_summary} | "
                f"sessions={self._sessions_since_summary} | "
                f"trades={self._trades_since_summary} | "
                f"errors={self._errors_since_summary} | "
                f"warnings={self._warnings_since_summary}"
            )
            self._triggers_since_summary = 0
            self._sessions_since_summary = 0
            self._trades_since_summary = 0
            self._errors_since_summary = 0
            self._warnings_since_summary = 0


_collector: Optional[MetricsCollector] = None


def init_metrics(data_root: str, summary_every: int = 10,
                 max_bytes: int = 10 * 1024 * 1024, backup_count: int = 5) -> MetricsCollector:
    """Initialize the global metrics collector. Call once at daemon startup."""
    global _collector
    _collector = MetricsCollector(data_root, summary_every, max_bytes, backup_count)
    return _collector


def get_metrics() -> Optional[MetricsCollector]:
    """Get the global metrics collector, or None if not initialized."""
    return _collector
