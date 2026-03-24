import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.utils.agent_utils import partition_prompt

def test_nesting():
    template = """
# Header
[[[PASS: PARENT]]]
  Parent Text Start
  [[[PASS: CHILD_A]]]
    Child A Content
  [[[/PASS: CHILD_A]]]
  Mid Parent
  [[[PASS: CHILD_B]]]
    Child B Content
  [[[/PASS: CHILD_B]]]
  Parent Text End
[[[/PASS: PARENT]]]
# Footer
"""
    
    print("Testing Nesting: PARENT and CHILD_B active...")
    result = partition_prompt(template, ["PARENT", "CHILD_B"])
    print("--- RESULT ---")
    print(result)
    print("--------------")
    
    # Assertions
    assert "# Header" in result
    assert "Parent Text Start" in result
    assert "Child A Content" not in result  # Should be filtered
    assert "Mid Parent" in result
    assert "Child B Content" in result      # Should be included
    assert "Parent Text End" in result
    assert "# Footer" in result
    print("SUCCESS: Nesting test passed!")

def test_parent_disabled_child_enabled():
    template = """
[[[PASS: PARENT]]]
  Parent Text
  [[[PASS: CHILD]]]
    Child Text
  [[[/PASS: CHILD]]]
[[[/PASS: PARENT]]]
"""
    print("\nTesting: Parent DISABLED, Child ENABLED...")
    # Even if CHILD is active, if its parent isn't, everything should be stripped
    result = partition_prompt(template, ["CHILD"])
    print("--- RESULT ---")
    print(f"'{result}'")
    print("--------------")
    assert result == ""
    print("SUCCESS: Child stripping in inactive parent passed!")

def test_multiple_top_level():
    template = """
[[[PASS: A]]]A-content[[[/PASS: A]]]
[[[PASS: B]]]B-content[[[/PASS: B]]]
[[[PASS: C]]]C-content[[[/PASS: C]]]
"""
    print("\nTesting: Multiple top-level active (A and C)...")
    result = partition_prompt(template, ["A", "C"])
    print("--- RESULT ---")
    print(result)
    print("--------------")
    assert "A-content" in result
    assert "C-content" in result
    assert "B-content" not in result
    print("SUCCESS: Multiple top-level passed!")

if __name__ == "__main__":
    test_nesting()
    test_parent_disabled_child_enabled()
    test_multiple_top_level()
