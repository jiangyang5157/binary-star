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

app = FastAPI(title="Singularity Dashboard", version="1.0")

static_dir = Path(__file__).parent / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

app.include_router(sessions_router)

TEMPLATES_DIR = Path(__file__).parent / "templates"


def read_template(name: str) -> str:
    path = TEMPLATES_DIR / name
    return path.read_text() if path.exists() else "<h1>Template missing</h1>"


@app.get("/", response_class=HTMLResponse)
def index(data_root: str = Query("data/prod")):
    return read_template("index.html")


@app.get("/sessions/{filename}", response_class=HTMLResponse)
def session_view(filename: str, data_root: str = Query("data/prod")):
    return read_template("session.html")


@app.get("/ledger", response_class=HTMLResponse)
def ledger(data_root: str = Query("data/prod")):
    return read_template("ledger.html")


def main():
    import uvicorn
    uvicorn.run("src.dashboard.server:app", host="0.0.0.0", port=8080, reload=True)


if __name__ == "__main__":
    main()
