import pytest
from datetime import datetime, timezone

from src.utils.datetime_utils import format_timestamp_for_filename, parse_iso_to_utc


# ── parse_iso_to_utc ───────────────────────────────────────────────

def test_parse_iso_z_suffix():
    t = parse_iso_to_utc("2026-07-12T14:49:49Z")
    assert t.tzinfo is not None
    assert t.hour == 14
    assert t.minute == 49


def test_parse_iso_offset_converts_to_utc():
    t = parse_iso_to_utc("2026-07-12T14:49:49+08:00")
    assert t.tzinfo is not None
    assert t.hour == 6  # 14:49 +08:00 → 06:49 UTC


def test_parse_iso_naive_tagged_utc():
    """Naive ISO (no timezone) must be tagged UTC, not left naive."""
    t = parse_iso_to_utc("2026-07-12T14:49:49")
    assert t.tzinfo is not None


# ── format_timestamp_for_filename (happy path) ─────────────────────

def test_format_iso_z():
    assert format_timestamp_for_filename("2026-07-12T14:49:49Z") == "20260712_144949"


def test_format_iso_offset():
    assert format_timestamp_for_filename("2026-07-12T14:49:49+00:00") == "20260712_144949"


def test_format_already_compact():
    assert format_timestamp_for_filename("20260712_144949") == "20260712_144949"


# ── format_timestamp_for_filename (fallback path) ──────────────────
# These inputs would fail datetime.fromisoformat on some Python versions
# or have non-standard formats, exercising the fallback logic.

def test_format_fallback_space_separated():
    """Space-separated timestamps must still produce compact format."""
    assert format_timestamp_for_filename("2026-07-12 14:49:49") == "20260712_144949"


def test_format_fallback_space_separated_with_z():
    assert format_timestamp_for_filename("2026-07-12 14:49:49Z") == "20260712_144949"


def test_format_fallback_garbage_preserved():
    """Non-timestamp strings should not crash; output is best-effort."""
    result = format_timestamp_for_filename("not_a_timestamp")
    assert isinstance(result, str)
    assert len(result) > 0


def test_format_fallback_numeric_extraction():
    """If the string contains 14+ digits, extract them as YYYYMMDD_HHMMSS."""
    # Simulate a malformed but digit-rich input
    result = format_timestamp_for_filename("2026/07/12-14:49:49")
    assert result == "20260712_144949"


# ── Round-trip consistency ─────────────────────────────────────────

def test_round_trip_compact_to_iso_and_back():
    """parse followed by format should return the original compact form."""
    from src.dashboard.api.sessions import _parse_session_timestamp
    parsed = _parse_session_timestamp("20260712_144949")
    formatted = format_timestamp_for_filename(parsed.isoformat())
    assert formatted == "20260712_144949"


def test_round_trip_observed_at_to_audit_filename():
    """The observed_at from a real session must produce the correct audit filename."""
    observed_at = "2026-07-12T14:49:49Z"
    compact = format_timestamp_for_filename(observed_at)
    assert compact == "20260712_144949"


# ── _parse_session_timestamp (smoke tests) ─────────────────────────

def test_parse_session_iso_z():
    from src.dashboard.api.sessions import _parse_session_timestamp
    t = _parse_session_timestamp("2026-07-12T14:49:49Z")
    assert t is not None
    assert t.tzinfo is not None


def test_parse_session_naive_iso():
    """Naive ISO must be tagged UTC, not crash or return naive dt."""
    from src.dashboard.api.sessions import _parse_session_timestamp
    t = _parse_session_timestamp("2026-07-12T14:49:49")
    assert t is not None
    assert t.tzinfo is not None


def test_parse_session_empty_returns_none():
    from src.dashboard.api.sessions import _parse_session_timestamp
    assert _parse_session_timestamp("") is None
    assert _parse_session_timestamp(None) is None
