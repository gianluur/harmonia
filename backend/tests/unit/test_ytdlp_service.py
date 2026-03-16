"""
backend/tests/unit/test_ytdlp_service.py

Unit tests for backend/services/ytdlp.py
"""

from __future__ import annotations

import pytest
import structlog

from backend.services.ytdlp import run_search, run_download, YTDLPError
from backend.schemas import SearchResult
from backend.plugin_base import DownloadProgressEvent, DownloadCompleteEvent, DownloadErrorEvent

logger = structlog.get_logger(__name__)


@pytest.mark.asyncio
async def test_run_search_query(mock_ytdlp):
    """Verify run_search returns expected SearchResults for a query."""
    mock_ytdlp.use_fixture("search_flat")
    results = [r async for r in run_search(
        query="test query", url=None, search_id="test-search-id", log=logger
    )]
    assert len(results) == 3
    assert all(isinstance(r, SearchResult) for r in results)
    assert results[0].id == "dQw4w9WgXcQ"
    assert results[0].source_plugin == "youtube"


@pytest.mark.asyncio
async def test_run_search_url(mock_ytdlp):
    """Verify run_search with a URL returns results from the fixture."""
    mock_ytdlp.use_fixture("search_flat")
    results = [r async for r in run_search(
        query=None,
        url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        search_id="test-search-id-url",
        log=logger,
    )]
    # URL search returns all fixture results (mock returns same fixture regardless)
    assert len(results) >= 1
    assert isinstance(results[0], SearchResult)


@pytest.mark.asyncio
async def test_run_search_flat_playlist_flag(mock_ytdlp):
    """Verify --flat-playlist flag is always passed to yt-dlp."""
    mock_ytdlp.use_fixture("search_flat")
    [r async for r in run_search(
        query="Radiohead", url=None, search_id="flag-test", log=logger
    )]
    mock_ytdlp.assert_flag_used("--flat-playlist")


@pytest.mark.asyncio
async def test_run_search_private_video_error(mock_ytdlp):
    """Verify run_search raises YTDLPError for private/unavailable videos."""
    mock_ytdlp.use_fixture("error_private_video", exit_code=1)
    with pytest.raises(YTDLPError, match="Video is private or unavailable."):
        [r async for r in run_search(
            query="private video", url=None, search_id="test-private-error", log=logger
        )]


@pytest.mark.asyncio
async def test_run_search_rate_limited_error(mock_ytdlp):
    """Verify run_search raises recoverable YTDLPError for rate limiting."""
    mock_ytdlp.use_fixture("error_rate_limited", exit_code=1)
    with pytest.raises(YTDLPError, match="Rate limited by YouTube.") as exc_info:
        [r async for r in run_search(
            query="any", url=None, search_id="test-rate-limit", log=logger
        )]
    assert exc_info.value.recoverable is True


@pytest.mark.asyncio
async def test_run_search_missing_id_skipped(mock_ytdlp):
    """Verify results missing the id field are silently skipped."""
    mock_ytdlp.use_fixture("malformed_missing_id")
    results = [r async for r in run_search(
        query="anything", url=None, search_id="malformed-test", log=logger
    )]
    assert len(results) == 0


@pytest.mark.asyncio
async def test_run_download_success(mock_ytdlp, fs_layout):
    """Verify run_download yields a DownloadCompleteEvent on success."""
    mock_ytdlp.use_fixture("download_complete")
    raw_dir = fs_layout["raw"]
    # Create the expected output file so file-exists check passes
    (raw_dir / "audio.opus").write_bytes(b"fake-audio-data")

    events = [e async for e in run_download(
        "test-job-id", "test_video_id", raw_dir, log=logger
    )]

    complete = next((e for e in events if isinstance(e, DownloadCompleteEvent)), None)
    assert complete is not None
    assert complete.job_id == "test-job-id"


@pytest.mark.asyncio
async def test_run_download_error_event(mock_ytdlp, fs_layout):
    """Verify run_download yields a DownloadErrorEvent on yt-dlp failure."""
    mock_ytdlp.use_fixture("error_private_video", exit_code=1)
    raw_dir = fs_layout["raw"]

    events = [e async for e in run_download(
        "test-job-error", "bad_video_id", raw_dir, log=logger
    )]

    error = next((e for e in events if isinstance(e, DownloadErrorEvent)), None)
    assert error is not None
    assert error.job_id == "test-job-error"
    assert "private or unavailable" in error.message.lower()


@pytest.mark.asyncio
async def test_run_download_no_file_yields_error(mock_ytdlp, fs_layout):
    """Verify run_download yields DownloadErrorEvent when file not found after success exit."""
    mock_ytdlp.use_fixture("empty_result", exit_code=0)
    raw_dir = fs_layout["raw"]
    # Do NOT create any audio file — raw_dir is empty

    events = [e async for e in run_download(
        "test-no-file-job", "some_id", raw_dir, log=logger
    )]

    error = next((e for e in events if isinstance(e, DownloadErrorEvent)), None)
    assert error is not None
    assert "not found" in error.message.lower()
    assert error.recoverable is False