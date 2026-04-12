import json
import yaml
import pytest
from run_patch import main as run_patch_main
from unittest.mock import patch
import sys

@pytest.fixture
def mock_project_env(tmp_path):
    """Sets up a virtual project structure for patching tests."""
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    config_file = config_dir / "strategy_config.yaml"
    
    prompts_dir = tmp_path / "src" / "agent" / "prompts"
    prompts_dir.mkdir(parents=True)
    session_file = prompts_dir / "session.md"
    
    # Original state
    initial_config = {
        "regime_parameters": {"trend_intensity_threshold": 0.7}
    }
    with open(config_file, 'w') as f:
        yaml.dump(initial_config, f)
        
    with open(session_file, 'w') as f:
        f.write("OLD_LOGIC: Wait for trend.")
        
    # Create the proposal JSON
    proposal_data = {
        "config_patch": [
            {
                "target_key": "trend_intensity_threshold",
                "replaced_with": 0.95,
                "target_path": "regime_parameters"
            }
        ],
        "semantic_refinement": [
            {
                "target_module": "session",
                "anchor_text": "OLD_LOGIC: Wait for trend.",
                "replaced_with": "NEW_LOGIC: Execute aggressive entry."
            }
        ]
    }
    proposal_file = tmp_path / "proposal.json"
    with open(proposal_file, 'w') as f:
        json.dump(proposal_data, f)
        
    return {
        "root": str(tmp_path),
        "config": str(config_file),
        "session_md": str(session_file),
        "proposal": str(proposal_file)
    }

def test_run_patch_physical_sync(mock_project_env, monkeypatch):
    """Integration test for run_patch.py main execution."""
    
    # Correct Mock Strategy: Intercept resolution within the target runner module
    monkeypatch.setattr("run_patch.resolve_project_root", lambda: mock_project_env["root"])
    
    # Prepare CLI arguments
    test_args = ["run_patch.py", "--file", mock_project_env["proposal"]]
    
    with patch.object(sys, 'argv', test_args):
        run_patch_main()
        
    # Verify Config Change
    with open(mock_project_env["config"], 'r') as f:
        updated_config = yaml.safe_load(f)
        assert updated_config['regime_parameters']['trend_intensity_threshold'] == 0.95
        
    # Verify Prompt Change
    with open(mock_project_env["session_md"], 'r') as f:
        updated_prompt = f.read()
        assert "NEW_LOGIC: Execute aggressive entry." in updated_prompt
        assert "OLD_LOGIC" not in updated_prompt
