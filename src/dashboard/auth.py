"""Shared auth utilities for the BinaryStar dashboard.

Permission checks for both page templates and API endpoints.
"""
import json
from pathlib import Path

from fastapi import HTTPException, Query

USERS_PATH = Path(__file__).resolve().parent.parent.parent / "config" / "auth" / "users.json"


def _load_users() -> dict[str, set[str]]:
    """Load users.json and resolve effective permissions per user ID."""
    if not USERS_PATH.exists():
        return {}
    try:
        config = json.loads(USERS_PATH.read_text())
    except json.JSONDecodeError:
        return {}

    roles = config.get("roles", {})
    users = config.get("users", {})
    result: dict[str, set[str]] = {}

    anon_role = roles.get("anonymous", {})
    result["__role_anonymous__"] = set(anon_role.get("permissions", []))

    for user_id, user_data in users.items():
        role_key = user_data.get("role", "")
        role = roles.get(role_key, {})
        result[user_id] = set(role.get("permissions", []))

    return result


def get_user_permissions(user_id: str | None) -> set[str]:
    """Resolve permissions for a user ID, falling back to anonymous role."""
    all_perms = _load_users()
    if user_id and user_id in all_perms:
        return all_perms[user_id]
    return all_perms.get("__role_anonymous__", set())


def require_permission(perm: str):
    """FastAPI dependency: reject requests lacking the named permission."""
    def checker(user: str = Query(None)):
        perms = get_user_permissions(user)
        if perm not in perms:
            raise HTTPException(status_code=403, detail=f"Missing permission: {perm}")
    return checker
