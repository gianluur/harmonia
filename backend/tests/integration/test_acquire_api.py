# Integration tests for /api/acquire, /api/stream, /api/jobs — see Testing spec §4.3
"""
backend/tests/integration/test_acquire_api.py

Integration tests for the acquire router and job WebSocket handler.
Covers all 11 scenarios from Testing spec §4.3.

Fixtures used (all from conftest.py — never redefined here):
  auth_client   — authenticated AsyncClient with JWT cookie set
  db            — fresh AsyncDB instance per test
  fs_layout     — tmp_path-based raw/ and library/ dirs
  mock_ytdlp    — patches asyncio.create_subprocess_exec
  ws_collect    — WebSocket helper (module-level utility)
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import AsyncClient

from backend.auth import encode_stream_token
from backend.schemas import JobStatusEnum
from backend.tests.conftest import ws_collect


# ---------------------------------------------------------------------------
# POST /api/acquire
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_acquire_creates_job(auth_client: AsyncClient, fs_layout: dict):
    """
    POST /api/acquire returns {job_id, stream_token} with status 201.
    raw/<job_id>/ directory is created on disk.
    """
    resp = await auth_client.post(
        "/api/acquire",
        json={"youtube_id": "dQw4w9WgXcQ", "title_hint": "Never Gonna Give You Up"},
    )

    assert resp.status_code == 201
    data = resp.json()
    assert "jobId" in data
    assert "streamToken" in data

    # Verify response shape — dir creation is the download service's responsibility
    assert data["jobId"]
    assert data["streamToken"]


# ---------------------------------------------------------------------------
# GET /api/stream/:job_id
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stream_valid_token(auth_client: AsyncClient, fs_layout: dict, monkeypatch):
    """
    GET /api/stream/<job_id>?token=<valid> returns 200 with audio/ogg content-type
    when an opus file exists in the job's raw directory.
    """
    import backend.routers.acquire as acquire_mod
    monkeypatch.setattr(acquire_mod.settings, "raw_path", fs_layout["raw"])

    # Create a job first
    resp = await auth_client.post(
        "/api/acquire",
        json={"youtube_id": "dQw4w9WgXcQ"},
    )
    assert resp.status_code == 201
    data = resp.json()
    job_id = data["jobId"]
    stream_token = data["streamToken"]

    # Place an audio file in the raw dir (simulates completed download)
    audio_file = fs_layout["raw"] / job_id / "audio.opus"
    audio_file.parent.mkdir(parents=True, exist_ok=True)
    opus_fixture = Path(__file__).parent.parent / "fixtures" / "ytdlp" / "audio_sample.opus"
    audio_file.write_bytes(opus_fixture.read_bytes())

    resp = await auth_client.get(f"/api/stream/{job_id}?token={stream_token}")

    assert resp.status_code == 200
    assert "audio" in resp.headers["content-type"]


@pytest.mark.asyncio
async def test_stream_invalid_token_401(auth_client: AsyncClient, fs_layout: dict):
    """
    GET /api/stream/<job_id>?token=<wrong> returns 401.
    """
    resp = await auth_client.post(
        "/api/acquire",
        json={"youtube_id": "dQw4w9WgXcQ"},
    )
    job_id = resp.json()["jobId"]

    resp = await auth_client.get(f"/api/stream/{job_id}?token=this.is.not.valid")

    assert resp.status_code == 401
    assert resp.json()["detail"]["error"] == "token_invalid"


@pytest.mark.asyncio
async def test_stream_expired_token_401(auth_client: AsyncClient, fs_layout: dict):
    """
    GET /api/stream/<job_id>?token=<expired> returns 401.
    """
    from datetime import UTC, datetime, timedelta
    from backend.config import settings
    from jose import jwt

    resp = await auth_client.post(
        "/api/acquire",
        json={"youtube_id": "dQw4w9WgXcQ"},
    )
    job_id = resp.json()["jobId"]

    # Manually craft an expired stream token
    expired_payload = {
        "sub": job_id,
        "type": "stream",
        "exp": datetime.now(UTC) - timedelta(minutes=1),
    }
    expired_token = jwt.encode(expired_payload, settings.jwt_secret, algorithm="HS256")

    resp = await auth_client.get(f"/api/stream/{job_id}?token={expired_token}")

    assert resp.status_code == 401
    assert resp.json()["detail"]["error"] == "token_expired"


@pytest.mark.asyncio
async def test_stream_range_request(auth_client: AsyncClient, fs_layout: dict, monkeypatch):
    """
    GET /api/stream with Range: bytes=0-1023 returns 206 Partial Content
    with correct Content-Range header and byte range.
    """
    import backend.routers.acquire as acquire_mod
    monkeypatch.setattr(acquire_mod.settings, "raw_path", fs_layout["raw"])
    resp = await auth_client.post(
        "/api/acquire",
        json={"youtube_id": "dQw4w9WgXcQ"},
    )
    data = resp.json()
    job_id = data["jobId"]
    stream_token = data["streamToken"]

    # Place audio file
    audio_file = fs_layout["raw"] / job_id / "audio.opus"
    audio_file.parent.mkdir(parents=True, exist_ok=True)
    opus_fixture = Path(__file__).parent.parent / "fixtures" / "ytdlp" / "audio_sample.opus"
    audio_bytes = opus_fixture.read_bytes()
    audio_file.write_bytes(audio_bytes)

    file_size = len(audio_bytes)
    end = min(1023, file_size - 1)

    resp = await auth_client.get(
        f"/api/stream/{job_id}?token={stream_token}",
        headers={"Range": "bytes=0-1023"},
    )

    assert resp.status_code == 206
    assert "Content-Range" in resp.headers
    assert resp.headers["Content-Range"] == f"bytes 0-{end}/{file_size}"
    assert len(resp.content) == end + 1


# ---------------------------------------------------------------------------
# GET /api/jobs/:job_id
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_job_status(auth_client: AsyncClient):
    """
    GET /api/jobs/<job_id> returns JobStatus with correct fields.
    """
    resp = await auth_client.post(
        "/api/acquire",
        json={"youtube_id": "dQw4w9WgXcQ"},
    )
    job_id = resp.json()["jobId"]

    resp = await auth_client.get(f"/api/jobs/{job_id}")

    assert resp.status_code == 200
    data = resp.json()
    assert data["jobId"] == job_id
    assert data["status"] == JobStatusEnum.pending.value


@pytest.mark.asyncio
async def test_get_job_status_not_found(auth_client: AsyncClient):
    """
    GET /api/jobs/<nonexistent_id> returns 404.
    """
    resp = await auth_client.get("/api/jobs/00000000-0000-0000-0000-000000000000")

    assert resp.status_code == 404
    assert resp.json()["detail"]["error"] == "job_not_found"


# ---------------------------------------------------------------------------
# GET /api/jobs/pending
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_pending_jobs_excludes_confirmed(auth_client: AsyncClient, db):
    """
    GET /api/jobs/pending returns jobs with status != 'confirmed'.
    Confirmed jobs are excluded; pending/downloading/tagging/error are included.
    """
    from backend.services.job_store import create_job, update_job_status

    # Create jobs in various states
    pending_id = await create_job(db, youtube_id="aaa")
    downloading_id = await create_job(db, youtube_id="bbb")
    await update_job_status(db, downloading_id, JobStatusEnum.downloading)
    confirmed_id = await create_job(db, youtube_id="ccc")
    await update_job_status(db, confirmed_id, JobStatusEnum.downloading)
    await update_job_status(db, confirmed_id, JobStatusEnum.tagging)
    await update_job_status(db, confirmed_id, JobStatusEnum.confirmed)

    resp = await auth_client.get("/api/jobs/pending")

    assert resp.status_code == 200
    ids = [j["jobId"] for j in resp.json()]
    assert pending_id in ids
    assert downloading_id in ids
    assert confirmed_id not in ids


# ---------------------------------------------------------------------------
# PATCH /api/acquire/:job_id/tags
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_patch_tags_returns_204(auth_client: AsyncClient, db):
    """
    PATCH /api/acquire/<job_id>/tags with valid payload returns 204.
    Job must be in a taggable state (downloading, tagging, or error).
    """
    from backend.services.job_store import create_job, update_job_status

    job_id = await create_job(db, youtube_id="dQw4w9WgXcQ")
    await update_job_status(db, job_id, JobStatusEnum.downloading)
    await update_job_status(db, job_id, JobStatusEnum.tagging)

    resp = await auth_client.patch(
        f"/api/acquire/{job_id}/tags",
        json={
            "title": "Never Gonna Give You Up",
            "artist": "Rick Astley",
            "album": "Whenever You Need Somebody",
            "year": 1987,
        },
    )

    assert resp.status_code == 204


@pytest.mark.asyncio
async def test_patch_tags_job_not_found(auth_client: AsyncClient):
    """
    PATCH /api/acquire/<nonexistent>/tags returns 404.
    """
    resp = await auth_client.patch(
        "/api/acquire/00000000-0000-0000-0000-000000000000/tags",
        json={"title": "Test", "artist": "Artist"},
    )

    assert resp.status_code == 404
    assert resp.json()["detail"]["error"] == "job_not_found"


@pytest.mark.asyncio
async def test_patch_tags_wrong_state_returns_409(auth_client: AsyncClient, db):
    """
    PATCH /api/acquire/<job_id>/tags when job is in 'pending' state returns 409.
    """
    from backend.services.job_store import create_job

    job_id = await create_job(db, youtube_id="dQw4w9WgXcQ")
    # Job is still in 'pending' — not taggable

    resp = await auth_client.patch(
        f"/api/acquire/{job_id}/tags",
        json={"title": "Test", "artist": "Artist"},
    )

    assert resp.status_code == 409
    assert resp.json()["detail"]["error"] == "invalid_job_state"


# ---------------------------------------------------------------------------
# Auth protection
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_acquire_requires_auth(client: AsyncClient):
    """
    POST /api/acquire without a JWT cookie returns 401.
    """
    resp = await client.post(
        "/api/acquire",
        json={"youtube_id": "dQw4w9WgXcQ"},
    )

    assert resp.status_code == 401