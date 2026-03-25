import logging
import sys
from typing import Optional

DEFAULT_LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"

def setup_logger(
    logger_name: str, 
    log_level: int = logging.INFO, 
    format_string: str = DEFAULT_LOG_FORMAT
) -> logging.Logger:
    """
    Standardizes logger configuration throughout the project.
    
    Args:
        logger_name: The identifying name for the logger.
        log_level: The logging threshold (e.g., logging.DEBUG, logging.INFO).
        format_string: The template for log entries.
        
    Returns:
        A configured logging.Logger instance.
    """
    logging.basicConfig(
        level=log_level,
        format=format_string,
        handlers=[logging.StreamHandler(sys.stdout)],
        force=True  # Overwrite existing configuration if necessary
    )
    logger = logging.getLogger(logger_name)
    logger.setLevel(log_level)
    return logger
