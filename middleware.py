"""
backend/middleware.py

RequestIDMiddleware — threads X-Request-ID through every request lifecycle.

Behaviour:
  - If the incoming request has an X-Request-ID header, use that value.
  - If not, generate a UUID v4.
  - Bind the request_id to structlog's contextvars so every log line
    emitted during this request automatically includes it.
  - Echo the request_id in the X-Request-ID response header.

This means a single grep request_id=<uuid> in logs returns every line
— HTTP, WebSocket, background task — for that entire user action.

WebSocket connections pass request_id as a query parameter:
    ws://<backend>/ws/<job_id>?request_id=<uuid>
The WS handlers read it manually and call bind_contextvars() themselves
(see backend/ws/job.py and backend/ws/search.py).

Coverage requirement: 100% (Architecture §8.2 — tracing middleware must
never silently drop a request_id).
"""

from __future__ import annotations

import uuid

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

logger = structlog.get_logger(__name__)

REQUEST_ID_HEADER = "X-Request-ID"


class RequestIDMiddleware(BaseHTTPMiddleware):
    """
    ASGI middleware that ensures every request has a request_id.

    Reads X-Request-ID from the incoming request headers.
    Falls back to a freshly generated UUID v4 if absent.
    Binds the value to structlog contextvars for the duration of the request.
    Adds the value to the outgoing response headers.
    Stores it on request.state.request_id for use in route handlers
    (e.g. when building error response envelopes).
    """

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next) -> Response:
        # Read or generate
        request_id = request.headers.get(REQUEST_ID_HEADER) or str(uuid.uuid4())

        # Make available to route handlers via request.state
        request.state.request_id = request_id

        # Bind to structlog context — all log lines in this request get it
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id)

        # Process the request
        response = await call_next(request)

        # Echo in response header
        response.headers[REQUEST_ID_HEADER] = request_id

        return response
