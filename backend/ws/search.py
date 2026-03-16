# WebSocket handler for ws/search — accepts search messages, runs yt-dlp, streams results — see Architecture §4.2.2
"""
backend/ws/search.py

WebSocket handler for ws/search — streams yt-dlp search results as they
resolve, following the search WS protocol in Architecture §4.2.2.

Responsibilities:
  - Authenticate via JWT cookie, close with code 4001 on invalid JWT
  - Bind request_id from query param to structlog context
  - Accept: { type: "search", query?, url?, search_id } client message
  - Push search_result events as run_search() yields each SearchResult
  - Push search_complete when the generator is exhausted
  - Close idle connections after 60 seconds with no client message
  - Log connection/disconnection with request_id and search_id

Design notes:
  - One connection : one search. If the client sends another "search"
    message, the previous generator is cancelled and a new one starts.
  - Any yt-dlp error is translated to a job_error event (matches the
    event type used by the job WS channel; search has no dedicated error
    event in the schema).
  - Idle timeout is enforced via asyncio.wait_for on receive_text(); if
    the client sends no message within 60 s the connection is closed
    cleanly with code 1000.
"""

from __future__ import annotations

import asyncio
import json
import uuid

import structlog
from fastapi import WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

from backend.auth import TokenExpiredError, TokenInvalidError, decode_jwt
from backend.schemas import (
    JobErrorEvent,
    SearchCompleteEvent,
    SearchResultEvent,
)
from backend.services.ytdlp import YTDLPError, run_search

logger = structlog.get_logger(__name__)


# Idle timeout — close the connection if no client message arrives in this
# many seconds.  Keeps idle connections from accumulating on the server.
_IDLE_TIMEOUT_SECONDS = 60.0


# ---------------------------------------------------------------------------
# Authentication  (mirrors ws/job.py pattern exactly)
# ---------------------------------------------------------------------------


async def _authenticate_websocket(
    websocket: WebSocket,
    request_id: str,
) -> str | None:
    """
    Validate JWT cookie.

    Returns:
        username on success, None on failure.
        On failure the connection is already closed with code 4001.
    """
    token = websocket.cookies.get("harmonia_token")
    if not token:
        logger.warning(
            "websocket_search_auth_missing_token",
            request_id=request_id,
            path=websocket.url.path,
        )
        await websocket.close(code=4001, reason="Missing JWT cookie")
        return None

    try:
        payload = decode_jwt(token)
    except TokenExpiredError:
        logger.warning(
            "websocket_search_auth_token_expired",
            request_id=request_id,
            path=websocket.url.path,
        )
        await websocket.close(code=4001, reason="JWT expired")
        return None
    except TokenInvalidError:
        logger.warning(
            "websocket_search_auth_token_invalid",
            request_id=request_id,
            path=websocket.url.path,
        )
        await websocket.close(code=4001, reason="Invalid JWT")
        return None

    return payload.get("sub")


# ---------------------------------------------------------------------------
# Search runner  (isolated so it can be cancelled cleanly)
# ---------------------------------------------------------------------------


async def _run_search_session(
    websocket: WebSocket,
    query: str | None,
    url: str | None,
    search_id: str,
    log: structlog.BoundLogger,
) -> None:
    """
    Drive run_search() and forward each result to the WebSocket client.

    Sends:
        One SearchResultEvent per yielded SearchResult.
        One SearchCompleteEvent after the generator is exhausted.
        One JobErrorEvent if yt-dlp raises YTDLPError.

    This coroutine is run as an asyncio.Task so it can be cancelled when
    the client sends a new search request or disconnects.
    """
    total = 0
    try:
        async for result in run_search(query=query, url=url, search_id=search_id, log=log):
            if websocket.client_state == WebSocketState.DISCONNECTED:
                log.debug("search_ws_client_disconnected_mid_stream", search_id=search_id)
                return

            event = SearchResultEvent(result=result)
            await websocket.send_text(event.model_dump_json(by_alias=True))
            total += 1

        # All results delivered — send completion signal
        complete_event = SearchCompleteEvent(search_id=search_id, total=total)
        await websocket.send_text(complete_event.model_dump_json(by_alias=True))
        log.info("search_complete", search_id=search_id, total=total)

    except asyncio.CancelledError:
        # Caller cancelled this task (new search request or disconnect)
        log.debug("search_task_cancelled", search_id=search_id)
        raise  # must re-raise so asyncio knows the task was cancelled

    except YTDLPError as exc:
        log.warning(
            "search_ytdlp_error",
            search_id=search_id,
            error=str(exc),
            recoverable=exc.recoverable,
        )
        if websocket.client_state != WebSocketState.DISCONNECTED:
            error_event = JobErrorEvent(message=str(exc), recoverable=exc.recoverable)
            await websocket.send_text(error_event.model_dump_json(by_alias=True))

    except Exception as exc:
        log.error("search_unexpected_error", search_id=search_id, error=str(exc))
        if websocket.client_state != WebSocketState.DISCONNECTED:
            error_event = JobErrorEvent(message=str(exc), recoverable=True)
            await websocket.send_text(error_event.model_dump_json(by_alias=True))


