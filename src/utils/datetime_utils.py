from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from typing import Optional


DEFAULT_FORMAT = "%Y-%m-%d %H:%M:%S"
FILE_TIMESTAMP_FORMAT = "%Y%m%d_%H%M%S"
NZ_TIMEZONE = ZoneInfo("Pacific/Auckland")

def sanitize_timestamp(ts_str: str) -> str:
    """
    Standardizes a timestamp string to a compact filename-friendly format (Style A).
    Example: '2026-03-24 10:30:00Z' -> '20260324_103000'
    """
    try:
        # Clean potential quirks (like extra Z after offset)
        clean_ts = ts_str.replace('Z', '').strip()
        dt = datetime.fromisoformat(clean_ts)
        return dt.strftime(FILE_TIMESTAMP_FORMAT)
    except Exception:
        # Fallback to simple replacement if ISO parsing fails
        return ts_str.replace(' ', '_').replace(':', '').replace('Z', '').replace('.', '_')

def format_datetime(dt: datetime, fmt: str = DEFAULT_FORMAT) -> str:
    """Formats a datetime object to a string."""
    return dt.strftime(fmt)

def utc_to_nz(dt: datetime) -> datetime:
    """Converts a UTC datetime to NZ (Auckland) time."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(NZ_TIMEZONE)

def nz_to_utc(dt: datetime) -> datetime:
    """Converts an NZ (Auckland) datetime to UTC."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=NZ_TIMEZONE)
    return dt.astimezone(timezone.utc)

def get_nz_now() -> datetime:
    """Returns the current time in NZ (Auckland)."""
    return datetime.now(NZ_TIMEZONE)

def get_utc_now() -> datetime:
    """Returns the current time in UTC."""
    return datetime.now(timezone.utc)

def parse_iso_to_utc(iso_str: str) -> datetime:
    """Parses an ISO string and ensures it is treated as UTC."""
    dt = datetime.fromisoformat(iso_str)
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
