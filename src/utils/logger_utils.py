import logging

def setup_logger(name: str, level=logging.INFO) -> logging.Logger:
    """
    Consistent logger setup for the entire project.
    Configures basic logging and returns a logger instance for the specified name.
    """
    logging.basicConfig(
        level=level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        force=True  # Allow re-configuration if needed in different entry points
    )
    return logging.getLogger(name)
