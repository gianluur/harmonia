"""
backend/main.py

FastAPI application factory.

This file wires everything together — it is intentionally thin.
No business logic lives here. Every route is in a router. Every service
is initialised in the lifespan handler and injected via dependencies.

Startup sequence (lifespan):
  1. Configure structlog (JSON or pretty based on LOG_FORMAT)
  2. Initialise SQLite database and run create_tables()
  3. Start APScheduler (GC worker + yt-dlp auto-updater)
  4. Yield (app is serving)
  5. Shutdown APScheduler
  6. Close database connection

Middleware stack (applied bottom → top, i.e. RequestIDMiddleware runs first):
  RequestIDMiddleware  — generates/reads X-Request-ID, binds to structlog ctx
  CORSMiddleware       — allows the Next.js dev server origin in development

The `app` object at the bottom of this file is what conftest.py imports.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.config import settings
from backend.database import init_db
from backend.middleware import RequestIDMiddleware

# Routers — import here so they are registered on startup
from backend.routers.auth import router as auth_router

# WebSocket handlers
from backend.ws.job import websocket_endpoint as job_websocket
from backend.ws.search import websocket_endpoint as search_websocket   

# Workers — imported for registration; implementations filled in Phase 1/2
# from backend.workers.gc import run_gc_worker
# from backend.workers.ytdlp_updater import run_ytdlp_update

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Logging configuration
# ---------------------------------------------------------------------------


def _configure_logging() -> None:
    """
    Configure structlog with the renderer specified by LOG_FORMAT.
    Called once at startup before any log lines are emitted.

    Production  (LOG_FORMAT=json):   JSONRenderer — one JSON object per line,
                                     compatible with Loki / Datadog / CloudWatch.
    Development (LOG_FORMAT=pretty): ConsoleRenderer with colour coding.
    """
    shared_processors = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
    ]

    if settings.log_format == "json":
        renderer = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer(colors=True)

    structlog.configure(
        processors=[*shared_processors, renderer],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, settings.log_level)
        ),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )

    # Silence noisy third-party loggers at WARNING in production
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("apscheduler").setLevel(logging.WARNING)


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """
    FastAPI lifespan handler — runs startup logic before `yield`,
    shutdown logic after.

    Everything initialised here is torn down cleanly on shutdown,
    even if the server receives SIGTERM mid-request.
    """
    # 1. Logging
    _configure_logging()
    logger.info("harmonia_starting", version="0.1.0", env=settings.log_format)

    # 2. Database
    db = init_db(str(settings.db_path))
    await db.connect()
    await db.create_tables()
    logger.info("database_ready", path=str(settings.db_path))

    # 3. Ensure raw/ and library/ directories exist
    settings.raw_path.mkdir(parents=True, exist_ok=True)
    settings.music_library_path.mkdir(parents=True, exist_ok=True)

    # 4. APScheduler
    scheduler = AsyncIOScheduler()

    # GC worker: every 6 hours (uncomment when backend/workers/gc.py exists)
    # scheduler.add_job(run_gc_worker, "interval", hours=6, id="gc_worker")

    # yt-dlp auto-updater: every 24 hours
    # scheduler.add_job(run_ytdlp_update, "interval", hours=24, id="ytdlp_updater")

    scheduler.start()
    logger.info("scheduler_started")

    yield  # ← app is serving requests

    # Shutdown
    scheduler.shutdown(wait=False)
    await db.close()
    logger.info("harmonia_shutdown")


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------


def create_app() -> FastAPI:
    """
    Application factory. Returns a configured FastAPI instance.
    Called once at module level — the resulting `app` is what uvicorn
    and conftest.py import.
    """
    application = FastAPI(
        title="Harmonia",
        description="Self-hosted music acquisition backend",
        version="0.1.0",
        # Disable the default /docs and /redoc in production if desired
        # docs_url=None, redoc_url=None,
        lifespan=lifespan,
    )

    # ------------------------------------------------------------------
    # Middleware (applied bottom → top)
    # ------------------------------------------------------------------

    # CORS — allow Next.js dev server; tighten in production
    application.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:3000",   # Next.js dev
            "http://127.0.0.1:3000",
        ],
        allow_credentials=True,       # required for httpOnly cookie auth
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID"],
    )

    # Request ID — must be outermost so all log lines carry it
    application.add_middleware(RequestIDMiddleware)

    # ------------------------------------------------------------------
    # Routers
    # ------------------------------------------------------------------

    application.include_router(auth_router)

    # WebSocket endpoints
    application.websocket("/ws/search")(search_websocket)
    application.websocket("/ws/{job_id}")(job_websocket)

    # Uncomment as each router is implemented (Phase 1 → 3):
    from backend.routers.acquire  import router as acquire_router
    from backend.routers.search   import router as search_router
    # from backend.routers.metadata import router as metadata_router
    # from backend.routers.system   import router as system_router
    application.include_router(acquire_router)
    application.include_router(search_router)
    # application.include_router(metadata_router)
    # application.include_router(system_router)

    return application


app = create_app()
