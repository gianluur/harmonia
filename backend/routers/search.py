"""
backend/routers/search.py

Search endpoint:
  POST /api/search — initiates a WebSocket search session.

Patterns followed from backend/routers/auth.py:
  - Every route has explicit response_model and status_code
  - No business logic in route functions — call a service, return its result
  - All errors: {"error": machine_code, "detail": human message, "request_id": uuid}
  - structlog bound per-request via log = logger.bind(**); never module logger in routes
  - Database access only through Depends(get_db) (not needed for search)
  - All datetimes UTC; never datetime.now() without UTC
"""

from __future__ import annotations

import uuid
from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, status

from backend.schemas import SearchRequest
from backend.routers.auth import require_auth

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api", tags=["search"])


@router.post(
    "/search",
    status_code=status.HTTP_200_OK,
    summary="Initiate a YouTube search",
)
async def post_search(
    body: SearchRequest,
    request: Request,
    auth: Annotated[dict, Depends(require_auth)],
) -> dict[str, str]:
    """
    Accepts a search query or YouTube URL, generates a search_id,
    and stores the request parameters for the WebSocket handler.

    The frontend should open a WebSocket connection to ws/search
    with the same search_id as the request_id query parameter.
    The WebSocket handler will start the search and push results.

    Returns { "searchId": "<uuid>" }.
    """
    log = logger.bind(
        query=body.query,
        url=body.url,
        path="/api/search",
        username=auth.get("sub"),
    )
    log.info("search_requested")

    # Validate that at least one of query or url is provided (already enforced by SearchRequest)
    if body.query is None and body.url is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error": "missing_query_or_url",
                "detail": "At least one of 'query' or 'url' must be provided.",
                "request_id": request.state.request_id,
            },
        )

    search_id = str(uuid.uuid4())
    # Store pending search in app state for WebSocket handler to pick up
    if not hasattr(request.app.state, "pending_searches"):
        request.app.state.pending_searches = {}
    request.app.state.pending_searches[search_id] = (body.query, body.url)

    log.info("search_initiated", search_id=search_id)
    return {"searchId": search_id}
