"""Shared progress-log helpers used by both the session-run API and the sniper
daemon to build activity entries for the dashboard progress bar."""

# Activity entry types
ACTIVE = "active"
COMPLETE = "complete"
ERROR = "error"

_MAX_ACTIVITIES = 10
_SECONDS_PER_MINUTE = 60


def add_activity_entry(activities: list[dict], activity: str | None, elapsed: int) -> None:
    """Mutate *activities* in-place: promote previous active → complete,
    then append the new entry with an elapsed-time label.

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

    # Elapsed-time label (e.g. "+15s" or "2:03")
    if elapsed < _SECONDS_PER_MINUTE:
        time_str = f"+{elapsed}s"
    else:
        m, s = divmod(elapsed, _SECONDS_PER_MINUTE)
        time_str = f"+{m}:{s:02d}"

    activities.append({
        "time": time_str,
        "type": entry_type,
        "message": activity or "",
    })

    # Keep only the last N entries
    if len(activities) > _MAX_ACTIVITIES:
        del activities[:-_MAX_ACTIVITIES]
