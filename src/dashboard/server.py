"""FastAPI dashboard server for Singularity session visualization."""
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from fastapi import FastAPI, Query, Depends, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, RedirectResponse
from jinja2 import Environment, FileSystemLoader
from src.dashboard.api.sessions import router as sessions_router
from src.dashboard.api.audits import router as audits_router
from src.dashboard.api.session_run import router as session_run_router
from src.dashboard.api.sniper_run import router as sniper_run_router
from src.dashboard.api.backtest import router as backtest_router

app = FastAPI(title="Singularity Dashboard", version="2.0")

static_dir = Path(__file__).parent / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

# Mount only chart image subdirectories (not raw session/audit data)
klines_dir = PROJECT_ROOT / "data" / os.environ.get("DATA_ROOT", "prod") / "klines"
if klines_dir.exists():
    app.mount("/klines", StaticFiles(directory=str(klines_dir)), name="klines")
html_dir = PROJECT_ROOT / "data" / os.environ.get("DATA_ROOT", "prod") / "html"
if html_dir.exists():
    app.mount("/html", StaticFiles(directory=str(html_dir)), name="html")

app.include_router(sessions_router)
app.include_router(audits_router)
app.include_router(session_run_router)
app.include_router(sniper_run_router)
app.include_router(backtest_router)

TEMPLATES_DIR = Path(__file__).parent / "templates"
_jinja_env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)))


# ── User permissions (loaded once at startup) ────────────────────────────

_users_permissions: dict[str, set[str]] = {}


def _load_users() -> dict[str, set[str]]:
    """Load users.json and resolve effective permissions per user ID.

    Returns a dict mapping user_id → set of permission strings.
    Returns an empty dict if the file is missing or malformed.
    """
    users_path = PROJECT_ROOT / "config" / "auth" / "users.json"
    if not users_path.exists():
        return {}
    try:
        config = json.loads(users_path.read_text())
    except json.JSONDecodeError:
        return {}

    roles = config.get("roles", {})
    users = config.get("users", {})
    result: dict[str, set[str]] = {}

    # Stash anonymous role as fallback for unknown/missing user IDs
    anon_role = roles.get("anonymous", {})
    result["__role_anonymous__"] = set(anon_role.get("permissions", []))

    for user_id, user_data in users.items():
        role_key = user_data.get("role", "")
        role = roles.get(role_key, {})
        perms = set(role.get("permissions", []))
        result[user_id] = perms
    return result


_users_permissions = _load_users()


def _get_user_permissions(user_id: str | None) -> set[str]:
    """Resolve permissions for a user ID.

    Falls back to the "anonymous" role when no user is specified or the
    user ID is unknown.
    """
    if user_id and user_id in _users_permissions:
        return _users_permissions[user_id]
    # Fallback to anonymous role
    return _users_permissions.get("__role_anonymous__", set())


def require_permission(perm: str):
    """FastAPI dependency: reject requests lacking the named permission."""
    def checker(user: str = Query(None)):
        perms = _get_user_permissions(user)
        if perm not in perms:
            raise HTTPException(status_code=403, detail=f"Missing permission: {perm}")
    return checker


def read_template(name: str) -> str:
    path = TEMPLATES_DIR / name
    return path.read_text() if path.exists() else "<h1>Template missing</h1>"


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def index():
    return RedirectResponse(url="/performance")


@app.get("/performance", response_class=HTMLResponse, summary="Performance Dashboard", tags=["Pages"])
def performance():
    return read_template("index.html")


@app.get("/live", response_class=HTMLResponse, summary="Live Sessions", tags=["Pages"])
def live_view(user: str = Query(None), data_root: str = Query("")):
    # Reload users.json on every request — edits take effect without restart
    global _users_permissions
    _users_permissions = _load_users()
    permissions = _get_user_permissions(user)
    template = _jinja_env.get_template("live.html")
    return HTMLResponse(template.render(permissions=permissions))


@app.get("/development", response_class=HTMLResponse, summary="Development Dashboard", tags=["Pages"])
def development_view(user: str = Query(None), data_root: str = Query("")):
    global _users_permissions
    _users_permissions = _load_users()
    permissions = _get_user_permissions(user)
    template = _jinja_env.get_template("development.html")
    return HTMLResponse(template.render(permissions=permissions))


@app.get("/audits/{filename}", response_class=HTMLResponse, summary="Audit Detail", tags=["Pages"])
def audit_view(filename: str, data_root: str = Query("")):
    return read_template("audit.html")


@app.get("/sessions/{filename}", response_class=HTMLResponse, summary="Session Detail", tags=["Pages"])
def session_view(filename: str, data_root: str = Query("")):
    return read_template("session.html")


def main():
    import argparse
    import uvicorn

    parser = argparse.ArgumentParser(description="Singularity Dashboard")
    parser.add_argument("-p", "--data-root", default="data/prod",
                        help="Data directory root (default: data/prod)")
    parser.add_argument("--port", type=int, default=8080,
                        help="Server port (default: 8080)")
    parser.add_argument("--host", default="127.0.0.1",
                        help="Server host (default: 127.0.0.1)")
    args = parser.parse_args()

    # Use env var so uvicorn reload subprocess inherits the value
    os.environ["SINGULARITY_DATA_ROOT"] = args.data_root

    print(f"Dashboard: data_root = {args.data_root}")
    print(f"Dashboard: http://{args.host}:{args.port}")
    uvicorn.run("src.dashboard.server:app", host=args.host, port=args.port,
                reload=True, reload_excludes=["data", "*.log", "*.png", "*.json"])


if __name__ == "__main__":
    main()
