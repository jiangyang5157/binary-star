"""Shared progress-log helpers used by both the session-run API and the sniper
daemon to build activity entries for the dashboard progress bar."""

from datetime import datetime, timezone

# Activity entry types
ACTIVE = "active"
COMPLETE = "complete"
ERROR = "error"

_MAX_ACTIVITIES = 10

STAGES = [
    {"stage": 1, "label": "Data Collection"},
    {"stage": 2, "label": "Prep"},
    {"stage": 3, "label": "Debate"},
    {"stage": 4, "label": "Decision"},
    {"stage": 5, "label": "Archive"},
]


def elapsed_since_iso(iso_str: str) -> int:
    """Seconds elapsed since an ISO-8601 timestamp.

    Returns 0 for empty strings and unparseable timestamps.
    Clamps negative values (clock skew) to 0.
    """
    if not iso_str:
        return 0
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        return max(0, round((datetime.now(timezone.utc) - dt).total_seconds()))
    except Exception:
        return 0


def enrich_progress(progress: dict | None) -> dict | None:
    """Inject stage definitions into a progress dict for frontend rendering.

    Returns the same dict (mutated in-place) for call-site convenience.
    Returns None if progress is None.
    """
    if progress is None:
        return None
    progress["stages"] = STAGES
    return progress


def add_activity_entry(activities: list[dict], activity: str | None, stage: int | None = None) -> None:
    """Mutate *activities* in-place: promote previous active → complete,
    then append the new entry.

    *stage* should be the 1-based stage number (1-5) the activity belongs
    to, so the frontend can group steps under the correct timeline stage.

    Callers should pass a copy of the list if they need the original unchanged.
    """
    # Auto-promote previous active entries to complete — the new activity
    # supersedes them, so they are implicitly done.
    for prev in activities:
        if prev.get("type") == ACTIVE:
            prev["type"] = COMPLETE

    # Determine entry type for the new activity
    entry_type = ACTIVE
    if activity and "done" in activity:
        entry_type = COMPLETE
    elif activity and activity.startswith("Debate") and ":" in activity:
        entry_type = COMPLETE

    entry = {
        "type": entry_type,
        "message": activity or "",
    }
    if stage is not None:
        entry["stage"] = stage
    activities.append(entry)

    # Keep only the last N entries
    if len(activities) > _MAX_ACTIVITIES:
        activities[:] = activities[-_MAX_ACTIVITIES:]
