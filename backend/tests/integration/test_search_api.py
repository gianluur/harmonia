# Integration tests for /api/search — see Testing spec §4.2
"""
backend/tests/integration/test_search_api.py

Integration tests for the search WebSocket handler and POST /api/search.
Covers all 5 scenarios from Testing spec §4.2.

Fixtures used (all from conftest.py — never redefined here):
  auth_client   — authenticated AsyncClient with JWT cookie set
  mock_ytdlp    — patches asyncio.create_subprocess_exec
  ws_collect    — WebSocket helper (module-level utility)
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from backend.schemas import SearchResult
from backend.tests.conftest import ws_collect


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _initiate_search(auth_client: AsyncClient, payload: dict) -> str:
    """POST /api/search and return the search_id."""
    resp = await auth_client.post("/api/search", json=payload)
    assert resp.status_code == 200, f"POST /api/search failed: {resp.text}"
    return resp.json()["searchId"]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_search_query_returns_results_via_ws(
    auth_client: AsyncClient,
    mock_ytdlp,
):
    """
    POST /api/search {query:'Radiohead'} → WebSocket pushes search_result
    events for each fixture entry, then a search_complete event.

    search_flat.json has 3 entries, so we expect 3 search_result events
    followed by 1 search_complete event = 4 total events.
    """
    mock_ytdlp.use_fixture("search_flat")

    search_id = await _initiate_search(auth_client, {"query": "Radiohead"})

    # 3 results + 1 search_complete
    events = await ws_collect(auth_client, f"/ws/search?request_id={search_id}", n_events=4)

    result_events = [e for e in events if e["type"] == "search_result"]
    complete_events = [e for e in events if e["type"] == "search_complete"]

    assert len(result_events) == 3
    assert len(complete_events) == 1
    assert complete_events[0]["searchId"] == search_id
    assert complete_events[0]["total"] == 3


@pytest.mark.asyncio
async def test_search_youtube_url_direct(
    auth_client: AsyncClient,
    mock_ytdlp,
):
    """
    POST /api/search {url:'https://youtube.com/watch?v=...'} →
    single search_result pushed immediately, then search_complete.
    """
    mock_ytdlp.use_fixture("search_flat")

    search_id = await _initiate_search(
        auth_client,
        {"url": "https://youtube.com/watch?v=dQw4w9WgXcQ"},
    )

    # At least 1 result + 1 search_complete
    events = await ws_collect(auth_client, f"/ws/search?request_id={search_id}", n_events=4)

    result_events = [e for e in events if e["type"] == "search_result"]
    complete_events = [e for e in events if e["type"] == "search_complete"]

    assert len(result_events) >= 1
    assert len(complete_events) == 1


@pytest.mark.asyncio
async def test_search_flat_playlist_used(
    auth_client: AsyncClient,
    mock_ytdlp,
):
    """
    yt-dlp mock asserts --flat-playlist flag was present in the subprocess
    call args when a search is initiated.
    """
    mock_ytdlp.use_fixture("search_flat")

    search_id = await _initiate_search(auth_client, {"query": "Radiohead"})

    # Collect events to ensure the search ran
    await ws_collect(auth_client, f"/ws/search?request_id={search_id}", n_events=4)

    mock_ytdlp.assert_flag_used("--flat-playlist")


@pytest.mark.asyncio
async def test_search_ytdlp_error_pushes_job_error(
    auth_client: AsyncClient,
    mock_ytdlp,
):
    """
    yt-dlp returns non-zero exit code → WebSocket pushes a job_error event.
    """
    mock_ytdlp.use_fixture("error_private_video", exit_code=1)

    search_id = await _initiate_search(auth_client, {"query": "private video"})

    # Expect exactly 1 job_error event
    events = await ws_collect(auth_client, f"/ws/search?request_id={search_id}", n_events=1)

    assert events[0]["type"] == "job_error"
    assert isinstance(events[0]["message"], str)
    assert len(events[0]["message"]) > 0


@pytest.mark.asyncio
async def test_search_result_schema_valid(
    auth_client: AsyncClient,
    mock_ytdlp,
):
    """
    Every search_result event payload validates against the SearchResult
    Pydantic model — no extra or missing fields.
    """
    mock_ytdlp.use_fixture("search_flat")

    search_id = await _initiate_search(auth_client, {"query": "Radiohead"})

    events = await ws_collect(auth_client, f"/ws/search?request_id={search_id}", n_events=4)

    result_events = [e for e in events if e["type"] == "search_result"]
    assert len(result_events) == 3

    for event in result_events:
        # Validate the nested result object against the SearchResult schema.
        # Pydantic will raise ValidationError if any required field is missing
        # or has the wrong type.
        result = SearchResult(**event["result"])
        assert result.id
        assert result.title
        assert result.source_plugin == "youtube"