"""
Harmonia – Pydantic v2 schema definitions.

All models that are purely read (responses, events) carry
``model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, frozen=True)`` to make them immutable.
Mutating request models (SetupRequest, LoginRequest, AcquireRequest,
SearchRequest, TagPayload) are left mutable so callers can construct
them incrementally if needed.

TypeScript equivalents live in frontend/src/lib/types.ts.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from pydantic.alias_generators import to_camel



# ---------------------------------------------------------------------------
# Base model with camelCase serialisation
# ---------------------------------------------------------------------------


class _CamelModel(BaseModel):
    """
    Internal base: configures camelCase JSON aliases for all models.
    FastAPI serialises snake_case Python fields to camelCase JSON automatically.
    Construct with snake_case in Python code (populate_by_name=True).
    """

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
    )

# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class JobStatusEnum(str, Enum):
    """Lifecycle states a background acquisition job can be in."""

    pending = "pending"
    downloading = "downloading"
    tagging = "tagging"
    confirmed = "confirmed"
    error = "error"


class TagSource(str, Enum):
    """Origin of a tagging suggestion."""

    beets = "beets"
    musicbrainz = "musicbrainz"
    custom = "custom"
    manual = "manual"


class PluginCapability(str, Enum):
    """Actions a source plugin can perform."""

    search = "search"
    stream = "stream"
    acquire = "acquire"


class PluginSearchInput(str, Enum):
    """Input modalities a plugin's search endpoint accepts."""

    query = "query"
    url = "url"


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------


class SetupRequest(_CamelModel):
    """Payload for the first-run setup endpoint that creates the admin account."""

    username: str
    password: str


class LoginRequest(_CamelModel):
    """Credentials posted to the login endpoint."""

    username: str
    password: str


class AuthStatus(_CamelModel):
    """Tells the frontend whether initial setup has been completed."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, frozen=True)

    configured: bool


class TokenResponse(_CamelModel):
    """JWT issued on successful authentication."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, frozen=True)

    access_token: str
    token_type: str
    expires_at: datetime


# ---------------------------------------------------------------------------
# Jobs & Acquisition
# ---------------------------------------------------------------------------


class AcquireRequest(_CamelModel):
    """Request body for POST /api/acquire – starts a new acquisition job."""

    youtube_id: str
    title_hint: str | None = None


class AcquireResponse(_CamelModel):
    """Response from POST /api/acquire containing identifiers for the new job."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, frozen=True)

    job_id: str
    stream_token: str


class JobStatus(_CamelModel):
    """Current state of an acquisition job, including optional progress data."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, frozen=True)

    job_id: str
    status: JobStatusEnum
    percent: float | None = None
    error_message: str | None = None
    created_at: datetime


class StreamToken(_CamelModel):
    """Internal signed token scoped to a single job for stream authentication."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, frozen=True)

    job_id: str
    expires_at: datetime


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------


class SearchRequest(_CamelModel):
    """Parameters for initiating a search; at least one of query or url is required."""

    query: str | None = None
    url: str | None = None

    @model_validator(mode="after")
    def require_query_or_url(self) -> "SearchRequest":
        """Ensure at least one search parameter is present."""
        if self.query is None and self.url is None:
            raise ValueError("At least one of 'query' or 'url' must be provided.")
        return self


class SearchResult(_CamelModel):
    """A single candidate track returned by a source plugin during search."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, frozen=True)

    id: str
    title: str
    artist: str
    duration_seconds: int
    thumbnail_url: str
    source_plugin: str
    source_url: str
    year: int | None = None


class SearchCompleteEvent(_CamelModel):
    """Signals that a search operation has finished and provides the total result count."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, frozen=True)

    type: Literal["search_complete"] = "search_complete"
    search_id: str
    total: int


# ---------------------------------------------------------------------------
# Tagging
# ---------------------------------------------------------------------------


class TagPayload(_CamelModel):
    """Final tag values submitted by the user to be written to an audio file."""

    title: str
    artist: str
    album: str | None = None
    year: int | None = None
    track_number: int | None = None
    disc_number: int | None = None
    genre: str | None = None
    cover_art_url: str | None = None
    cover_art_b64: str | None = None
    mb_recording_id: str | None = None
    mb_release_id: str | None = None

    @field_validator("title", "artist")
    @classmethod
    def must_be_non_empty(cls, v: str) -> str:
        """Validate that title and artist are non-empty strings."""
        if not v or not v.strip():
            raise ValueError("Field must be a non-empty string.")
        return v


class TagCandidate(TagPayload):
    """A tagging suggestion from an automated source, annotated with confidence."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, frozen=True)

    confidence: Annotated[float, Field(ge=0.0, le=1.0)]
    source: TagSource


# ---------------------------------------------------------------------------
# WebSocket Events
# ---------------------------------------------------------------------------


class DownloadProgressEvent(_CamelModel):
    """Real-time download progress pushed over the job WebSocket."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, frozen=True)

    type: Literal["download_progress"] = "download_progress"
    percent: float
    speed: float
    eta: int


class DownloadCompleteEvent(_CamelModel):
    """Emitted when yt-dlp finishes writing the audio file to disk."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, frozen=True)

    type: Literal["download_complete"] = "download_complete"
    job_id: str
    file_path: str


