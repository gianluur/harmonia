"""
backend/plugin_base.py

Plugin contract — abstract base class every source plugin must implement.

Architecture spec §5 defines the plugin contract in prose. This file is
the Python enforcement of that contract: any class that does not implement
every abstract method will raise TypeError at import time, long before any
user touches it.

Two classes are defined here:

  SourcePlugin (ABC)
    The abstract base. New source plugins subclass this. The YouTube plugin
    (backend/plugins/youtube.py) will be the first real implementation.

  MockYouTubePlugin
    A concrete stub that returns fixture data. Used by:
      - tests/contract/test_plugin_contract.py  (validates the contract itself)
      - tests/integration/*                     (any test that needs a plugin)
      - Local development without a live yt-dlp install

Patterns:
  - search() is an async generator — it yields results one at a time so the
    WebSocket handler can push each result to the frontend immediately
  - acquire() is an async generator — it yields DownloadEvent objects
    (progress, complete, error) so the WS handler can fan them out
  - stream() returns an AsyncIterator of bytes — the stream endpoint reads
    from it in chunks
  - All methods receive a structlog BoundLogger so every plugin emits log
    lines with the same fields as the rest of the backend
  - get_manifest() is a classmethod — the plugin registry calls it without
    instantiating the plugin
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator, AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import structlog

from backend.schemas import (
    AcquireResponse,
    JobStatusEnum,
    PluginCapability,
    PluginManifest,
    PluginSearchInput,
    SearchResult,
    TagPayload,
)

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Download event types (internal — not sent over the wire directly)
# The WS handler translates these into the appropriate WSEvent schemas.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DownloadProgressEvent:
    """Emitted repeatedly during download with current progress."""
    job_id: str
    percent: float
    speed: float        # bytes/second
    eta: int            # seconds remaining


@dataclass(frozen=True)
class DownloadCompleteEvent:
    """Emitted once when yt-dlp (or equivalent) finishes writing the file."""
    job_id: str
    file_path: str      # absolute path to the downloaded audio file


@dataclass(frozen=True)
class DownloadErrorEvent:
    """Emitted if the download fails. recoverable=True means the user can retry."""
    job_id: str
    message: str
    recoverable: bool


# Union type for acquire() yields
DownloadEvent = DownloadProgressEvent | DownloadCompleteEvent | DownloadErrorEvent


# ---------------------------------------------------------------------------
# Abstract base class
# ---------------------------------------------------------------------------


class SourcePlugin(ABC):
    """
    Abstract base class for all Harmonia source plugins.

    Every plugin that provides music from an external source must subclass
    this and implement all abstract methods. The plugin registry in
    backend/plugins.py calls get_manifest() at startup to discover
    capabilities and validate the plugin before registering it.

    Subclassing example:
        class YouTubePlugin(SourcePlugin):
            @classmethod
            def get_manifest(cls) -> PluginManifest:
                return PluginManifest(
                    id="youtube",
                    name="YouTube",
                    ...
                )

            async def search(self, query, search_id, log) -> AsyncGenerator[SearchResult, None]:
                async for result in _run_ytdlp_flat(query):
                    yield result

            async def acquire(self, job_id, youtube_id, raw_dir, log) -> AsyncGenerator[DownloadEvent, None]:
                async for event in _run_ytdlp_download(job_id, youtube_id, raw_dir):
                    yield event

            async def stream(self, job_id, file_path, log) -> AsyncIterator[bytes]:
                async with aiofiles.open(file_path, "rb") as f:
                    while chunk := await f.read(65536):
                        yield chunk

            async def confirm_tags(self, job_id, file_path, payload, log) -> str:
                write_tags(file_path, payload)
                dest = build_library_path(...)
                shutil.move(file_path, dest)
                return str(dest)
    """

    # ------------------------------------------------------------------
    # Plugin identity (must be implemented)
    # ------------------------------------------------------------------

    @classmethod
    @abstractmethod
    def get_manifest(cls) -> PluginManifest:
        """
        Return the plugin's manifest describing its identity and capabilities.
        Called at startup by the plugin registry — no instance required.
        The manifest is validated against the PluginManifest Pydantic model.
        """

    # ------------------------------------------------------------------
    # Capability: search (required if manifest declares PluginCapability.search)
    # ------------------------------------------------------------------

    @abstractmethod
    async def search(
        self,
        *,
        query: str | None,
        url: str | None,
        search_id: str,
        log: structlog.BoundLogger,
    ) -> AsyncGenerator[SearchResult, None]:
        """
        Search for tracks matching `query` or `url`.
        Exactly one of query/url will be non-None (validated upstream).

        Yields SearchResult objects one at a time as they resolve.
        The WS handler pushes each result to the frontend immediately —
        do not batch and return all at once.

        On failure, raise PluginSearchError with a descriptive message.
        Do not yield partial results and then raise — either yield all
        results successfully or raise immediately.

        Args:
            query:     free-text search string, or None if url is set
            url:       direct URL (e.g. YouTube video URL), or None if query is set
            search_id: UUID v4 from the frontend, echoed in all WS events
            log:       structlog logger pre-bound with search_id
        """
        # This makes the method a generator — subclasses must also yield.
        # Without this the ABC machinery would accept a non-generator override.
        return
        yield  # noqa: unreachable — makes this an async generator

    # ------------------------------------------------------------------
    # Capability: acquire (required if manifest declares PluginCapability.acquire)
    # ------------------------------------------------------------------

    @abstractmethod
    async def acquire(
        self,
        *,
        job_id: str,
        youtube_id: str,
        raw_dir: Path,
        log: structlog.BoundLogger,
    ) -> AsyncGenerator[DownloadEvent, None]:
        """
        Download the track identified by `youtube_id` into `raw_dir`.

        Yields DownloadEvent objects as the download progresses:
          1. Zero or more DownloadProgressEvent (percent, speed, eta)
          2. Exactly one terminal event: DownloadCompleteEvent or DownloadErrorEvent

        The caller (WS handler) translates these into WebSocket messages.
        After yielding DownloadCompleteEvent, the file at event.file_path
        must exist and be readable.

        Args:
            job_id:     UUID v4 identifying this acquisition job
            youtube_id: plugin-scoped track identifier (for YouTube: the video ID)
            raw_dir:    Path to /data/raw/<job_id>/ — write the file here
            log:        structlog logger pre-bound with job_id
        """
        return
        yield  # noqa: unreachable

    # ------------------------------------------------------------------
    # Capability: stream (required if manifest declares PluginCapability.stream)
    # ------------------------------------------------------------------

    @abstractmethod
    async def stream(
        self,
        *,
        job_id: str,
        file_path: str,
        log: structlog.BoundLogger,
    ) -> AsyncIterator[bytes]:
        """
        Stream the audio file at `file_path` as raw bytes.

        The stream endpoint reads from this iterator in chunks and forwards
        them to the frontend's audio element. The file may be partially
        written (download still in progress) — the implementation must
        handle that gracefully (e.g. tail-follow the file).

        Supports HTTP range requests: the stream endpoint handles the
        Range header externally and calls this method with the full path;
        byte-range slicing is done at the endpoint layer, not here.

        Args:
            job_id:    UUID v4 — used for logging only
            file_path: absolute path to the audio file (may be partial)
            log:       structlog logger pre-bound with job_id
        """
        return
        yield  # noqa: unreachable

    # ------------------------------------------------------------------
    # Capability: tag confirmation (always required if acquire is declared)
    # ------------------------------------------------------------------

    @abstractmethod
    async def confirm_tags(
        self,
        *,
        job_id: str,
        file_path: str,
        payload: TagPayload,
        log: structlog.BoundLogger,
    ) -> str:
        """
        Write finalised tags to the audio file, move it to the library,
        and return the destination path.

        Steps (all must be completed before returning):
          1. Write ID3/Vorbis tags to file_path using Mutagen
          2. Build the library path from payload fields
          3. Move the file from raw_dir to the library path
          4. Return the destination path as a string

        The caller (PATCH /api/acquire/:job_id/tags) triggers the Navidrome
        rescan after this method returns — do not trigger it here.

        Args:
            job_id:    UUID v4 — used for logging
            file_path: absolute path to the tagged audio file in /data/raw/
            payload:   finalised tag values from the user
            log:       structlog logger pre-bound with job_id

        Returns:
            Absolute path where the file now lives in the library.
        """

    # ------------------------------------------------------------------
    # Helpers available to all subclasses
    # ------------------------------------------------------------------

    def _log(self, **kwargs: Any) -> structlog.BoundLogger:
        """Return a logger bound with the plugin id and any extra fields."""
        return logger.bind(plugin=self.get_manifest().id, **kwargs)

    def supports(self, capability: PluginCapability) -> bool:
        """Return True if this plugin declares the given capability."""
        return capability in self.get_manifest().capabilities


# ---------------------------------------------------------------------------
# Plugin errors
# ---------------------------------------------------------------------------


class PluginError(Exception):
    """Base class for all plugin errors."""


class PluginSearchError(PluginError):
    """Raised when a search operation fails."""


class PluginAcquireError(PluginError):
    """Raised when a download operation fails. Set recoverable=True for retryable errors."""

    def __init__(self, message: str, *, recoverable: bool = False) -> None:
        super().__init__(message)
        self.recoverable = recoverable


class PluginStreamError(PluginError):
    """Raised when a stream operation fails."""


class PluginTagError(PluginError):
    """Raised when tag writing or file move fails."""


# ---------------------------------------------------------------------------
# MockYouTubePlugin — concrete stub for tests and local dev
# ---------------------------------------------------------------------------

_FIXTURES_DIR = Path(__file__).parent / "tests" / "fixtures" / "ytdlp"

# Inline fixture data so the mock works even before fixture files are created
_MOCK_SEARCH_RESULTS = [
    {
        "id": "dQw4w9WgXcQ",
        "title": "Never Gonna Give You Up",
        "artist": "Rick Astley",
        "duration_seconds": 213,
        "thumbnail_url": "/api/proxy/thumbnail/dQw4w9WgXcQ",
        "source_plugin": "youtube",
        "source_url": "https://youtube.com/watch?v=dQw4w9WgXcQ",
        "year": 1987,
    },
    {
        "id": "9bZkp7q19f0",
        "title": "Gangnam Style",
        "artist": "PSY",
        "duration_seconds": 252,
        "thumbnail_url": "/api/proxy/thumbnail/9bZkp7q19f0",
        "source_plugin": "youtube",
        "source_url": "https://youtube.com/watch?v=9bZkp7q19f0",
        "year": 2012,
    },
    {
        "id": "kJQP7kiw5Fk",
        "title": "Despacito",
        "artist": "Luis Fonsi ft. Daddy Yankee",
        "duration_seconds": 282,
        "thumbnail_url": "/api/proxy/thumbnail/kJQP7kiw5Fk",
        "source_plugin": "youtube",
        "source_url": "https://youtube.com/watch?v=kJQP7kiw5Fk",
        "year": 2017,
    },
]


class MockYouTubePlugin(SourcePlugin):
    """
    Concrete stub implementation of SourcePlugin for tests and local dev.

    Returns deterministic fixture data — no real yt-dlp, no network calls.
    Used by:
      - tests/contract/test_plugin_contract.py
      - tests/integration/* (any test that needs a plugin without real yt-dlp)
      - Local development when HARMONIA_MOCK_PLUGINS=true

    Behaviour:
      - search(): yields 3 hardcoded SearchResult objects with a 0.05s delay
        between each to simulate streaming (tests can assert on ordering)
      - acquire(): yields 10 progress events then a DownloadCompleteEvent,
        writing a copy of tests/fixtures/ytdlp/audio_sample.opus to raw_dir
      - stream(): reads and yields the audio_sample.opus in 64KB chunks
      - confirm_tags(): writes a minimal tag set and moves the file
    """

    # Configurable delay between search results (set to 0 in fast unit tests)
    search_delay_seconds: float = 0.05

    @classmethod
    def get_manifest(cls) -> PluginManifest:
        return PluginManifest(
            id="youtube",
            name="YouTube (Mock)",
            version="0.0.1-mock",
            base_url="http://localhost:8001",
            capabilities=[
                PluginCapability.search,
                PluginCapability.stream,
                PluginCapability.acquire,
            ],
            search_input=[PluginSearchInput.query, PluginSearchInput.url],
            audio_formats=["opus"],
            icon="/icons/youtube.svg",
        )

    async def search(
        self,
        *,
        query: str | None,
        url: str | None,
        search_id: str,
        log: structlog.BoundLogger,
    ) -> AsyncGenerator[SearchResult, None]:
        import asyncio

        log.debug("mock_search_started", query=query, url=url)

        # If a URL is passed, return just the first result (simulates direct lookup)
        results = _MOCK_SEARCH_RESULTS[:1] if url else _MOCK_SEARCH_RESULTS

        for raw in results:
            if self.search_delay_seconds > 0:
                await asyncio.sleep(self.search_delay_seconds)
            yield SearchResult(**raw)

        log.debug("mock_search_complete", result_count=len(results))

    async def acquire(
        self,
        *,
        job_id: str,
        youtube_id: str,
        raw_dir: Path,
        log: structlog.BoundLogger,
    ) -> AsyncGenerator[DownloadEvent, None]:
        import asyncio
        import shutil

        log.info("mock_acquire_started", youtube_id=youtube_id)

        # Emit 10 evenly-spaced progress events (0%→100%)
        for i in range(1, 11):
            await asyncio.sleep(0.01)  # fast in tests
            yield DownloadProgressEvent(
                job_id=job_id,
                percent=float(i * 10),
                speed=1_500_000.0,  # 1.5 MB/s simulated
                eta=int((10 - i) * 0.1),
            )

        # Write the audio sample to raw_dir
        sample_path = _FIXTURES_DIR / "audio_sample.opus"
        dest_path = raw_dir / "audio.opus"

        if sample_path.exists():
            shutil.copy(sample_path, dest_path)
        else:
            # Create a minimal valid file if fixture not yet present
            dest_path.write_bytes(b"mock-opus-data")

        log.info("mock_acquire_complete", file_path=str(dest_path))
        yield DownloadCompleteEvent(job_id=job_id, file_path=str(dest_path))

    async def stream(
        self,
        *,
        job_id: str,
        file_path: str,
        log: structlog.BoundLogger,
    ) -> AsyncIterator[bytes]:
        import aiofiles

        log.debug("mock_stream_started", file_path=file_path)
        chunk_size = 65_536  # 64 KB

        try:
            async with aiofiles.open(file_path, "rb") as f:
                while True:
                    chunk = await f.read(chunk_size)
                    if not chunk:
                        break
                    yield chunk
        except FileNotFoundError as exc:
            raise PluginStreamError(f"Audio file not found: {file_path}") from exc

        log.debug("mock_stream_complete", file_path=file_path)

    async def confirm_tags(
        self,
        *,
        job_id: str,
        file_path: str,
        payload: TagPayload,
        log: structlog.BoundLogger,
    ) -> str:
        """
        Stub implementation: moves the file to a deterministic library path.
        Real tag writing (Mutagen) happens in backend/services/tagger.py —
        this mock skips that step so tests don't need Mutagen installed.
        """
        import shutil

        from backend.services.tagger import build_library_path
        from backend.config import settings

        dest = build_library_path(
            library_root=settings.music_library_path,
            artist=payload.artist or "Unknown Artist",
            album=payload.album or "Unknown Album",
            year=payload.year,
            track_number=payload.track_number,
            title=payload.title,
            extension=Path(file_path).suffix.lstrip(".") or "opus",
        )

        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(file_path, dest)
        log.info("mock_confirm_tags_complete", dest=str(dest))
        return str(dest)
