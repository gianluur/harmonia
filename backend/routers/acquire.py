"""
backend/routers/acquire.py

Acquisition, streaming, and job management endpoints:
  POST  /api/acquire                  — start a new acquisition job → 201
  GET   /api/stream/:job_id           — chunked audio stream with Range support
  GET   /api/jobs/pending             — list all jobs awaiting tag confirmation
  GET   /api/jobs/:job_id             — get job status
  PATCH /api/acquire/:job_id/tags     — submit confirmed tags → 204

Patterns followed from backend/routers/auth.py:
  - Every route has explicit response_model and status_code
  - No business logic in route functions — call a service, return its result
  - All errors: {"error": machine_code, "detail": human message, "request_id": uuid}
  - structlog bound per-request via log = logger.bind(**); never module logger in routes
  - Database access only through Depends(get_db)
  - All datetimes UTC; never datetime.now() without UTC

Stream endpoint notes:
  - Validates stream token via decode_stream_token(token, expected_job_id=job_id)
  - Supports Range header → 206 Partial Content
  - Streams from /data/raw/<job_id>/audio.* (any extension yt-dlp chose)
  - Returns 404 if the file does not exist yet (download not started)
  - Does NOT require JWT cookie — uses the ephemeral stream token instead

GET /api/jobs/pending note (from TASKS.md):
  - Returns status != 'confirmed' (all active/in-progress jobs), not just 'pending'
"""

from __future__ import annotations

import os
from datetime import datetime, UTC
from pathlib import Path
from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import StreamingResponse

from backend.auth import (
    TokenExpiredError,
    TokenInvalidError,
    decode_stream_token,
    encode_stream_token,
)
from backend.database import AsyncDB, get_db
from backend.schemas import (
    AcquireRequest,
    AcquireResponse,
    JobStatus,
    JobStatusEnum,
    TagPayload,
)
from backend.services.job_store import create_job, get_job, list_pending_jobs
from backend.routers.auth import require_auth
from backend.config import settings

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api", tags=["acquire"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _find_audio_file(job_raw_dir: Path) -> Path | None:
    """
    Scan the job's raw directory for any audio file yt-dlp wrote.
    yt-dlp chooses the extension based on format (opus, webm, m4a, etc.).
    Returns the first match, or None if nothing exists yet.
    """
    for ext in ("opus", "webm", "m4a", "mp3", "ogg", "flac", "wav"):
        candidate = job_raw_dir / f"audio.{ext}"
        if candidate.exists():
            return candidate
    # Fallback: any file named audio.*
    matches = list(job_raw_dir.glob("audio.*"))
    return matches[0] if matches else None


def _parse_range_header(range_header: str, file_size: int) -> tuple[int, int]:
    """
    Parse a Range: bytes=<start>-<end> header.
    Returns (start, end) as inclusive byte offsets clamped to file_size.
    Raises ValueError on malformed headers.
    """
    if not range_header.startswith("bytes="):
        raise ValueError("Only byte ranges are supported")
    range_spec = range_header[len("bytes="):]
    parts = range_spec.split("-")
    if len(parts) != 2:
        raise ValueError(f"Malformed range spec: {range_spec}")

    start_str, end_str = parts
    start = int(start_str) if start_str else 0
    end = int(end_str) if end_str else file_size - 1
    end = min(end, file_size - 1)
    return start, end


async def _stream_file(
    file_path: Path,
    start: int,
    end: int,
    chunk_size: int = 65536,
):
    """Async generator that yields file bytes from start to end (inclusive)."""
    remaining = end - start + 1
    with open(file_path, "rb") as f:
        f.seek(start)
        while remaining > 0:
            chunk = f.read(min(chunk_size, remaining))
            if not chunk:
                break
            remaining -= len(chunk)
            yield chunk


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.post(
    "/acquire",
    response_model=AcquireResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Start a new acquisition job",
)
async def post_acquire(
    body: AcquireRequest,
    request: Request,
    db: Annotated[AsyncDB, Depends(get_db)],
    auth: Annotated[dict, Depends(require_auth)],
) -> AcquireResponse:
    """
    Creates a new acquisition job for the given YouTube ID.

    Returns job_id and a short-lived stream token (10-minute expiry)
    that authorises streaming from GET /api/stream/:job_id.

    The actual download is started by the acquire service (called separately
    by the WebSocket handler after this returns).
    """
    log = logger.bind(
        youtube_id=body.youtube_id,
        path="/api/acquire",
        username=auth.get("sub"),
    )
    log.info("acquire_requested", title_hint=body.title_hint)

    # Create raw directory for this job
    job_id = await create_job(db, youtube_id=body.youtube_id, title_hint=body.title_hint)

    job_id = await create_job(db, youtube_id=body.youtube_id, title_hint=body.title_hint)
    stream_token = encode_stream_token(job_id)

    log.info("acquire_job_created", job_id=job_id)
    return AcquireResponse(job_id=job_id, stream_token=stream_token)


