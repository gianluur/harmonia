"""
backend/ws/job.py

WebSocket handler for ws/<job_id> — job event fan-out, reconnection state recovery — see Architecture §4.2.1

Responsibilities:
  - Authenticate via JWT cookie, close with code 4001 on invalid JWT
  - Bind request_id from query param to structlog context
  - On connect, send current JobStatus as first message
  - Maintain per‑job connection set for event fan‑out
  - Translate plugin DownloadEvent → WebSocket events
  - Fan‑out tagging_suggestions, tagging_error, library_ready events
  - Reconnection resumes from current job state (same first‑message logic)
  - Log connection/disconnection with job_id and request_id

Thread‑safety: asyncio locks around the connection dict.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from collections import defaultdict
from collections.abc import AsyncGenerator
from typing import Any, cast
from weakref import WeakSet

import structlog
from fastapi import WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

from backend.auth import TokenExpiredError, TokenInvalidError, decode_jwt
from backend.database import AsyncDB, get_db
from backend.schemas import (
    DownloadCompleteEvent,
    DownloadProgressEvent,
    JobErrorEvent,
    JobStatus,
    JobStatusEnum,
    JobWSEvent,
    LibraryReadyEvent,
    TaggingErrorEvent,
    TaggingSuggestionsEvent,
)
from backend.services.job_store import get_job

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Connection management
# ---------------------------------------------------------------------------

# Weak set of active WebSocket connections per job_id.
# When a connection closes (garbage‑collected) it is automatically removed.
_connections: dict[str, WeakSet[WebSocket]] = defaultdict(WeakSet)
# Lock per job_id to avoid race conditions on connection set modifications.
_connection_locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)


async def _add_connection(job_id: str, ws: WebSocket) -> None:
    """Register a WebSocket connection for the given job."""
    async with _connection_locks[job_id]:
        _connections[job_id].add(ws)


async def _remove_connection(job_id: str, ws: WebSocket) -> None:
    """Remove a WebSocket connection from the given job."""
    async with _connection_locks[job_id]:
        _connections[job_id].discard(ws)
        # Clean up empty entries to avoid memory leak
        if not _connections[job_id]:
            _connections.pop(job_id, None)
            _connection_locks.pop(job_id, None)


async def _broadcast_event(job_id: str, event: JobWSEvent) -> None:
    """
    Send a JobWSEvent to every WebSocket connected to this job.

    Silently drops connections that have been closed (e.g., client‑side disconnect).
    Logs any send failure at DEBUG level.
    """
    connections = _connections.get(job_id)
    if not connections:
        return

    log = logger.bind(job_id=job_id, event_type=event.type)
    log.debug("broadcasting_event")

    # Convert to JSON once
    payload = event.model_dump_json(by_alias=True)

    dead: list[WebSocket] = []
    for ws in connections:
        if ws.client_state == WebSocketState.DISCONNECTED:
            dead.append(ws)
            continue
        try:
            await ws.send_text(payload)
        except (WebSocketDisconnect, RuntimeError):
            # Client closed the connection while we were sending
            dead.append(ws)
        except Exception as exc:
            log.debug("broadcast_failed", exc=str(exc))

    # Clean up dead connections
    if dead:
        async with _connection_locks.get(job_id, asyncio.Lock()):
            for ws in dead:
                _connections[job_id].discard(ws)


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------

async def _authenticate_websocket(
    websocket: WebSocket,
    request_id: str,
) -> str | None:
    """
    Validate JWT cookie.

    Returns:
        username on success, None on failure.
        On failure, the connection is already closed with appropriate code.
    """
    # 1. Extract JWT from cookie (same name as HTTP routes)
    token = websocket.cookies.get("harmonia_token")
    if not token:
        logger.warning(
            "websocket_auth_missing_token",
            request_id=request_id,
            path=websocket.url.path,
        )
        await websocket.close(code=4001, reason="Missing JWT cookie")
        return None

    # 2. Decode and verify the token
    try:
        payload = decode_jwt(token)
    except TokenExpiredError:
        logger.warning(
            "websocket_auth_token_expired",
            request_id=request_id,
            path=websocket.url.path,
        )
        await websocket.close(code=4001, reason="JWT expired")
        return None
    except TokenInvalidError:
        logger.warning(
            "websocket_auth_token_invalid",
            request_id=request_id,
            path=websocket.url.path,
        )
        await websocket.close(code=4001, reason="Invalid JWT")
        return None

    username = payload.get("sub")
    return username


# ---------------------------------------------------------------------------
# WebSocket endpoint
# ---------------------------------------------------------------------------

async def websocket_endpoint(websocket: WebSocket, job_id: str) -> None:
    """
    WebSocket handler for `ws/<job_id>`.

    Query parameters:
        request_id — optional UUID v4; if missing, generate one.

    Flow:
        1. Authenticate via JWT cookie → close 4001 on failure.
        2. Bind request_id to structlog context for the lifetime of the connection.
        3. Send current JobStatus as the first message.
        4. Add connection to the per‑job fan‑out set.
        5. Keep connection alive, discarding any incoming messages (frontend
           sends nothing; we only push events).
        6. On disconnect, remove connection from the fan‑out set.
    """
    # Extract request_id from query parameters
    request_id = websocket.query_params.get("request_id")
    if request_id is None:
        request_id = str(uuid.uuid4())

    # Bind request_id to structlog context for this connection
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(request_id=request_id)
    log = logger.bind(request_id=request_id, job_id=job_id)
    log.debug("websocket_connecting")

    # Accept the connection before we can read cookies
    await websocket.accept()

    # Authenticate
    username = await _authenticate_websocket(websocket, request_id)
    if username is None:
        # Connection already closed by _authenticate_websocket
        return

    # Get current job status from database
    db_gen: AsyncGenerator[AsyncDB, None] = get_db()
    db = await anext(db_gen)
    try:
        job_row = await get_job(db, job_id)
    finally:
        await db_gen.aclose()  # ensure generator cleanup

    if job_row is None:
        log.warning("job_not_found")
        await websocket.close(code=4004, reason=f"Job {job_id} not found")
        return

    # Build JobStatus schema object
    status = JobStatus(
        job_id=job_id,
        status=JobStatusEnum(job_row["status"]),
        percent=job_row.get("percent"),
        error_message=job_row.get("error_message"),
        created_at=job_row["created_at"],
    )
    # Send as first message (type is implicit — frontend knows it's JobStatus)
    await websocket.send_text(status.model_dump_json(by_alias=True))

    # Register connection for fan‑out
    await _add_connection(job_id, websocket)
    log.info("websocket_connected", username=username)

    try:
        # Keep connection alive; frontend sends no messages, but we must
        # call receive() to detect disconnection.
        while True:
            # We ignore any messages the frontend might send (none expected).
            # A timeout ensures we don't block forever on a stale connection.
            try:
                await asyncio.wait_for(websocket.receive_text(), timeout=30.0)
            except asyncio.TimeoutError:
                # Send a ping to check liveness
                await websocket.send_json({"type": "ping"})
    except WebSocketDisconnect:
        log.debug("websocket_disconnected")
    except Exception as exc:
        log.error("websocket_unexpected_error", exc=str(exc))
    finally:
        await _remove_connection(job_id, websocket)
        log.info("websocket_connection_removed")


# ---------------------------------------------------------------------------
# Event translation & broadcast (called by external services)
# ---------------------------------------------------------------------------

async def broadcast_download_progress(
    job_id: str,
    percent: float,
    speed: float,
    eta: int,
) -> None:
    """Convert plugin DownloadProgressEvent → WebSocket event and broadcast."""
    event = DownloadProgressEvent(percent=percent, speed=speed, eta=eta)
    await _broadcast_event(job_id, cast(JobWSEvent, event))


async def broadcast_download_complete(job_id: str, file_path: str) -> None:
    """Convert plugin DownloadCompleteEvent → WebSocket event and broadcast."""
    event = DownloadCompleteEvent(job_id=job_id, file_path=file_path)
    await _broadcast_event(job_id, cast(JobWSEvent, event))


async def broadcast_job_error(job_id: str, message: str, recoverable: bool) -> None:
    """Convert plugin DownloadErrorEvent → JobErrorEvent and broadcast."""
    event = JobErrorEvent(message=message, recoverable=recoverable)
    await _broadcast_event(job_id, cast(JobWSEvent, event))


async def broadcast_tagging_suggestions(
    job_id: str,
    candidates: list[dict],
) -> None:
    """Broadcast TaggingSuggestionsEvent (called by tagging service)."""
    # TODO: convert candidates to TagCandidate list
    pass


async def broadcast_tagging_error(job_id: str, message: str) -> None:
    """Broadcast TaggingErrorEvent (called by tagging service)."""
    event = TaggingErrorEvent(message=message)
    await _broadcast_event(job_id, cast(JobWSEvent, event))


async def broadcast_library_ready(job_id: str, navidrome_id: str, file_path: str) -> None:
    """Broadcast LibraryReadyEvent (called after file move & Navidrome rescan)."""
    event = LibraryReadyEvent(navidrome_id=navidrome_id, file_path=file_path)
    await _broadcast_event(job_id, cast(JobWSEvent, event))