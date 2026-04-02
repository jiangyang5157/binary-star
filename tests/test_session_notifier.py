import os
import unittest
import sys
from unittest.mock import MagicMock

# Setup paths
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.infrastructure.notifications.email_notifier import SessionNotifier
from tests.mock_factory import MockDataFactory
from src.utils.pipeline_utils import resolve_data_root

class TestSessionNotifier(unittest.TestCase):
    def setUp(self):
        self.data_root = resolve_data_root("test")
        self.notifier = SessionNotifier(data_root=self.data_root)
        self.symbol = "BTCUSDT"

    def test_notify_session_generation(self):
        """Verifies that session notification logic runs and saves local HTML."""
        mock_session = MockDataFactory.create_mock_session_result(self.symbol)
        
        # We don't want to actually send emails in tests, but we want to test HTML generation
        # save_local=True ensures it writes to disk in data/test/previews/
        self.notifier.notify_session(self.symbol, mock_session, save_local=True)
        
        # Verify preview exists
        preview_dir = os.path.join(PROJECT_ROOT, self.data_root, "html")
        self.assertTrue(os.path.exists(preview_dir))

    def test_notify_review_generation(self):
        """Verifies that audit review notification logic runs."""
        # Mock audit report structure
        mock_review = {
            "symbol": self.symbol,
            "audit_status": {"mae_stress_level_pct": 12.5, "stress_tier": "PINPOINT", "tp_sl_result": "TP_HIT"},
            "execution_logic": {"opinion": "BULLISH", "entry": 60000, "exit": 62000, "pnl_pct": 3.3}
        }
        self.notifier.notify_review(self.symbol, mock_review, save_local=True)
        
    def test_notify_ledger_generation(self):
        """Verifies aggregate ledger notification."""
        mock_dataset = [
            {"observation_time": "2026-04-01 10:00:00", "tp_sl_result": "TP_HIT", "pnl": 2.5},
            {"observation_time": "2026-04-01 11:00:00", "tp_sl_result": "SL_HIT", "pnl": -1.2}
        ]
        
        dummy_ledger = os.path.join(PROJECT_ROOT, self.data_root, "dummy_ledger.html")
        os.makedirs(os.path.dirname(dummy_ledger), exist_ok=True)
        with open(dummy_ledger, "w") as f:
            f.write("<html><body>MOCK LEDGER</body></html>")
            
        try:
            self.notifier.notify_ledger(self.symbol, mock_dataset, ledger_path=dummy_ledger)
        finally:
            if os.path.exists(dummy_ledger):
                os.remove(dummy_ledger)

if __name__ == '__main__':
    unittest.main()
