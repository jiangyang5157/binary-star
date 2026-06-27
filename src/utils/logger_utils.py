import logging
import sys
import os
import datetime
from logging.handlers import RotatingFileHandler
from typing import Optional


# ── Colorized Console Formatter ──────────────────────────────────────────────

class ColorFormatter(logging.Formatter):
    """Terminal-only: wraps the standard format with ANSI color codes."""

    COLORS = {
        logging.DEBUG:    "\033[90m",
        logging.INFO:     "\033[36m",
        logging.WARNING:  "\033[93m",
        logging.ERROR:    "\033[91m",
        logging.CRITICAL: "\033[91;1m",
    }
    RESET = "\033[0m"
    LEVEL_SHORT = {
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


DEFAULT_LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"

# Compact timestamp format for console: "HH:MM:SS [LVL] name | message"
CONSOLE_FORMAT = "%(asctime)s [%(shortlevel)s] %(name)s | %(message)s"  # noqa — shortlevel injected by ColorFormatter
CONSOLE_DATEFMT = "%H:%M:%S"


# ── Structured File Formatter ─────────────────────────────────────────────────

class StructuredFileFormatter(logging.Formatter):
    """File-only formatter producing compact, scannable log lines.

    Format: ``HH:MM:SS.mmm LVL [tag              ] message``

    - Timestamp is compact (no date — file name carries the date).
    - Logger name is shortened to its last dotted component, padded to 22 chars.
    - Level is abbreviated to 3 chars (INF/WRN/ERR/CRT/DBG).
    - ANSI color codes are NEVER emitted (plain-text safe).
    """

    TAG_WIDTH = 22
    LEVEL_SHORT = {
        logging.DEBUG:    "DBG",
        logging.INFO:     "INF",
        logging.WARNING:  "WRN",
        logging.ERROR:    "ERR",
        logging.CRITICAL: "CRT",
    }

    def formatTime(self, record: logging.LogRecord, datefmt=None) -> str:
        ct = datetime.datetime.fromtimestamp(record.created)
        return f"{ct.hour:02d}:{ct.minute:02d}:{ct.second:02d}.{int(record.msecs):03d}"

    def format(self, record: logging.LogRecord) -> str:
        shortname = record.name.rsplit(".", 1)[-1][:self.TAG_WIDTH]
        level = self.LEVEL_SHORT.get(record.levelno, record.levelname[:3])
        timestamp = self.formatTime(record)
        tag = shortname.ljust(self.TAG_WIDTH)
        return f"{timestamp} {level} [{tag}] {record.getMessage()}"


def setup_logger(
    logger_name: str,
    log_level: int = logging.INFO,
    format_string: str = DEFAULT_LOG_FORMAT,
    log_file: Optional[str] = None,
    propagate: bool = True,
    max_bytes: int = 0,
    backup_count: int = 3,
    console_color: bool = False,
    compact_file: bool = True,
) -> logging.Logger:
    """
    Standardizes logger configuration throughout the project.
    Supports console, plain file, and rotating file persistence.

    Args:
        logger_name:  The identifying name for the logger ('' = root).
        log_level:    The logging threshold (e.g., logging.INFO).
        format_string: The template for log entries.
        log_file:     Optional path to a log file.
        propagate:    Whether to send records to parent loggers (default: True).
        max_bytes:    If > 0, enables RotatingFileHandler at this byte limit per file.
                      0 means plain FileHandler (no rotation).
        backup_count: Number of rotated backup files to keep (default: 3).
        console_color: Whether to emit ANSI color codes on the console (default: False).
        compact_file:  Whether to use StructuredFileFormatter for file output (default: True).

    Returns:
        A configured logging.Logger instance.
    """
    logger = logging.getLogger(logger_name)
    logger.setLevel(log_level)
    logger.propagate = propagate

    # 0. Suppress verbose third-party loggers
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("google_genai").setLevel(logging.WARNING)

    # 1. Console Handler Management: Centralized at root to prevent duplicates
    target_for_console = logging.getLogger("") if propagate else logger
    has_console = any(
        isinstance(h, logging.StreamHandler) and h.stream == sys.stdout
        for h in target_for_console.handlers
    )
    file_formatter = logging.Formatter(format_string)

    if not has_console:
        if console_color:
            console_handler = logging.StreamHandler(sys.stdout)
            console_handler.setFormatter(ColorFormatter())
        else:
            console_handler = logging.StreamHandler(sys.stdout)
            console_handler.setFormatter(file_formatter)
        target_for_console.addHandler(console_handler)

    # 2. File Handler Management
    if log_file:
        try:
            log_file_abs = os.path.abspath(log_file)
            log_dir = os.path.dirname(log_file_abs)
            os.makedirs(log_dir, exist_ok=True)

            # Check if this exact file is already attached (avoids duplicate handlers)
            is_active = any(
                isinstance(h, logging.FileHandler) and h.baseFilename == log_file_abs
                for h in logger.handlers
            )

            if not is_active:
                # Remove stale FileHandlers to prevent resource accumulation
                for h in logger.handlers[:]:
                    if isinstance(h, logging.FileHandler):
                        h.close()
                        logger.removeHandler(h)

                if max_bytes > 0:
                    # Rotating mode: auto-splits log when it exceeds max_bytes
                    file_handler = RotatingFileHandler(
                        log_file_abs,
                        maxBytes=max_bytes,
                        backupCount=backup_count,
                        encoding="utf-8",
                    )
                else:
                    # Standard mode: plain append, no size limit
                    file_handler = logging.FileHandler(log_file_abs, encoding="utf-8")

                file_handler.setFormatter(
                    StructuredFileFormatter() if compact_file else file_formatter
                )
                logger.addHandler(file_handler)

        except Exception as e:
            print(f"ERROR: Could not setup file logger at {log_file}: {e}", file=sys.stderr)

    return logger
