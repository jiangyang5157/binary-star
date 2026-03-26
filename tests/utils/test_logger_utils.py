import os
import logging
import shutil
import pytest
from src.utils.logger_utils import setup_logger

def test_setup_logger_basic():
    """Verify that setup_logger returns a correctly named logger and level."""
    logger_name = "test_logger_basic"
    logger = setup_logger(logger_name, log_level=logging.DEBUG)
    
    assert logger.name == logger_name
    assert logger.level == logging.DEBUG
    # Basic check for propagation prevention
    assert logger.propagate is False

def test_setup_logger_persistence(tmp_path):
    """Verify that setup_logger correctly initializes a file handler and creates directories."""
    logger_name = "test_logger_file"
    log_dir = tmp_path / "logs"
    log_file = log_dir / "test.log"
    
    logger = setup_logger(logger_name, log_file=str(log_file))
    
    # Verify directory was created
    assert log_dir.exists()
    
    # Verify file handler was added
    file_handlers = [h for h in logger.handlers if isinstance(h, logging.FileHandler)]
    assert len(file_handlers) == 1
    assert file_handlers[0].baseFilename == str(log_file.absolute())
    
    # Test logging to file
    test_msg = "Persistence Test Message"
    logger.info(test_msg)
    
    # Close handlers to flush and release file
    for h in logger.handlers:
        h.close()
        
    with open(log_file, "r") as f:
        content = f.read()
        assert test_msg in content

def test_setup_logger_no_propagation():
    """Verify that logger.propagate is False to avoid double logging."""
    logger = setup_logger("no_prop_test")
    assert logger.propagate is False
