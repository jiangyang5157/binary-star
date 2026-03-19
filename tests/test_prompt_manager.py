import pytest
import os
import json
import shutil
from src.agent.prompt_manager import PromptManager

def test_apply_patches_basic():
    base = "Section 1\nSome content here.\nSection 2\nOld content."
    
    patches = [
        {"action": "ADD", "target_section": "Section 1", "content": "- Added rule"},
        {"action": "REPLACE", "target": "Old content.", "replacement": "New and improved content."},
        {"action": "REMOVE", "target": "Some content here.\n"}
    ]
    
    result = PromptManager.apply_patches(base, patches)
    
    assert "Section 1\n- Added rule" in result
    assert "New and improved content." in result
    assert "Some content here." not in result
    assert "Section 2" in result

def test_get_latest_coach_report(tmp_path):
    coach_dir = tmp_path / "coach"
    coach_dir.mkdir()
    
    symbol = "BTCUSDT"
    # Create two reports with different timestamps
    r1 = coach_dir / f"coach_{symbol}_20260319_100000.json"
    r2 = coach_dir / f"coach_{symbol}_20260319_110000.json"
    
    d1 = {"analysis": {"master_prompt_patch": [{"action": "ADD", "content": "old"}]}}
    d2 = {"analysis": {"master_prompt_patch": [{"action": "ADD", "content": "new"}]}}
    
    r1.write_text(json.dumps(d1))
    r2.write_text(json.dumps(d2))
    
    latest = PromptManager.get_latest_coach_report(symbol, str(coach_dir))
    assert latest["analysis"]["master_prompt_patch"][0]["content"] == "new"

def test_get_patched_prompt_integration(tmp_path):
    # Setup
    agent_dir = tmp_path / "agent"
    agent_dir.mkdir()
    prompt_file = agent_dir / "prompt_trader.txt"
    prompt_file.write_text("BASE PROMPT\n### Rules")
    
    coach_dir = tmp_path / "coach"
    coach_dir.mkdir()
    symbol = "BTCUSDT"
    report_file = coach_dir / f"coach_{symbol}_latest.json"
    patch_data = {
        "analysis": {
            "master_prompt_patch": [
                {"action": "REPLACE", "target": "BASE PROMPT", "replacement": "PATCHED PROMPT"}
            ]
        }
    }
    report_file.write_text(json.dumps(patch_data))
    
    # Execute
    pm = PromptManager()
    result = pm.get_patched_prompt(str(prompt_file), symbol, str(coach_dir))
    
    # Verify
    assert "PATCHED PROMPT" in result
    assert "### Rules" in result
