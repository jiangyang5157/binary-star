import pytest
import yaml
from src.utils.evolution_utils import ConfigPatcher, PromptDistiller

@pytest.fixture
def temp_files(tmp_path):
    """Sets up temporary config and prompt files for testing."""
    config_file = tmp_path / "strategy_config.yaml"
    session_file = tmp_path / "session.md"
    bs_file = tmp_path / "binary_star.md"

    # Initial Config
    initial_config_content = """# Strategy Configuration
analysis_window:
  micro_context:
    time_interval: 5
    threshold: 0.1
  macro_context:
    time_interval: 60
    threshold: 0.8
global_param: 100
"""
    with open(config_file, 'w', encoding='utf-8') as f:
        f.write(initial_config_content)

    # Initial Session Prompt
    session_content = """# ROLE_SESSION
Logic A: Use ATR for buffer.
Logic B: Maintain neutrality.
Logic A: Use ATR for buffer.
"""
    with open(session_file, 'w', encoding='utf-8') as f:
        f.write(session_content)

    # Initial Binary Star Prompt
    bs_content = """# PROTOCOL_BINARY_STAR
Standard adversarial debate protocol.
"""
    with open(bs_file, 'w', encoding='utf-8') as f:
        f.write(bs_content)

    return {
        "config_path": str(config_file),
        "session_path": str(session_file),
        "bs_path": str(bs_file)
    }

def test_config_patcher_precise_path(temp_files):
    """Verifies that ConfigPatcher can target a specific nested path."""
    count = ConfigPatcher.apply_patch(
        temp_files["config_path"], 
        "time_interval", 15, 
        target_path="analysis_window.micro_context"
    )
    assert count == 1
    with open(temp_files["config_path"], 'r', encoding='utf-8') as f:
        data = yaml.safe_load(f)
        assert data["analysis_window"]["micro_context"]["time_interval"] == 15

def test_config_patcher_root_only_strict(temp_files):
    """STRICT: Verifies that empty path ONLY checks root and does NOT recurse."""
    # 'time_interval' exists in nested but NOT root.
    count = ConfigPatcher.apply_patch(
        temp_files["config_path"], 
        "time_interval", 999, 
        target_path=""
    )
    # Should NOT find it, should NOT recurse.
    assert count == 0
    
    with open(temp_files["config_path"], 'r', encoding='utf-8') as f:
        data = yaml.safe_load(f)
        # Verify nested ones are UNCHANGED
        assert data["analysis_window"]["micro_context"]["time_interval"] == 5
        assert "time_interval" not in data # Should not be added to root

def test_config_patcher_root_match(temp_files):
    """Verifies success if key IS in root."""
    count = ConfigPatcher.apply_patch(temp_files["config_path"], "global_param", 200, target_path="")
    assert count == 1
    with open(temp_files["config_path"], 'r', encoding='utf-8') as f:
        data = yaml.safe_load(f)
        assert data["global_param"] == 200

def test_prompt_distiller_multi_instance(temp_files):
    """Verifies that PromptDistiller replaces ALL occurrences of the anchor."""
    anchor = "Logic A: Use ATR for buffer."
    replacement = "Evolved Logic"
    count = PromptDistiller.apply_distillation(temp_files["session_path"], anchor, replacement)
    assert count == 2
    with open(temp_files["session_path"], 'r', encoding='utf-8') as f:
        content = f.read()
        assert content.count(replacement) == 2

def test_prompt_distiller_deletion(temp_files):
    """Verifies that an empty replacement physically removes the anchor."""
    anchor = "Logic B: Maintain neutrality."
    replacement = ""
    count = PromptDistiller.apply_distillation(temp_files["session_path"], anchor, replacement)
    assert count == 1
    with open(temp_files["session_path"], 'r', encoding='utf-8') as f:
        content = f.read()
        assert anchor not in content

def test_prompt_distiller_addition(temp_files):
    """Verifies that selecting a line and replacing with (Line + \n + New) adds content."""
    anchor = "# PROTOCOL_BINARY_STAR"
    # Logic: Preserve the header and add a new rule below it
    replacement = anchor + "\n- **NEW_RULE**: Only trade during high volatility."
    count = PromptDistiller.apply_distillation(temp_files["bs_path"], anchor, replacement)
    assert count == 1
    with open(temp_files["bs_path"], 'r', encoding='utf-8') as f:
        content = f.read()
        assert "- **NEW_RULE**" in content
        assert "# PROTOCOL_BINARY_STAR" in content

def test_prompt_distiller_no_match(temp_files):
    """Verifies zero matches return 0."""
    count = PromptDistiller.apply_distillation(temp_files["session_path"], "MISSING", "FOO")
    assert count == 0
