import pytest
from src.agent.apply_coach_patch import apply_patches

def test_apply_patches_basic():
    base = "Section 1\nSome content here.\nSection 2\nOld content."
    
    patches = [
        {"action": "ADD", "target_section": "Section 1", "content": "- Added rule"},
        {"action": "REPLACE", "target": "Old content.", "replacement": "New and improved content."},
        {"action": "REMOVE", "target": "Some content here.\n"}
    ]
    
    result = apply_patches(base, patches)
    
    assert "Section 1\n- Added rule" in result
    assert "New and improved content." in result
    assert "Some content here." not in result
    assert "Section 2" in result

def test_apply_patches_no_match():
    base = "Hello World"
    patches = [
        {"action": "REPLACE", "target": "Goodbye", "replacement": "Nothing"},
        {"action": "REMOVE", "target": "Universe"}
    ]
    result = apply_patches(base, patches)
    assert result == base

def test_apply_patches_add_fallback():
    base = "Hello"
    patches = [
        {"action": "ADD", "target_section": "Missing", "content": "World"}
    ]
    result = apply_patches(base, patches)
    assert "Hello\n\nWorld" in result
