from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from typing import Optional


DEFAULT_DATETIME_FORMAT = "%Y-%m-%d %H:%M:%S"
FILE_TIMESTAMP_FORMAT = "%Y%m%d_%H%M%S"
NZ_ZONE = ZoneInfo("Pacific/Auckland")

def format_timestamp_for_filename(timestamp_str: str) -> str:
    """
    Standardizes a timestamp string to a compact filename-friendly format.
    Example: '2026-03-24 10:30:00Z' -> '20260324_103000'
    """
    try:
        # Normalize: Remove 'Z' and treat as ISO format
        normalized_ts = timestamp_str.replace('Z', '').strip()
        dt_obj = datetime.fromisoformat(normalized_ts)
        return dt_obj.strftime(FILE_TIMESTAMP_FORMAT)
    except (ValueError, TypeError):
        # Fallback for non-ISO or malformed strings
        return timestamp_str.replace(' ', '_').replace(':', '').replace('Z', '').replace('.', '_')

def format_datetime(dt_obj: datetime, format_str: str = DEFAULT_DATETIME_FORMAT) -> str:
    """Formats a datetime object into a string using the specified format."""
    return dt_obj.strftime(format_str)

def convert_utc_to_nz(utc_dt: datetime) -> datetime:
    """Converts a UTC-aware datetime to New Zealand (Auckland) time."""
    if utc_dt.tzinfo is None:
        utc_dt = utc_dt.replace(tzinfo=timezone.utc)
    return utc_dt.astimezone(NZ_ZONE)

def convert_nz_to_utc(nz_dt: datetime) -> datetime:
    """Converts a New Zealand (Auckland) datetime to UTC."""
    if nz_dt.tzinfo is None:
        nz_dt = nz_dt.replace(tzinfo=NZ_ZONE)
    return nz_dt.astimezone(timezone.utc)

def get_current_nz_time() -> datetime:
    """Returns the current local time in New Zealand (Auckland)."""
    return datetime.now(NZ_ZONE)

def get_current_utc_time() -> datetime:
    """Returns the current time in UTC."""
    return datetime.now(timezone.utc)

def parse_iso_string_to_utc(iso_timestamp: str) -> datetime:
    """Parses an ISO-8601 string and returns a UTC-aware datetime."""
    try:
        # Python < 3.11 compatibility: fromisoformat doesn't natively support 'Z'
        normalized_timestamp = iso_timestamp.replace('Z', '+00:00')
        dt_obj = datetime.fromisoformat(normalized_timestamp)
        if dt_obj.tzinfo is None:
            return dt_obj.replace(tzinfo=timezone.utc)
        return dt_obj.astimezone(timezone.utc)
    except (ValueError, TypeError) as e:
        raise ValueError(f"Invalid ISO timestamp format: {iso_timestamp}") from e