@router.get(
    "/stream/{job_id}",
    status_code=status.HTTP_200_OK,
    summary="Stream audio for an acquisition job",
    # No response_model — returns a StreamingResponse
)
async def get_stream(
    job_id: str,
    request: Request,
    token: str | None = None,
) -> StreamingResponse:
    """
    Streams the audio file for a job.

    Authentication: ephemeral stream token passed as ?token=<token> query param
    (not a JWT cookie — the HTML5 <audio> element cannot set headers).

    Supports Range requests → 206 Partial Content for seek support.
    Returns 401 for missing/invalid/expired token.
    Returns 404 if the audio file doesn't exist yet.
    """
    log = logger.bind(job_id=job_id, path=f"/api/stream/{job_id}")

    # --- Validate stream token ---
    if not token:
        log.warning("stream_missing_token")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "error": "missing_token",
                "detail": "Stream token is required.",
                "request_id": request.state.request_id,
            },
        )

    try:
        decode_stream_token(token, expected_job_id=job_id)
    except TokenExpiredError:
        log.warning("stream_token_expired")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "error": "token_expired",
                "detail": "Stream token has expired.",
                "request_id": request.state.request_id,
            },
        )
    except TokenInvalidError:
        log.warning("stream_token_invalid")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "error": "token_invalid",
                "detail": "Invalid stream token.",
                "request_id": request.state.request_id,
            },
        )

    # --- Locate the audio file ---
    job_raw_dir = settings.raw_path / job_id
    audio_file = _find_audio_file(job_raw_dir)

    if audio_file is None:
        log.warning("stream_file_not_found", raw_dir=str(job_raw_dir))
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": "file_not_found",
                "detail": "Audio file not available yet.",
                "request_id": request.state.request_id,
            },
        )

    file_size = audio_file.stat().st_size

    # Determine content type from extension
    ext = audio_file.suffix.lstrip(".")
    content_type_map = {
        "opus": "audio/ogg",
        "ogg": "audio/ogg",
        "webm": "audio/webm",
        "m4a": "audio/mp4",
        "mp3": "audio/mpeg",
        "flac": "audio/flac",
        "wav": "audio/wav",
    }
    content_type = content_type_map.get(ext, "application/octet-stream")

    # --- Handle Range request ---
    range_header = request.headers.get("range")

    if range_header:
        try:
            start, end = _parse_range_header(range_header, file_size)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "error": "invalid_range",
                    "detail": str(exc),
                    "request_id": request.state.request_id,
                },
            )

        content_length = end - start + 1
        log.debug(
            "stream_range_request",
            start=start,
            end=end,
            content_length=content_length,
        )

        headers = {
            "Content-Range": f"bytes {start}-{end}/{file_size}",
            "Accept-Ranges": "bytes",
            "Content-Length": str(content_length),
            "Cache-Control": "no-store",
        }
        return StreamingResponse(
            _stream_file(audio_file, start, end),
            status_code=status.HTTP_206_PARTIAL_CONTENT,
            media_type=content_type,
            headers=headers,
        )

    # --- Full file response ---
    log.debug("stream_full_request", file_size=file_size)
    headers = {
        "Accept-Ranges": "bytes",
        "Content-Length": str(file_size),
        "Cache-Control": "no-store",
    }
    return StreamingResponse(
        _stream_file(audio_file, 0, file_size - 1),
        status_code=status.HTTP_200_OK,
        media_type=content_type,
        headers=headers,
    )


