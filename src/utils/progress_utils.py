"""Shared progress-log helpers used by both the session-run API and the sniper
daemon to build activity entries for the dashboard progress bar."""

# Activity entry types
ACTIVE = "active"
COMPLETE = "complete"
ERROR = "error"

_MAX_ACTIVITIES = 10


def add_activity_entry(activities: list[dict], activity: str | None) -> None:
    """Mutate *activities* in-place: promote previous active → complete,
    then append the new entry.

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

    activities.append({
        "type": entry_type,
        "message": activity or "",
    })

    # Keep only the last N entries
    if len(activities) > _MAX_ACTIVITIES:
        del activities[:-_MAX_ACTIVITIES]
