import os
from unittest.mock import patch
from src.utils.path_utils import resolve_project_root

def test_resolve_project_root_with_marker():
    """Verify that resolve_project_root finds the root when a marker is present."""
    with patch("os.path.exists", return_value=True):
        root = resolve_project_root()
        assert os.path.isabs(root)

def test_resolve_project_root_fallback():
    """Verify that resolve_project_root falls back to CWD when no marker is found."""
    with patch("os.path.exists", return_value=False):
        root = resolve_project_root()
        assert root == os.getcwd()
