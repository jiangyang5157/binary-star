from src.utils.pipeline_utils import deep_merge

def test_deep_merge_simple():
    base = {"a": 1, "b": 2}
    overlay = {"b": 3, "c": 4}
    result = deep_merge(base, overlay)
    assert result == {"a": 1, "b": 3, "c": 4}

def test_deep_merge_nested():
    base = {
        "session": {
            "role": "agent",
            "temp": 0.1
        },
        "system": "online"
    }
    overlay = {
        "session": {
            "temp": 0.5,
            "new_key": "val"
        }
    }
    result = deep_merge(base, overlay)
    
    # Nested keys should coexist
    assert result["session"]["role"] == "agent"
    assert result["session"]["temp"] == 0.5
    assert result["session"]["new_key"] == "val"
    assert result["system"] == "online"

def test_deep_merge_type_conflict():
    # If base has a dict but overlay has a scalar, overlay wins and replaces the dict
    base = {"key": {"sub": 1}}
    overlay = {"key": 2}
    result = deep_merge(base, overlay)
    assert result == {"key": 2}

    # Reverse: If base has a scalar but overlay has a dict, overlay wins
    base = {"key": 1}
    overlay = {"key": {"sub": 2}}
    result = deep_merge(base, overlay)
    assert result == {"key": {"sub": 2}}

def test_deep_merge_empty():
    assert deep_merge({}, {"a": 1}) == {"a": 1}
    assert deep_merge({"a": 1}, {}) == {"a": 1}
    assert deep_merge({}, {}) == {}

def test_deep_merge_immutability():
    # Ensure deep_merge doesn't mutate the original base dictionary (uses copy)
    base = {"a": {"b": 1}}
    overlay = {"a": {"c": 2}}
    result = deep_merge(base, overlay)
    
    assert base == {"a": {"b": 1}} # Original should remain unchanged
    assert result == {"a": {"b": 1, "c": 2}}