@router.get(
    "/jobs/pending",
    response_model=list[JobStatus],
    status_code=status.HTTP_200_OK,
    summary="List all jobs awaiting tag confirmation",
)
async def get_pending_jobs(
    request: Request,
    db: Annotated[AsyncDB, Depends(get_db)],
    auth: Annotated[dict, Depends(require_auth)],
) -> list[JobStatus]:
    """
    Returns all jobs whose status is NOT 'confirmed' — i.e. every job that
    is still active, in progress, or waiting for user action.

    This powers the "Pending" tray in the frontend that shows jobs awaiting
    tag confirmation.

    Delegates to list_pending_jobs() in job_store.py which encodes the
    status != 'confirmed' query logic.
    """
    log = logger.bind(path="/api/jobs/pending", username=auth.get("sub"))

    rows = await list_pending_jobs(db)

    jobs = [
        JobStatus(
            job_id=row["id"],
            status=JobStatusEnum(row["status"]),
            percent=row["percent"],
            error_message=row["error_message"],
            created_at=row["created_at"],
        )
        for row in rows
    ]

    log.debug("pending_jobs_listed", count=len(jobs))
    return jobs


@router.get(
    "/jobs/{job_id}",
    response_model=JobStatus,
    status_code=status.HTTP_200_OK,
    summary="Get status of a specific acquisition job",
)
async def get_job_status(
    job_id: str,
    request: Request,
    db: Annotated[AsyncDB, Depends(get_db)],
    auth: Annotated[dict, Depends(require_auth)],
) -> JobStatus:
    """
    Returns the current status of a job.
    Returns 404 if the job does not exist.
    """
    log = logger.bind(job_id=job_id, path=f"/api/jobs/{job_id}", username=auth.get("sub"))

    row = await get_job(db, job_id)
    if row is None:
        log.warning("job_not_found")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": "job_not_found",
                "detail": f"Job {job_id} does not exist.",
                "request_id": request.state.request_id,
            },
        )

    log.debug("job_status_fetched", status=row["status"])
    return JobStatus(
        job_id=job_id,
        status=JobStatusEnum(row["status"]),
        percent=row["percent"],
        error_message=row["error_message"],
        created_at=row["created_at"],
    )


@router.patch(
    "/acquire/{job_id}/tags",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Submit confirmed tags for a job",
)
async def patch_tags(
    job_id: str,
    body: TagPayload,
    request: Request,
    db: Annotated[AsyncDB, Depends(get_db)],
    auth: Annotated[dict, Depends(require_auth)],
) -> Response:
    """
    Accepts finalised tag metadata for a job and triggers the tagging pipeline:
      1. Write ID3/Vorbis tags to the audio file (via tagger service)
      2. Move file from /data/raw/<job_id>/ to /data/library/<Artist>/<Album>/
      3. Trigger Navidrome rescan
      4. Push library_ready WebSocket event

    Returns 204 No Content on success.
    Returns 404 if the job does not exist.
    Returns 409 if the job is not in a taggable state.

    Note: tagging pipeline services (tagger, navidrome) are implemented in
    Phase 2. This endpoint currently validates and acknowledges the request.
    """
    log = logger.bind(
        job_id=job_id,
        path=f"/api/acquire/{job_id}/tags",
        username=auth.get("sub"),
    )

    row = await get_job(db, job_id)
    if row is None:
        log.warning("patch_tags_job_not_found")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": "job_not_found",
                "detail": f"Job {job_id} does not exist.",
                "request_id": request.state.request_id,
            },
        )

    # Only jobs that have completed downloading can be tagged
    current_status = JobStatusEnum(row["status"])
    taggable = {JobStatusEnum.tagging, JobStatusEnum.downloading, JobStatusEnum.error}
    if current_status not in taggable:
        log.warning("patch_tags_invalid_state", current_status=current_status.value)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "invalid_job_state",
                "detail": (
                    f"Job is in state '{current_status.value}' and cannot be tagged. "
                    f"Expected one of: {[s.value for s in taggable]}"
                ),
                "request_id": request.state.request_id,
            },
        )

    # Phase 2: tagger service will be called here.
    # For now: acknowledge the request and log the payload.
    log.info(
        "patch_tags_received",
        title=body.title,
        artist=body.artist,
        album=body.album,
    )

    # Return 204 No Content
    return Response(status_code=status.HTTP_204_NO_CONTENT)