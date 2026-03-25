import json
import os
import numpy as np
import pytest
from datetime import datetime
from enum import Enum
from src.utils.json_utils import convert_to_json_string, save_to_json_file, load_from_json_file

class MockEnum(Enum):
    TEST = "TEST_VALUE"

def test_enhanced_json_encoder():
    """Verify that EnhancedJSONEncoder handles NumPy, Datetime, and Enum types."""
    data = {
        "float": np.float64(1.23),
        "int": np.int64(10),
        "array": np.array([1, 2, 3]),
        "date": datetime(2026, 3, 24, 10, 30, 0),
        "enum": MockEnum.TEST
    }
    json_str = convert_to_json_string(data)
    parsed = json.loads(json_str)
    
    assert parsed["float"] == 1.23
    assert parsed["int"] == 10
    assert parsed["array"] == [1, 2, 3]
    assert "2026-03-24" in parsed["date"]
    assert parsed["enum"] == "TEST"

def test_save_and_load_json_file(tmp_path):
    """Verify successful saving and loading of JSON files, including dir creation."""
    data = {"hello": "world", "meta": [1, 2, 3]}
    # Test nested directory creation
    file_path = tmp_path / "subdir" / "test.json"
    
    # Save
    success = save_to_json_file(data, str(file_path))
    assert success is True
    assert file_path.exists()
    
    # Load
    loaded_data = load_from_json_file(str(file_path))
    assert loaded_data == data

def test_load_from_json_file_missing():
    """Verify that load_from_json_file returns None for non-existent files."""
    assert load_from_json_file("non_existent_file_123.json") is None

def test_load_from_json_file_corrupted(tmp_path):
    """Verify that load_from_json_file returns None for invalid JSON."""
    file_path = tmp_path / "corrupted.json"
    file_path.write_text("invalid json { content")
    
    assert load_from_json_file(str(file_path)) is None
