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

    # Initial Config
    initial_config = {
        "strategy_intent": "Test Intent",
        "trend_intensity_threshold": 0.7,
        "binary_star": {
            "session": {"role_definition_prompt": "src/agent/prompts/session.md"},
            "critic": {"role_definition_prompt": "src/agent/prompts/critic.md"},
            "system_instruction": "src/agent/prompts/binary_star.md"
        }
    }
    with open(config_file, 'w') as f:
        yaml.dump(initial_config, f)

    # Initial Prompts
    with open(session_file, 'w') as f:
        f.write("# SESSION_LOGIC\nWait for a strong trend confirmation.")
    
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

def test_evolver_v6_patching_flow(mock_paths, monkeypatch):
    """Verifies that the new array-based schema is correctly applied to files."""
    
    # 1. Mock the project root to our temp directory
    monkeypatch.setattr("src.utils.path_utils.resolve_project_root", lambda: mock_paths["project_root"])
    # We also need to monkeypatch load_config because it defaults to config/strategy_config.yaml
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

    # 3. Define Final V6 Mock Output
    mock_evolution_result = {
        "evolution_signature": "evolution_20260403",
        "evolution_type": "PATCH",
        "config_patch": [
            {
                "pathology_tag": "[REGIME_MISALIGNMENT]",
                "rationale": "Harden trend filter",
                "target_key": "trend_intensity_threshold",
                "replaced_with": 0.85
            }
        ],
        "semantic_refinement": [
            {
                "target_module": "session",
                "pathology_tag": "[SEMANTIC_DRIFT]",
                "rationale": "Precision hardening",
                "anchor_text": "Wait for a strong trend confirmation",
                "replaced_with": "Wait for trend_intensity > {trend_intensity_threshold}"
            },
            {
                "target_module": "critic",
                "pathology_tag": "[PROTOCOL_DISOBEDIENCE]",
                "rationale": "Parametric alignment",
                "anchor_text": "ATR > 2",
                "replaced_with": "ATR > {volatility_extreme_ratio}"
            },
            {
                "target_module": "binary_star",
                "pathology_tag": "[ADVERSARIAL_DEADLOCK]",
                "rationale": "Protocol tightening",
                "anchor_text": "Binary Star Protocol",
                "replaced_with": "Hardened Binary Star Protocol"
            }
        ],
        "sandbox_check_required": True
    }

    # 4. Apply Patch
    success = agent.apply_patch(mock_evolution_result, mock_paths["config_path"], "BTCUSDT")
    assert success is True

    # 5. Verify YAML Changes
    with open(mock_paths["config_path"], 'r') as f:
        updated_config = yaml.safe_load(f)
    assert updated_config["trend_intensity_threshold"] == 0.85

    # 6. Verify Markdown Changes (Session)
    with open(mock_paths["session_path"], 'r') as f:
        updated_session = f.read()
    assert "Wait for trend_intensity > {trend_intensity_threshold}" in updated_session
    assert "Wait for a strong trend confirmation" not in updated_session

    # 7. Verify Markdown Changes (Critic)
    with open(mock_paths["critic_path"], 'r') as f:
        updated_critic = f.read()
    assert "ATR > {volatility_extreme_ratio}" in updated_critic
    assert "ATR > 2" not in updated_critic

    # 8. Verify Markdown Changes (Binary Star)
    with open(mock_paths["bs_path"], 'r') as f:
        updated_bs = f.read()
    assert "Hardened Binary Star Protocol" in updated_bs

if __name__ == "__main__":
    # If run directly, we might need a different setup or just rely on pytest
    pass
