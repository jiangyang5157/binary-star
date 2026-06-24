import time
import threading
from typing import Optional
from src.utils.logger_utils import setup_logger

logger = setup_logger(__name__)

class CongestionController:
    """
    Centralized pacing utility to ensure compliance with API rate limits (RPM).

    This controller tracks the timestamp of the last successful API request and
    enforces a minimum interval between calls. Supporting a zero-interval
    mode for unrestricted accounts.
    """

    def __init__(self, interval_seconds: float):
        """
        Initializes the controller with a fixed pacing interval.

        Args:
            interval_seconds: Minimum seconds between requests. Use 0.0 to disable.
        """
        self.interval = interval_seconds
        self.last_call_time: float = 0.0
        self._lock = threading.Lock()

        if self.interval > 0:
            logger.info(f"CongestionController: Initialized with {self.interval}s pacing (RPM Protection active).")
        else:
            logger.info("CongestionController: Pacing is DISABLED (interval=0).")

    def pace(self, agent_name: str = "Client"):
        """
        Forces the calling thread to sleep if the minimum interval hasn't passed.
        Thread-safe: only one caller paces at a time.
        """
        if self.interval <= 0:
            return

        with self._lock:
            now = time.perf_counter()
            elapsed = now - self.last_call_time

            if elapsed < self.interval:
                wait_time = self.interval - elapsed
                logger.info(f"CongestionController: [{agent_name}] Pacing delay triggered. Waiting {wait_time:.2f}s...")
                time.sleep(wait_time)

            # Update last call time AFTER the potential sleep
            self.last_call_time = time.perf_counter()

    def reset(self):
        """Resets the internal timer."""
        self.last_call_time = 0.0
