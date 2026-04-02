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

    # Prevent duplicate handlers if setup_logger is called multiple times for the same name
    if not logger.handlers:
        formatter = logging.Formatter(format_string)
        
        # Console Handler
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)
        
        # File Handler (Optional)
        if log_file:
            try:
                # Ensure the directory exists
                log_dir = os.path.dirname(os.path.abspath(log_file))
                os.makedirs(log_dir, exist_ok=True)
                
                file_handler = logging.FileHandler(log_file, encoding='utf-8')
                file_handler.setFormatter(formatter)
                logger.addHandler(file_handler)
            except Exception as e:
                # Fallback to console if file logging fails, but notify
                print(f"ERROR: Could not setup file logger at {log_file}: {e}", file=sys.stderr)
                
    return logger
