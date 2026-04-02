import os
import json
import pytest
from unittest.mock import patch
from export_strategy import main as export_main

def test_strategy_export_logic(tmp_path):
    """
    Verifies that a reviewer report's strategy_session is correctly exported
    to a standardized strategy file with the correct naming convention.
    """
    # 1. Setup Mock Reviewer Report
    symbol = "ETHUSDT"
    timestamp = "2024-03-28T12:00:00Z"
    ts_suffix = "20240328_120000"
    
    mock_strategy = {
        "observation": {
            "symbol": symbol,
            "timestamp": timestamp,
            "data": "important_test_data"
        },
        "final_decision": {"opinion": "BULLISH"}
    }
    
    mock_reviewer_report = {
        "audit_timestamp": "2024-03-28T14:00:00Z",
        "strategy_session": mock_strategy,
        "audit_findings": {"score": 85}
    }
    
    # Create the source file in tmp_path
    reviewer_file = tmp_path / "mock_reviewer.json"
    with open(reviewer_file, "w", encoding="utf-8") as f:
        json.dump(mock_reviewer_report, f)
        
    # 2. Orchestrate Mocks
    # We redirect the file system operations to our tmp_path
    with patch("sys.argv", ["export_strategy.py", "test", "--file", str(reviewer_file)]):
        with patch("src.utils.pipeline_utils.resolve_data_root", return_value="data/test"):
            with patch("export_strategy.resolve_project_root", return_value=str(tmp_path)):
                
                # Pre-create directory to simulate standard project structure
                strat_dir = tmp_path / "data" / "test" / "strategies"
                strat_dir.mkdir(parents=True, exist_ok=True)
                
                # Execute the utility
                export_main()
                
                # 3. Verify Output
                expected_filename = f"{symbol}_strategies_{ts_suffix}.json"
                exported_file = strat_dir / expected_filename
                
                assert exported_file.exists(), f"Exported file {expected_filename} should exist."
                
                with open(exported_file, "r") as f:
                    exported_data = json.load(f)
                    
                # Verification: The exported data must exactly match the strategy_session
                assert exported_data == mock_strategy
                assert exported_data["observation"]["symbol"] == symbol