# ---------------------------------------------------------------------------
# WebSocket endpoint
# ---------------------------------------------------------------------------


async def websocket_endpoint(websocket: WebSocket) -> None:
    """
    WebSocket handler for ``ws/search``.

    Query parameters:
        request_id — optional UUID v4; generated if absent.

    Protocol (client → server):
        { "type": "search", "search_id": "<uuid>", "query": "<text>" }
        { "type": "search", "search_id": "<uuid>", "url": "<youtube-url>" }

    Protocol (server → client):
        SearchResultEvent  — one per result, as yt-dlp resolves each entry
        SearchCompleteEvent — when all results have been pushed
        JobErrorEvent       — if yt-dlp fails

    Idle timeout:
        If the client sends no message for 60 s the connection is closed
        with code 1000 (normal closure).

    Flow:
        1. Accept the connection.
        2. Authenticate via JWT cookie → close 4001 on failure.
        3. Enter receive loop with idle timeout.
        4. On each "search" message: cancel any in-flight search task,
           start a new one.
        5. On timeout: close 1000.
        6. On disconnect: cancel in-flight task, exit cleanly.
    """
    # --- request_id binding ---
    request_id = websocket.query_params.get("request_id") or str(uuid.uuid4())
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(request_id=request_id)
    log = logger.bind(request_id=request_id)
    log.debug("search_ws_connecting")

    await websocket.accept()

    username = await _authenticate_websocket(websocket, request_id)
    if username is None:
        return  # already closed by _authenticate_websocket

    log.info("search_ws_connected", username=username)

    # Track the currently running search task so we can cancel it when
    # the client sends a new search or disconnects.
    current_task: asyncio.Task | None = None

    # Check if there's a pending search for this request_id (initiated by POST /api/search)
    pending_searches = getattr(websocket.app.state, "pending_searches", None)
    if pending_searches and request_id in pending_searches:
        query, url = pending_searches.pop(request_id)
        search_id = request_id
        search_log = log.bind(search_id=search_id)
        search_log.info(
            "search_ws_search_started_from_pending",
            query=query,
            url=url,
        )
        current_task = asyncio.create_task(
            _run_search_session(
                websocket=websocket,
                query=query,
                url=url,
                search_id=search_id,
                log=search_log,
            )
        )


    try:
        while True:
            # --- wait for a client message (with idle timeout) ---
            try:
                raw = await asyncio.wait_for(
                    websocket.receive_text(),
                    timeout=_IDLE_TIMEOUT_SECONDS,
                )
            except asyncio.TimeoutError:
                log.info("search_ws_idle_timeout", request_id=request_id)
                if current_task and not current_task.done():
                    current_task.cancel()
                    try:
                        await current_task
                    except (asyncio.CancelledError, Exception):
                        pass
                await websocket.close(code=1000, reason="Idle timeout")
                return

            # --- parse client message ---
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                log.warning("search_ws_invalid_json", raw=raw[:200])
                continue

            msg_type = msg.get("type")

            if msg_type != "search":
                log.debug("search_ws_unknown_message_type", msg_type=msg_type)
                continue

            query: str | None = msg.get("query") or None
            url: str | None = msg.get("url") or None
            search_id: str = msg.get("search_id") or str(uuid.uuid4())

            if not query and not url:
                log.warning("search_ws_message_missing_query_and_url", search_id=search_id)
                error_event = JobErrorEvent(
                    message="Search message must include 'query' or 'url'.",
                    recoverable=True,
                )
                await websocket.send_text(error_event.model_dump_json(by_alias=True))
                continue

            # Cancel any in-flight search before starting the new one
            if current_task and not current_task.done():
                log.debug("search_ws_cancelling_previous_task", search_id=search_id)
                current_task.cancel()
                try:
                    await current_task
                except (asyncio.CancelledError, Exception):
                    pass

            search_log = log.bind(search_id=search_id)
            search_log.info(
                "search_ws_search_started",
                query=query,
                url=url,
            )

            current_task = asyncio.create_task(
                _run_search_session(
                    websocket=websocket,
                    query=query,
                    url=url,
                    search_id=search_id,
                    log=search_log,
                )
            )

    except WebSocketDisconnect:
        log.debug("search_ws_disconnected")
    except Exception as exc:
        log.error("search_ws_unexpected_error", error=str(exc))
    finally:
        # Always cancel any running search task on exit
        if current_task and not current_task.done():
            current_task.cancel()
            try:
                await current_task
            except (asyncio.CancelledError, Exception):
                pass
        log.info("search_ws_connection_removed")