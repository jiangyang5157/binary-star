import pytest
import os
from unittest.mock import patch, mock_open
from src.utils.agent_utils import load_config, read_prompt_template, apply_prompt_logic_filters

def test_apply_prompt_logic_filters():
    """Verify the 'Sieve' algorithm for filtering prompt templates by PASS blocks."""
    template = (
        "Common Header.\n"
        "[[[PASS: DRAFT]]]Drafting Context[[[/PASS: DRAFT]]]\n"
        "[[[PASS: REVIEW]]]Reviewing Context[[[/PASS: REVIEW]]]\n"
        "Common Footer."
    )
    
    # 1. Test DRAFT pass enabled
    draft_only = apply_prompt_logic_filters(template, ["DRAFT"])
    assert "Drafting Context" in draft_only
    assert "Reviewing Context" not in draft_only
    assert "Common Header" in draft_only
    
    # 2. Test both passes enabled
    both_passes = apply_prompt_logic_filters(template, ["DRAFT", "REVIEW"])
    assert "Drafting Context" in both_passes
    assert "Reviewing Context" in both_passes
    
    # 3. Test nested blocks
    nested = "Root.[[[PASS: A]]]A-start.[[[PASS: B]]]B-content.[[[/PASS: B]]]A-end.[[[/PASS: A]]]"
    # Only A enabled
    only_a = apply_prompt_logic_filters(nested, ["A"])
    assert "A-start" in only_a
    assert "B-content" not in only_a
    # Both A and B enabled
    both_ab = apply_prompt_logic_filters(nested, ["A", "B"])
    assert "B-content" in both_ab

@patch("builtins.open", new_callable=mock_open, read_data="key: value")
@patch("yaml.safe_load", return_value={"key": "value"})
def test_load_config(mock_yaml, mock_file):
    """Verify that load_config reads and parses YAML correctly."""
    config = load_config("test_config.yaml")
    assert config["key"] == "value"
    mock_file.assert_called_once()

@patch("builtins.open", new_callable=mock_open, read_data="Raw Prompt Content")
def test_read_prompt_template(mock_file):
    """Verify that read_prompt_template reads the file content."""
    prompt = read_prompt_template("test_prompt.md")
    assert prompt == "Raw Prompt Content"
    mock_file.assert_called_once()
