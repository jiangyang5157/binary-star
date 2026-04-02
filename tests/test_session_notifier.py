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
        """Verifies that audit review notification logic runs (renamed to notify_audit)."""
        # Mock audit data compliant with AuditEmailTemplate
        mock_audit_data = {
            "strategy_session": {
                "observation": {"symbol": self.symbol, "timestamp": "2026-04-02T12:00:00Z"},
                "final_decision": {"opinion": "BULLISH", "confidence_score": 85, "reasoning_chain": "Test rationale"}
            },
            "market_outcome": {
                "tp_sl_result": "TP_HIT",
                "total_price_change_pct": 3.5,
                "max_favorable_runup_pct": 4.1,
                "max_adverse_drawdown_pct": 0.5,
                "trade_execution_metrics": {"actual_hours": 2.5, "mfe_efficiency": "HIGH", "mae_stress_level": "LOW"}
            },
            "audit_findings": {
                "evaluation_score": 92,
                "adversarial_audit": {"shadow_evidence": ["Evidence A", "Evidence B"]},
                "post_mortem": "Execution was clean."
            }
        }
        self.notifier.notify_audit(self.symbol, mock_audit_data, save_local=True)
        
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
