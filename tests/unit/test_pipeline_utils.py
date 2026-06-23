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


def test_deep_merge_none_value():
    """None values in overlay should overwrite existing values."""
    result = deep_merge({"a": 1}, {"a": None})
    assert result["a"] is None


def test_deep_merge_deep_nesting():
    """Very deeply nested dicts should be merged correctly (10+ levels)."""
    def deep_nest(levels):
        if levels == 1:
            return {"v": "original"}
        return {"nested": deep_nest(levels - 1)}
    base = deep_nest(10)
    overlay = {"nested": {"nested": {"nested": {"nested": {"nested": {"nested": {"nested": {"nested": {"nested": {"v": "overridden"}}}}}}}}}}
    result = deep_merge(base, overlay)
    # Navigate to the deepest level
    curr = result
    for _ in range(9):
        curr = curr["nested"]
    assert curr["v"] == "overridden"


def test_deep_merge_list_preserved():
    """List values are not deep-merged; overlay list replaces base list."""
    result = deep_merge({"a": [1, 2, 3]}, {"a": [4, 5]})
    assert result["a"] == [4, 5]
