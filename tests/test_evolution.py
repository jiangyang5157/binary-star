import os
import json
import yaml
import pytest
from unittest.mock import MagicMock
from src.agent.evolver_agent import EvolverAgent, EvolverConfig
from src.utils.path_utils import resolve_project_root

@pytest.fixture
def mock_paths(tmp_path):
    """Sets up temporary config and prompt files for testing."""
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    config_file = config_dir / "strategy_config.yaml"
    
    prompts_dir = tmp_path / "src" / "agent" / "prompts"
    prompts_dir.mkdir(parents=True)
    session_file = prompts_dir / "session.md"
    critic_file = prompts_dir / "critic.md"
    bs_file = prompts_dir / "binary_star.md"

    # Initial Config (Nested)
    initial_config = {
        "strategy_intent": "Test Intent",
        "regime_parameters": {
            "trend_intensity_threshold": 0.7
        },
        "binary_star": {
            "session": {"role_definition_prompt": "src/agent/prompts/session.md"},
            "critic": {"role_definition_prompt": "src/agent/prompts/critic.md"},
            "system_instruction": "src/agent/prompts/binary_star.md"
        }
    }
    with open(config_file, 'w') as f:
        yaml.dump(initial_config, f)

    # Initial Prompts (Session has multiple occurrences)
    with open(session_file, 'w') as f:
        f.write("# SESSION_LOGIC\nWait for a strong trend confirmation.\nWait for a strong trend confirmation.")
    
    with open(critic_file, 'w') as f:
        f.write("# CRITIC_LOGIC\nVeto all trades with ATR > 2.")

    with open(bs_file, 'w') as f:
        f.write("# PROTOCOL\nBinary Star Protocol")

    return {
        "config_path": str(config_file),
        "session_path": str(session_file),
        "critic_path": str(critic_file),
        "bs_path": str(bs_file),
        "project_root": str(tmp_path)
    }

def test_evolver_patching_flow_hardened(mock_paths, monkeypatch):
    """Verifies precise path targeting and exhaustive prompt replacement."""
    
    # 1. Mock the project root and config loading
    monkeypatch.setattr("src.utils.path_utils.resolve_project_root", lambda: mock_paths["project_root"])
    from src.utils import pipeline_utils
    monkeypatch.setattr(pipeline_utils, "load_config", lambda *args, **kwargs: yaml.safe_load(open(mock_paths["config_path"])))

    # 2. Setup EvolverAgent
    config = EvolverConfig(
        model="gemini-2.0-flash",
        model_temperature=0.0,
        role_prompt_path="mock_path",
        max_tool_iterations=5
    )
    
    agent = EvolverAgent(config, MagicMock(), 30, 3, 2.0, 1, 5)

    # 3. Define Patch Result with target_path and repeated anchor
    mock_evolution_result = {
        "evolution_signature": "evolution_20260404",
        "evolution_type": "PATCH",
        "config_patch": [
            {
                "pathology_tag": "[REGIME_MISALIGNMENT]",
                "target_path": "regime_parameters",
                "target_key": "trend_intensity_threshold",
                "replaced_with": 0.95
            }
        ],
        "semantic_refinement": [
            {
                "target_module": "session",
                "anchor_text": "Wait for a strong trend confirmation.",
                "replaced_with": "Wait for trend_intensity > 0.8"
            }
        ]
    }

    # 4. Apply Patch
    # Note: apply_patch should return True because it modifies files
    success = agent.apply_patch(mock_evolution_result, mock_paths["config_path"], "BTCUSDT")
    assert success is True

    # 5. Verify Nested Config Update
    with open(mock_paths["config_path"], 'r') as f:
        updated_config = yaml.safe_load(f)
    assert updated_config["regime_parameters"]["trend_intensity_threshold"] == 0.95

    # 6. Verify Multi-Instance Prompt Replacement
    with open(mock_paths["session_path"], 'r') as f:
        content = f.read()
        assert content.count("Wait for trend_intensity > 0.8") == 2
        assert "Wait for a strong trend confirmation." not in content

def test_evolver_patching_no_op(mock_paths, monkeypatch):
    """Verifies that no changes are made if anchors don't match."""
    monkeypatch.setattr("src.utils.path_utils.resolve_project_root", lambda: mock_paths["project_root"])
    from src.utils import pipeline_utils
    monkeypatch.setattr(pipeline_utils, "load_config", lambda *args, **kwargs: yaml.safe_load(open(mock_paths["config_path"])))

    agent = EvolverAgent(
        EvolverConfig(model="mock", model_temperature=0.0, role_prompt_path="mock", max_tool_iterations=1), 
        MagicMock(), 1, 1, 1.0, 1, 1
    )
    
    mock_result = {
        "config_patch": [{"target_key": "non_existent_key", "target_path": "wrong_path", "replaced_with": 1}],
        "semantic_refinement": [{"target_module": "session", "anchor_text": "WRONG_ANCHOR", "replaced_with": "FOO"}]
    }
    
    # It should return False because nothing was applied (or it added to root if path was empty, 
    # but here path is 'wrong_path' so navigate_and_update returns 0)
    success = agent.apply_patch(mock_result, mock_paths["config_path"], "BTCUSDT")
    assert success is False
