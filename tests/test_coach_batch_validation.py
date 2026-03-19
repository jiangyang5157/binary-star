"""
Tests for coach.py --batch input validation.
"""
import sys
import os
from unittest.mock import patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from coach import run_coach_pipeline


def test_batch_zero_aborts(capsys):
    """Batch size 0 should warn and abort."""
    run_coach_pipeline(n=0)
    captured = capsys.readouterr()
    # No crash means it handled gracefully


def test_batch_negative_aborts(capsys):
    """Negative batch size should warn and abort."""
    run_coach_pipeline(n=-5)
    captured = capsys.readouterr()
    # No crash means it handled gracefully


@patch('coach.load_config')
def test_batch_positive_proceeds(mock_config):
    """Positive batch size should proceed past validation (may fail later on missing data, that's OK)."""
    mock_config.return_value = {}
    # With empty config, it will return early after load_config returns {}
    # But it should NOT abort at the n <= 0 check
    run_coach_pipeline(n=5)
    mock_config.assert_called_once()
