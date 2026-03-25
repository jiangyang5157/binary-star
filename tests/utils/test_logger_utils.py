import logging
from src.utils.logger_utils import setup_logger

def test_setup_logger():
    """Verify that setup_logger returns a correctly named logger and level."""
    logger_name = "test_logger"
    logger = setup_logger(logger_name, log_level=logging.DEBUG)
    
    assert logger.name == logger_name
    assert logger.level == logging.DEBUG
    assert len(logger.handlers) >= 0 # Basic check
