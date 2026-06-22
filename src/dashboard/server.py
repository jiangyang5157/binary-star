"""FastAPI dashboard server for Singularity session visualization."""
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from fastapi import FastAPI, Query
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
from src.dashboard.api.sessions import router as sessions_router
from src.dashboard.api.audits import router as audits_router
from src.dashboard.api.session_run import router as session_run_router
from src.dashboard.api.sniper_run import router as sniper_run_router

app = FastAPI(title="Singularity Dashboard", version="2.0")

static_dir = Path(__file__).parent / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

# Mount data directory so chart images (e.g., data/prod/klines/*.png) are served
data_dir = PROJECT_ROOT / "data"
if data_dir.exists():
    app.mount("/data", StaticFiles(directory=str(data_dir)), name="data")

app.include_router(sessions_router)
app.include_router(audits_router)
app.include_router(session_run_router)
app.include_router(sniper_run_router)

TEMPLATES_DIR = Path(__file__).parent / "templates"


def read_template(name: str) -> str:
    path = TEMPLATES_DIR / name
    return path.read_text() if path.exists() else "<h1>Template missing</h1>"


@app.get("/", response_class=HTMLResponse)
def index(data_root: str = Query("")):
    return read_template("index.html")


@app.get("/active", response_class=HTMLResponse)
def active_view(data_root: str = Query("")):
    return read_template("active.html")


@app.get("/audits/{filename}", response_class=HTMLResponse)
def audit_view(filename: str, data_root: str = Query("")):
    return read_template("audit.html")


@app.get("/sessions/{filename}", response_class=HTMLResponse)
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
    parser.add_argument("--host", default="0.0.0.0",
                        help="Server host (default: 0.0.0.0)")
    args = parser.parse_args()

    # Use env var so uvicorn reload subprocess inherits the value
    os.environ["SINGULARITY_DATA_ROOT"] = args.data_root

    print(f"Dashboard: data_root = {args.data_root}")
    print(f"Dashboard: http://{args.host}:{args.port}")
    uvicorn.run("src.dashboard.server:app", host=args.host, port=args.port, reload=True)


if __name__ == "__main__":
    main()
