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

from fastapi import FastAPI, Query, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from jinja2 import Environment, FileSystemLoader
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp
import time
from src.dashboard.api.sessions import router as sessions_router
from src.dashboard.api.audits import router as audits_router
from src.dashboard.api.session_run import router as session_run_router
from src.dashboard.api.sniper_run import router as sniper_run_router
from src.dashboard.api.backtest import router as backtest_router

app = FastAPI(title="Singularity Dashboard", version="2.0")

# ── Security Headers Middleware ─────────────────────────────────────────
class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Sets security headers on every response."""
    async def dispatch(self, request: Request, call_next: ASGIApp) -> Response:
        resp = await call_next(request)
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["X-Frame-Options"] = "DENY"
        resp.headers["X-XSS-Protection"] = "1; mode=block"
        resp.headers["Referrer-Policy"] = "same-origin"
        # Restrictive CSP — inline styles permitted for dashboard rendering
        resp.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "style-src 'self' 'unsafe-inline'; "
            "script-src 'self' https://cdn.jsdelivr.net; "
            "img-src 'self' data: blob:; "
            "font-src 'self' data:; "
            "connect-src 'self'; "
            "form-action 'self'; "
            "frame-ancestors 'none';"
        )
        return resp

app.add_middleware(SecurityHeadersMiddleware)

# ── Rate Limiter ────────────────────────────────────────────────────────
class RateLimitMiddleware(BaseHTTPMiddleware):
    """Simple in-memory rate limiter: 60 requests/min per client IP.

    Respects X-Forwarded-For for reverse-proxy deployments. Stale client
    entries are pruned on each request to prevent unbounded memory growth.
    """
    def __init__(self, app: ASGIApp, max_requests: int = 60, window_seconds: int = 60):
        super().__init__(app)
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._clients: dict[str, list[float]] = {}
        self._prune_counter: int = 0

    def _resolve_client_ip(self, request: Request) -> str:
        """Extract real client IP, preferring X-Forwarded-For when present."""
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            # Take the leftmost (original client) IP
            return forwarded.split(",")[0].strip()
        return request.client.host if request.client else "unknown"

    async def dispatch(self, request: Request, call_next: ASGIApp) -> Response:
        # Skip rate limiting for static files
        if request.url.path.startswith("/static/"):
            return await call_next(request)

        client_ip = self._resolve_client_ip(request)
        now = time.time()
        window_start = now - self.window_seconds

        if client_ip in self._clients:
            self._clients[client_ip] = [t for t in self._clients[client_ip] if t > window_start]
        else:
            self._clients[client_ip] = []

        if len(self._clients[client_ip]) >= self.max_requests:
            raise HTTPException(status_code=429, detail="Rate limit exceeded — try again shortly")

        self._clients[client_ip].append(now)

        # Periodic prune: purge clients with no recent activity every 1000 requests
        self._prune_counter += 1
        if self._prune_counter >= 1000:
            self._prune_counter = 0
            self._clients = {
                ip: stamps for ip, stamps in self._clients.items()
                if stamps and stamps[-1] > window_start
            }

        return await call_next(request)

app.add_middleware(RateLimitMiddleware, max_requests=60, window_seconds=60)

static_dir = Path(__file__).parent / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

# Mount only chart image subdirectories (not raw session/audit data)
_data_root = os.environ.get("SINGULARITY_DATA_ROOT", "data/prod")
klines_dir = PROJECT_ROOT / _data_root / "klines"
if klines_dir.exists():
    app.mount("/klines", StaticFiles(directory=str(klines_dir)), name="klines")
html_dir = PROJECT_ROOT / _data_root / "html"
if html_dir.exists():
    app.mount("/html", StaticFiles(directory=str(html_dir)), name="html")

app.include_router(sessions_router)
app.include_router(audits_router)
app.include_router(session_run_router)
app.include_router(sniper_run_router)
app.include_router(backtest_router)

TEMPLATES_DIR = Path(__file__).parent / "templates"
_jinja_env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)), autoescape=True)


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


def _server_data_root() -> str:
    """Return the server's effective data root (from env or default)."""
    return os.environ.get("SINGULARITY_DATA_ROOT", "data/prod")


def render_template(name: str, **kwargs) -> HTMLResponse:
    """Render a Jinja2 template with server data_root always injected."""
    template = _jinja_env.get_template(name)
    kwargs.setdefault("data_root", _server_data_root())
    return HTMLResponse(template.render(**kwargs))


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def index():
    return RedirectResponse(url="/performance")


@app.get("/performance", response_class=HTMLResponse, summary="Performance Dashboard", tags=["Pages"])
def performance():
    return render_template("index.html")


@app.get("/live", response_class=HTMLResponse, summary="Live Sessions", tags=["Pages"])
def live_view(user: str = Query(None), data_root: str = Query("")):
    # Reload users.json on every request — edits take effect without restart
    global _users_permissions
    _users_permissions = _load_users()
    permissions = _get_user_permissions(user)
    return render_template("live.html", permissions=permissions)


@app.get("/development", response_class=HTMLResponse, summary="Development Dashboard", tags=["Pages"])
def development_view(user: str = Query(None), data_root: str = Query("")):
    global _users_permissions
    _users_permissions = _load_users()
    permissions = _get_user_permissions(user)
    return render_template("development.html", permissions=permissions)


@app.get("/audits/{filename}", response_class=HTMLResponse, summary="Audit Detail", tags=["Pages"])
def audit_view(filename: str):
    return render_template("audit.html")


@app.get("/sessions/{filename}", response_class=HTMLResponse, summary="Session Detail", tags=["Pages"])
def session_view(filename: str):
    return render_template("session.html")


def main():
    import argparse
    import uvicorn

    parser = argparse.ArgumentParser(description="Singularity Dashboard")
    parser.add_argument("-p", "--data-root", required=True,
                        help="Data directory root (e.g. data/v26.6.28)")
    parser.add_argument("--port", type=int, default=8080,
                        help="Server port (default: 8080)")
    parser.add_argument("--host", default="127.0.0.1",
                        help="Server host (default: 127.0.0.1)")
    args = parser.parse_args()

    # Validate data root exists before starting
    from pathlib import Path
    data_root_path = Path(args.data_root)
    if not data_root_path.is_dir():
        print(f"Error: data root not found: {args.data_root}", file=sys.stderr)
        sys.exit(1)

    # Use env var so uvicorn reload subprocess inherits the value
    os.environ["SINGULARITY_DATA_ROOT"] = args.data_root

    print(f"Dashboard: data_root = {args.data_root}  ({data_root_path.resolve()})")
    print(f"Dashboard: http://{args.host}:{args.port}")
    uvicorn.run("src.dashboard.server:app", host=args.host, port=args.port,
                reload=True, reload_excludes=["data", "*.log", "*.png", "*.json"])


if __name__ == "__main__":
    main()