class TaggingSuggestionsEvent(_CamelModel):
    """Carries beets/MusicBrainz tag candidates for display in the tagging panel."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, frozen=True)

    type: Literal["tagging_suggestions"] = "tagging_suggestions"
    candidates: list[TagCandidate]


class LibraryReadyEvent(_CamelModel):
    """Emitted once a track has been tagged, moved, and added to the Navidrome library."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, frozen=True)

    type: Literal["library_ready"] = "library_ready"
    navidrome_id: str
    file_path: str


class JobErrorEvent(_CamelModel):
    """Signals an acquisition job failure, distinguishing recoverable from fatal errors."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, frozen=True)

    type: Literal["job_error"] = "job_error"
    message: str
    recoverable: bool


class SearchResultEvent(_CamelModel):
    """Streams a single search result to the frontend as it resolves."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, frozen=True)

    type: Literal["search_result"] = "search_result"
    result: SearchResult


class TaggingErrorEvent(_CamelModel):
    """Emitted when beets or MusicBrainz lookup fails; tagging panel falls back to manual entry."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, frozen=True)

    type: Literal["tagging_error"] = "tagging_error"
    message: str


# Per-job WebSocket channel (ws://<backend>/ws/<job_id>).
JobWSEvent = (
    DownloadProgressEvent
    | DownloadCompleteEvent
    | TaggingSuggestionsEvent
    | LibraryReadyEvent
    | TaggingErrorEvent
    | JobErrorEvent
)

# Search WebSocket channel (ws://<backend>/ws/search).
SearchWSEvent = SearchResultEvent | SearchCompleteEvent

# Full union across both channels.
# Prefer the narrower JobWSEvent or SearchWSEvent at call sites.
WSEvent = JobWSEvent | SearchWSEvent


# ---------------------------------------------------------------------------
# Metadata
# ---------------------------------------------------------------------------


class MusicBrainzArtist(_CamelModel):
    """A MusicBrainz artist entity returned from the metadata proxy."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, frozen=True)

    mbid: str
    name: str
    disambiguation: str | None = None
    score: int


class MusicBrainzRelease(_CamelModel):
    """A MusicBrainz release (album) associated with a recording."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, frozen=True)

    mbid: str
    title: str
    date: str | None = None
    track_count: int | None = None


class MusicBrainzRecording(_CamelModel):
    """A MusicBrainz recording (track) with its linked releases."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, frozen=True)

    mbid: str
    title: str
    artist_credit: str | None = None
    releases: list[MusicBrainzRelease]


class CoverArtResponse(_CamelModel):
    """Backend-relative URL pointing to a proxied cover art image."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, frozen=True)

    url: str
    mbid: str


# ---------------------------------------------------------------------------
# Custom Metadata
# ---------------------------------------------------------------------------


class CustomTrack(_CamelModel):
    """A user-defined track entry persisted in the local Custom Metadata Store."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, frozen=True)

    id: str
    title: str
    artist: str | None = None
    album: str | None = None
    year: int | None = None
    genre: str | None = None
    source_query: str | None = None
    youtube_id: str | None = None
    created_at: datetime


class CustomMetadataSuggestion(_CamelModel):
    """A tagging suggestion sourced exclusively from the local Custom Metadata Store."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, frozen=True)

    source: Literal["custom"] = "custom"
    confidence: float
    track: CustomTrack


# ---------------------------------------------------------------------------
# System
# ---------------------------------------------------------------------------


class _SearchMetrics(_CamelModel):
    """Aggregated performance counters for the search subsystem."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, frozen=True)

    count: int
    avg_duration_ms: float
    p95_duration_ms: float


class _DownloadMetrics(_CamelModel):
    """Aggregated performance counters for the download subsystem."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, frozen=True)

    count: int
    avg_duration_ms: float
    total_bytes: int


class _TaggingMetrics(_CamelModel):
    """Aggregated performance counters for the tagging subsystem."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, frozen=True)

    count: int
    avg_beets_confidence: float
    source_breakdown: dict[str, int]


class SystemMetrics(_CamelModel):
    """Snapshot of runtime performance and health data for the settings screen."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, frozen=True)

    search: _SearchMetrics
    download: _DownloadMetrics
    tagging: _TaggingMetrics
    ytdlp_version: str
    gc_last_run: datetime
    raw_folder_size_bytes: int


class ClientErrorReport(_CamelModel):
    """Frontend error payload posted to the backend error-collection endpoint."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, frozen=True)

    request_id: str
    error: str
    stack: str
    component: str | None = None
    route: str
    user_agent: str
    timestamp: datetime


class YtdlpUpdateStatus(_CamelModel):
    """Result of a yt-dlp auto-update or manual update attempt."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, frozen=True)

    current_version: str
    updated: bool
    new_version: str | None = None


# ---------------------------------------------------------------------------
# Plugin
# ---------------------------------------------------------------------------


class PluginManifest(_CamelModel):
    """Declaration of a source plugin's identity, capabilities, and supported formats."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, frozen=True)

    id: str
    name: str
    version: str
    base_url: str
    capabilities: list[PluginCapability]
    search_input: list[PluginSearchInput]
    audio_formats: list[str]
    icon: str
