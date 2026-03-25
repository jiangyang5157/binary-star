from datetime import datetime, timezone
import pytest
from src.utils.datetime_utils import (
    format_timestamp_for_filename,
    format_datetime,
    convert_utc_to_nz,
    convert_nz_to_utc,
    get_current_nz_time,
    get_current_utc_time,
    parse_iso_string_to_utc
)

def test_format_timestamp_for_filename():
    """Verify that timestamps are correctly formatted for use in filenames."""
    assert format_timestamp_for_filename("2026-03-24 10:30:00Z") == "20260324_103000"
    assert format_timestamp_for_filename("invalid") == "invalid"

def test_format_datetime():
    """Verify standard datetime formatting."""
    dt = datetime(2026, 3, 24, 10, 30, 0)
    assert format_datetime(dt) == "2026-03-24 10:30:00"

def test_timezone_conversions():
    """Verify correct conversions between UTC and NZ (Auckland) time."""
    utc_dt = datetime(2026, 3, 24, 10, 30, 0, tzinfo=timezone.utc)
    nz_dt = convert_utc_to_nz(utc_dt)
    # NZ is UTC+13 in late March (daylight savings)
    assert nz_dt.hour == 23
    
    back_to_utc = convert_nz_to_utc(nz_dt)
    assert back_to_utc == utc_dt

def test_parse_iso_string_to_utc():
    """Verify parsing of ISO-8601 strings into UTC-aware datetimes."""
    iso_str = "2026-03-24T10:30:00Z"
    dt = parse_iso_string_to_utc(iso_str)
    assert dt.tzinfo == timezone.utc
    assert dt.hour == 10

def test_get_current_times():
    """Verify that current time functions return aware datetimes."""
    assert get_current_nz_time().tzinfo is not None
    assert get_current_utc_time().tzinfo == timezone.utc
