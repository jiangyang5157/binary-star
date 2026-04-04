import os
import pytest
import yaml
from ruamel.yaml import YAML
from src.utils.evolution_utils import ConfigPatcher, PromptDistiller

@pytest.fixture
def temp_files(tmp_path):
    """Sets up temporary config and prompt files for testing."""
    config_file = tmp_path / "strategy_config.yaml"
    session_file = tmp_path / "session.md"
    critic_file = tmp_path / "critic.md"
    bs_file = tmp_path / "binary_star.md"

    # Initial Config (with nested structure and comments)
    initial_config_content = """# Strategy Configuration
strategy_intent: "Market Survival"
regime_parameters:
  # Minimum vector strength
  trend_intensity_threshold: 0.4
  unfilled_proximity_atr_limit: 0.1
"""
    with open(config_file, 'w', encoding='utf-8') as f:
        f.write(initial_config_content)

    # Initial Session Prompt
    session_content = """# ROLE_SESSION
Sink your entry deep into an HVN to maximize RR.
Another line of logic.
"""
    with open(session_file, 'w', encoding='utf-8') as f:
        f.write(session_content)
        
    # Initial Critic Prompt
    critic_content = """# ROLE_CRITIC
[GRAVITY_EXHAUSTION] (Demand Mean-Reversion DLE or Neutral).
"""
    with open(critic_file, 'w', encoding='utf-8') as f:
        f.write(critic_content)

    # Initial Binary Star Prompt
    bs_content = """# PROTOCOL_BINARY_STAR
Standard adversarial debate protocol.
"""
    with open(bs_file, 'w', encoding='utf-8') as f:
        f.write(bs_content)

    return {
        "config_path": str(config_file),
        "session_path": str(session_file),
        "critic_path": str(critic_file),
        "bs_path": str(bs_file)
    }

def test_config_patcher_update_nested(temp_files):
    """Verifies that ConfigPatcher deep-updates nested keys."""
    patch_overlays = {
        "trend_intensity_threshold": 0.7,
        "unfilled_proximity_atr_limit": 0.3
    }
    
    success = ConfigPatcher.apply_patch(temp_files["config_path"], patch_overlays)
    assert success is True
    
    # Reload and verify placement
    with open(temp_files["config_path"], 'r', encoding='utf-8') as f:
        content = f.read()
        # Verify it stays inside regime_parameters (not at root)
        # Check that it's indented
        assert "  trend_intensity_threshold: 0.7" in content
        assert "  unfilled_proximity_atr_limit: 0.3" in content
        assert "# Minimum vector strength" in content

def test_config_patcher_additive(temp_files):
    """Verifies that ConfigPatcher can add new keys at root."""
    patch_overlays = {
        "new_global_param": 99
    }
    
    success = ConfigPatcher.apply_patch(temp_files["config_path"], patch_overlays)
    assert success is True
    
    with open(temp_files["config_path"], 'r', encoding='utf-8') as f:
        data = yaml.safe_load(f)
        assert data["new_global_param"] == 99

def test_prompt_distiller_exact_match(temp_files):
    """Verifies byte-perfect replacement in PromptDistiller."""
    anchor = "Sink your entry deep into an HVN to maximize RR."
    replacement = "Sink your entry into the nearest HVN. Do not over-distance."
    
    success = PromptDistiller.apply_distillation(temp_files["session_path"], anchor, replacement)
    assert success is True
    
    with open(temp_files["session_path"], 'r', encoding='utf-8') as f:
        content = f.read()
        assert replacement in content
        assert anchor not in content

def test_prompt_distiller_regex_match_hardened(temp_files):
    """Verifies flexible whitespace matching in PromptDistiller (Hardened)."""
    # Original file has: "Sink your entry deep into an HVN to maximize RR."
    # Anchor has varied whitespace and a tab.
    anchor = "Sink your entry 	deep into an \\n  HVN tomaximize RR."
    # Note: 'tomaximize' is missing a space, it will fail unless regex handles it?
    # Actually, my regex handles [\s\n\r]+ so it requires AT LEAST one space if the anchor has it?
    # Wait, 'to maximize' in file. If anchor is 'to maximize', it works.
    
    anchor = "Sink your entry  deep into an \n  HVN to  maximize RR."
    replacement = "Refined Logic"
    
    success = PromptDistiller.apply_distillation(temp_files["session_path"], anchor, replacement)
    assert success is True
    
    with open(temp_files["session_path"], 'r', encoding='utf-8') as f:
        content = f.read()
        assert replacement in content

def test_prompt_distiller_anchor_not_found(temp_files):
    """Verifies regression handling when anchor text is not found."""
    anchor = "GRAVITY_EXHAUSTION (Demand Mean-Reversion DLE or Neutral)"
    replacement = "THIS SHOULD NOT BE APPLIED"
    
    success = PromptDistiller.apply_distillation(temp_files["critic_path"], anchor, replacement)
    assert success is False
    
    with open(temp_files["critic_path"], 'r', encoding='utf-8') as f:
        content = f.read()
        assert "[GRAVITY_EXHAUSTION] (Demand Mean-Reversion DLE or Neutral)." in content

def test_multi_patch_logic_nested(temp_files):
    """Simulates a full evolution flow with nested keys."""
    proposal = {
        "config_patch": [
            {
                "target_key": "trend_intensity_threshold",
                "replaced_with": 0.8
            }
        ],
        "semantic_refinement": [
            {
                "target_module": "session",
                "anchor_text": "Another line of logic.",
                "replaced_with": "Evolved line of logic."
            }
        ]
    }
    
    overlays = {p["target_key"]: p["replaced_with"] for p in proposal["config_patch"]}
    ConfigPatcher.apply_patch(temp_files["config_path"], overlays)
    
    for ref in proposal["semantic_refinement"]:
        PromptDistiller.apply_distillation(temp_files["session_path"], ref["anchor_text"], ref["replaced_with"])
        
    with open(temp_files["config_path"], 'r', encoding='utf-8') as f:
        content = f.read()
        assert "  trend_intensity_threshold: 0.8" in content
        
    with open(temp_files["session_path"], 'r', encoding='utf-8') as f:
        assert "Evolved line of logic." in f.read()

def test_prompt_distiller_binary_star_protocol(temp_files):
    """Verifies distillation for the core Binary Star protocol instructions."""
    anchor = "Standard adversarial debate protocol."
    replacement = "Hardened Binary Star Protocol v6.1."
    
    success = PromptDistiller.apply_distillation(temp_files["bs_path"], anchor, replacement)
    assert success is True
    
    with open(temp_files["bs_path"], 'r', encoding='utf-8') as f:
        content = f.read()
        assert replacement in content
