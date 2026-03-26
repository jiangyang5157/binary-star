import os
import json
import pytest
from unittest.mock import MagicMock, patch
from reviewer import ReviewerOrchestrator

@pytest.fixture
def mock_orchestrator(tmp_path):
    """Creates a ReviewerOrchestrator with mocked dependencies and a temp data_root."""
    data_root = tmp_path / "data"
    data_root.mkdir()
    (data_root / "strategies").mkdir()
    (data_root / "reviewers").mkdir()
    
    # We patch the imports as they appear in reviewer.py
    with patch("reviewer.BinanceFuturesClient"), patch("reviewer.load_config"), patch("reviewer.ReviewerAgent"):
        orchestrator = ReviewerOrchestrator(data_root=str(data_root))
        # Ensure PROJECT_ROOT doesn't interfere with our temp paths
        with patch("reviewer.PROJECT_ROOT", str(tmp_path)):
            yield orchestrator, data_root

def test_reviewer_re_audits_stub(mock_orchestrator):
    """Verify that the reviewer correctly identifies and re-audits a SYSTEM-STUB file."""
    orchestrator, data_root = mock_orchestrator
    
    # 1. Create a strategy with a specific timestamp
    # Note: reviewer.py extracts ts_str from observation timestamp
    strat_file = data_root / "strategies" / "BTCUSDT_strategies_test.json"
    strat_data = {
        "observation": {"symbol": "BTCUSDT", "timestamp": "2024-01-01T00:00:00Z"},
        "final_decision": {"suggested_holding_time_hours": 4}
    }
    with open(strat_file, "w") as f:
        json.dump(strat_data, f)
        
    # 2. Create a matching SYSTEM-STUB review file
    # reviewer.py expects: {symbol}_reviewers_20240101_000000.json
    review_file = data_root / "reviewers" / "BTCUSDT_reviewers_20240101_000000.json"
    stub_data = {
        "market_outcome": {
            "trade_execution_metrics": {
                "is_premature_audit": True,
                "tp_sl_result": "NEITHER"
            }
        }
    }
    with open(review_file, "w") as f:
        json.dump(stub_data, f)
        
    # 3. Patch the inner processor to see if we reach it (meaning we didn't skip)
    with patch.object(orchestrator, "_process_session") as mock_process:
        with patch("reviewer.logger") as mock_logger:
            orchestrator.execute_single(str(strat_file), force=False)
            
            # Check if 'Re-auditing' log was called
            re_audit_called = any("Re-auditing" in str(call) for call in mock_logger.info.call_args_list)
            assert re_audit_called is True
            # Verify we proceeded to processing
            assert mock_process.called

def test_reviewer_skips_finalized_audit(mock_orchestrator):
    """Verify that the reviewer continues to skip finalized (non-stub) audits."""
    orchestrator, data_root = mock_orchestrator
    
    strat_file = data_root / "strategies" / "BTCUSDT_strategies_test.json"
    strat_data = {
        "observation": {"symbol": "BTCUSDT", "timestamp": "2024-01-01T00:00:00Z"},
        "final_decision": {"suggested_holding_time_hours": 4}
    }
    with open(strat_file, "w") as f:
        json.dump(strat_data, f)
        
    # Create a FINALIZED review file
    review_file = data_root / "reviewers" / "BTCUSDT_reviewers_20240101_000000.json"
    full_data = {
        "market_outcome": {
            "trade_execution_metrics": {
                "is_premature_audit": False,
                "tp_sl_result": "TAKE_PROFIT"
            }
        }
    }
    with open(review_file, "w") as f:
        json.dump(full_data, f)
        
    with patch.object(orchestrator, "_process_session") as mock_process:
        with patch("reviewer.logger") as mock_logger:
            orchestrator.execute_single(str(strat_file), force=False)
            
            # Check if 'Skipping' log was called
            skip_called = any("Skipping" in str(call) for call in mock_logger.info.call_args_list)
            assert skip_called is True
            # Verify we did NOT proceed to processing
            assert not mock_process.called
