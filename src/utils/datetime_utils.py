from datetime import datetime, timezone
from zoneinfo import ZoneInfo

DEFAULT_DATETIME_FORMAT = "%Y-%m-%d %H:%M:%S"
FILE_TIMESTAMP_FORMAT = "%Y%m%d_%H%M%S"
NZ_ZONE = ZoneInfo("Pacific/Auckland")

def format_timestamp_for_filename(timestamp_str: str) -> str:
    """
    Standardizes a timestamp string to a compact filename-friendly format.
    Example: '2026-03-24 10:30:00Z' -> '20260324_103000'
    """
    try:
        # Normalize: Remove 'Z' and treat as ISO format.
        # Note: fromisoformat on a string without timezone offset produces a naive
        # datetime, which is intentional — we only need strftime output for a filename,
        # so the absolute UTC instant is irrelevant.
        normalized_ts = timestamp_str.strip()
        if normalized_ts.endswith('Z'):
            normalized_ts = normalized_ts[:-1] + '+00:00'
        dt_obj = datetime.fromisoformat(normalized_ts)
        if dt_obj.tzinfo is None:
            dt_obj = dt_obj.replace(tzinfo=timezone.utc)
        return dt_obj.astimezone(timezone.utc).strftime(FILE_TIMESTAMP_FORMAT)
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

def to_iso_zulu(dt_obj: datetime) -> str:
    """Returns a clean ISO-8601 string with 'Z' suffix (Zulu time).
    Strips microseconds for terminal consistency.
    """
    if dt_obj.tzinfo is None:
        dt_obj = dt_obj.replace(tzinfo=timezone.utc)
    # Strip microseconds (.%f) for a cleaner "Audit-Grade" look
    return dt_obj.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

def to_html_display(ts_str: str) -> str:
    """
    Converts any timestamp string to a dual UTC/Local format for HTML reports.
    Format: 2026-03-08 13:00:00Z (2026-03-08 21:00:00 GMT+12)
    """
    if not ts_str:
        return "N/A"
    
    try:
        from src.utils.datetime_utils import parse_iso_to_utc
        
        # 1. Parse to UTC
        if "_" in ts_str and "-" not in ts_str:
            dt_utc = datetime.strptime(ts_str, "%Y%m%d_%H%M%S").replace(tzinfo=timezone.utc)
        else:
            dt_utc = parse_iso_to_utc(ts_str)
            
        # 2. Format UTC Part
        utc_part = dt_utc.strftime("%Y-%m-%d %H:%M:%S") + "Z"
        
        # 3. Format Local Part (Server/System Timezone) as GMT±HH:MM
        local_dt = dt_utc.astimezone()
        offset = local_dt.utcoffset()
        total_seconds = int(offset.total_seconds())
        hours = total_seconds // 3600
        minutes = abs(total_seconds) % 3600 // 60
        tz_str = f"GMT{hours:+d}" + (f":{minutes:02d}" if minutes else "")
        local_part = local_dt.strftime("%Y-%m-%d %H:%M:%S") + " " + tz_str
        
        return f"{utc_part} ({local_part})"
    except Exception as e:
        logger = __import__('logging').getLogger(__name__)
        logger.warning("to_html_display failed | ts=%s | error=%s", ts_str, e)
        return ts_str

def to_compact_timestamp(dt_obj: datetime) -> str:
    """Returns a filename-friendly compact timestamp (YYYYMMDD_HHMMSS)."""
    if dt_obj.tzinfo is None:
        dt_obj = dt_obj.replace(tzinfo=timezone.utc)
    return dt_obj.astimezone(timezone.utc).strftime(FILE_TIMESTAMP_FORMAT)

def get_interval_seconds(interval: str) -> int:
    """
    Converts a Binance interval string (e.g., '1h', '15m', '1d') to seconds.
    """
    unit = interval[-1]
    try:
        value = int(interval[:-1])
    except ValueError:
        return 60 # Default to 1m if malformed
        
    mapping = {
        'm': 60,
        'h': 3600,
        'd': 86400,
        'w': 604800,
        'M': 2592000
    }
    return value * mapping.get(unit, 60)

def get_interval_minutes(interval: str) -> int:
    """
    Converts a Binance interval string (e.g., '1h', '15m', '1d') to integer minutes.
    """
    return get_interval_seconds(interval) // 60

def get_interval_hours(interval: str) -> float:
    """
    Converts a Binance interval string to float hours.
    """
    return get_interval_seconds(interval) / 3600.0

# Aliases for backward compatibility
get_utc_now = get_current_utc_time
sanitize_timestamp = format_timestamp_for_filename


def parse_flexible_date(date_str: str) -> datetime:
    """Parse flexible date strings into timezone-aware UTC datetimes.

    Supported formats:
        - ``"now"`` — current UTC time
        - ``"T-30d"`` / ``"T-12h"`` — relative time offset (days or hours)
        - ISO-8601 (e.g. ``"2026-06-01T12:34:00Z"``)
        - ``"YYYY-MM-DD"``, ``"YYYY-MM-DDTHH:MM:SS"``, ``"YYYY-MM-DD HH:MM:SS"``

    Raises:
        ValueError: if the string does not match any supported format.
    """
    from datetime import timedelta

    if date_str.lower() == "now":
        return datetime.now(timezone.utc)

    if date_str.upper().startswith("T-"):
        if len(date_str) < 4:
            raise ValueError(
                f"Invalid date: '{date_str}'. Use T-<N>d or T-<N>h (e.g., T-30d, T-12h)."
            )
        val = int(date_str[2:-1])
        unit = date_str[-1].lower()
        if unit == 'd':
            return datetime.now(timezone.utc) - timedelta(days=val)
        if unit == 'h':
            return datetime.now(timezone.utc) - timedelta(hours=val)
        raise ValueError(
            f"Invalid date: '{date_str}'. Unsupported unit '{unit}'. Use 'd' (days) or 'h' (hours)."
        )

    # Try ISO-8601
    try:
        return parse_iso_to_utc(date_str)
    except Exception:
        pass

    # Try common formats
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(date_str, fmt).replace(tzinfo=timezone.utc)
        except Exception:
            continue

    raise ValueError(f"Invalid date: '{date_str}'")
parse_iso_to_utc = parse_iso_string_to_utc
