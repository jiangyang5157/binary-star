import pytest
from unittest.mock import MagicMock, patch
from src.agent.evolver_sandbox import EvolverSandbox

@pytest.fixture
def mock_audit_report():
    return {
        "session": {
            "observation": {
                "symbol": "BTCUSDT",
                "observed_at": "2026-04-04T10:00:00Z"
            },
            "metadata": {
                "config_snapshot": {
                    "regime_parameters": {"trend_intensity_threshold": 0.5},
                    "binary_star": {"model": "gemini-flash-latest"}
                }
            }
        },
        "market_outcome": {
            "tp_sl_result": "SL_HIT",
            "trade_execution_metrics": {"mae_stress_level_pct": 80.0}
        },
        "metadata": {
            "audit_at": "2026-04-04T12:00:00Z"
        }
    }

@patch("src.agent.evolver_sandbox.BinaryStarOrchestrator")
@patch("src.agent.evolver_sandbox.AuditController")
def test_reply_audit_with_patch_memory_isolation(mock_audit_controller_cls, mock_orchestrator_cls, mock_audit_report):
    # Setup
    api_key = "test_key"
    data_root = "data/test"
    config = {"evolver": {"sandbox_mae_significance_threshold": 5.0, "sandbox_mae_improvement_threshold": 5.0}}
    
    sandbox = EvolverSandbox(api_key, data_root, config)
    
    # Define Patches
    config_patch = [{
        "target_key": "trend_intensity_threshold",
        "replaced_with": 0.99,
        "target_path": "regime_parameters"
    }]
    
    # Execute
    sandbox.reply_audit_with_patch(mock_audit_report, config_patch=config_patch)
    
    # Verification 1: Orchestrator was initialized with the PATCHED config
    _, kwargs = mock_orchestrator_cls.call_args
    captured_config = kwargs.get('config_dict')
    
    assert captured_config['regime_parameters']['trend_intensity_threshold'] == 0.99
    
    # Verification 2: The original audit report was NOT polluted (Deep Copy Check)
    original_val = mock_audit_report['session']['metadata']['config_snapshot']['regime_parameters']['trend_intensity_threshold']
    assert original_val == 0.5

@patch("src.agent.evolver_sandbox.BinaryStarOrchestrator")
@patch("src.agent.evolver_sandbox.AuditController")
def test_sandbox_improvement_logic(mock_audit_controller_cls, mock_orchestrator_cls, mock_audit_report):
    # Setup
    config = {
        "evolver": {
            "sandbox_mae_significance_threshold": 5.0,
            "sandbox_mae_improvement_threshold": 5.0
        }
    }
    sandbox = EvolverSandbox("key", "root", config)
    
    # Mock Audit Controller to return a WIN (TP_HIT)
    mock_controller = mock_audit_controller_cls.return_value
    mock_controller.audit_session_data.return_value = {
        "session": {"observation": {"observed_at": "2026-04-04T10:00:00Z"}},
        "market_outcome": {"tp_sl_result": "TP_HIT", "trade_execution_metrics": {"mae_stress_level_pct": 10.0}},
        "metadata": {"audit_at": "2026-04-04T12:00:00Z"} 
    }
    
    # Execute batch validation with 1 report (which was a SL_HIT in mock_audit_report)
    result = sandbox.run_batch_validation([mock_audit_report])
    
    # Verification
    assert result["is_accepted"] is True
    assert len(result["accepted_cases"]) == 1
    assert len(result["rejected_cases"]) == 0

@patch("src.agent.evolver_sandbox.BinaryStarOrchestrator")
@patch("src.agent.evolver_sandbox.AuditController")
def test_sandbox_rejection_logic(mock_audit_controller_cls, mock_orchestrator_cls, mock_audit_report):
    # Setup
    config = {
        "evolver": {
            "sandbox_mae_significance_threshold": 5.0,
            "sandbox_mae_improvement_threshold": 5.0
        }
    }
    sandbox = EvolverSandbox("key", "root", config)
    
    # Mock Audit Controller to return another LOSS (SL_HIT) with no MAE improvement
    mock_controller = mock_audit_controller_cls.return_value
    mock_controller.audit_session_data.return_value = {
        "session": {"observation": {"observed_at": "2026-04-04T10:00:00Z"}},
        "market_outcome": {"tp_sl_result": "SL_HIT", "trade_execution_metrics": {"mae_stress_level_pct": 85.0}},
        "metadata": {"audit_at": "2026-04-04T12:00:00Z"}
    }
    
    # Execute
    result = sandbox.run_batch_validation([mock_audit_report])
    
    # Verification
    assert result["is_accepted"] is False
    assert len(result["accepted_cases"]) == 0
    assert len(result["rejected_cases"]) == 1
