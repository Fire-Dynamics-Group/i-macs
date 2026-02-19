"""FastAPI application factory for the MACS+ live dashboard."""

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from macs_automation.db import ResultsDB

WEB_DIR = Path(__file__).parent
TEMPLATE_DIR = WEB_DIR / "templates"
STATIC_DIR = WEB_DIR / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Open database on startup, close on shutdown."""
    db_path = os.environ.get("MACS_DB_PATH", "results.db")
    app.state.db = ResultsDB(db_path, check_same_thread=False)
    yield
    app.state.db.close()


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(title="MACS+ Automation Dashboard", lifespan=lifespan)

    # Static files
    if STATIC_DIR.exists():
        app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    # Templates
    app.state.templates = Jinja2Templates(directory=TEMPLATE_DIR)

    # Import and include routes
    from macs_automation.web.routes import router
    app.include_router(router)

    return app
