import logging
import sys
import os
from typing import Optional

DEFAULT_LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"

def setup_logger(
    logger_name: str, 
    log_level: int = logging.INFO, 
    format_string: str = DEFAULT_LOG_FORMAT,
    log_file: Optional[str] = None,
    propagate: bool = True
) -> logging.Logger:
    """
    Standardizes logger configuration throughout the project.
    Now supports both console and optional file persistence.
    
    Args:
        logger_name: The identifying name for the logger.
        log_level: The logging threshold (e.g., logging.DEBUG, logging.INFO).
        format_string: The template for log entries.
        log_file: Optional path to a log file. If provided, logs will be appended there.
        propagate: Whether to send records to parent loggers (default: True).
        
    Returns:
        A configured logging.Logger instance.
    """
    logger = logging.getLogger(logger_name)
    logger.setLevel(log_level)
    logger.propagate = propagate

    # 1. Console Handler Management: Centralized at root to prevent duplicates
    target_for_console = logging.getLogger("") if propagate else logger
    has_console = any(isinstance(h, logging.StreamHandler) and h.stream == sys.stdout for h in target_for_console.handlers)
    formatter = logging.Formatter(format_string)
    
    if not has_console:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(formatter)
        target_for_console.addHandler(console_handler)

    # 2. File Handler Management: Support atomic updates for same logger name
    if log_file:
        try:
            log_file_abs = os.path.abspath(log_file)
            log_dir = os.path.dirname(log_file_abs)
            os.makedirs(log_dir, exist_ok=True)

            # Check if this specific file is already attached
            is_active = any(isinstance(h, logging.FileHandler) and h.baseFilename == log_file_abs for h in logger.handlers)
            
            if not is_active:
                # Remove stale FileHandlers to prevent resource accumulation
                for h in logger.handlers[:]:
                    if isinstance(h, logging.FileHandler):
                        h.close()
                        logger.removeHandler(h)
                
                file_handler = logging.FileHandler(log_file_abs, encoding='utf-8')
                file_handler.setFormatter(formatter)
                logger.addHandler(file_handler)
        except Exception as e:
            print(f"ERROR: Could not setup file logger at {log_file}: {e}", file=sys.stderr)
                
    return logger
