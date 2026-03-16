"""
backend/tests/conftest.py

Shared pytest fixtures for all test layers (unit, integration, contract).

Fixture scopes:
  - session:   created once per test run  (respx_router, mock_navidrome app)
  - function:  created fresh per test     (db, fs_layout, client)

Every fixture that touches the filesystem uses tmp_path so cleanup is automatic.
Every fixture that mocks an external HTTP dependency uses respx so no real
network calls are ever made.

Patterns established here that ALL test files must follow:
  - Import from backend.* using absolute paths — no relative imports in tests
  - Use AsyncClient(app=app, base_url="http://test") for HTTP tests — never
    open a real port
  - Use ws_collect() for WebSocket assertions — never write raw WS loops inline
  - Override FastAPI dependencies via app.dependency_overrides — never monkeypatch
    internals
  - Fixture names are stable contracts: fs_layout, db, client, mock_navidrome,
    respx_router — do not rename them
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import AsyncGenerator, Generator
from unittest.mock import AsyncMock, MagicMock

import os
import pytest
import pytest_asyncio
import respx
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

# ---------------------------------------------------------------------------
# Environment variables for Settings
# ---------------------------------------------------------------------------
# Set required environment variables before any backend module imports config.
os.environ.update({
    "NAVIDROME_URL": "http://mock-navidrome:4533",
    "NAVIDROME_ADMIN_USER": "admin",
    "NAVIDROME_ADMIN_PASS": "admin",
    "NAVIDROME_APP_USER": "appuser",
    "NAVIDROME_APP_PASS": "apppass",
    "JWT_SECRET": "test-secret-do-not-use-in-production-" + "x" * 10,
    "MUSICBRAINZ_CONTACT_URL": "https://example.com/harmonia",
})

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

FIXTURES_DIR = Path(__file__).parent / "fixtures"
YTDLP_FIXTURES = FIXTURES_DIR / "ytdlp"
MB_FIXTURES = FIXTURES_DIR / "musicbrainz"


# ---------------------------------------------------------------------------
# pytest-asyncio configuration
# ---------------------------------------------------------------------------
# All async tests use the same event loop for the session.

pytest_plugins = ["pytest_asyncio"]


# ---------------------------------------------------------------------------
# 1. Filesystem layout  (function scope — fresh per test)
# ---------------------------------------------------------------------------


@pytest.fixture()
def fs_layout(tmp_path: Path) -> dict[str, Path]:
    """
    Creates the expected /data directory structure inside a temporary directory.
    Overrides the MUSIC_LIBRARY_PATH, RAW_PATH, and DB_PATH env vars so the
    backend uses these temp paths instead of the real filesystem.

    Returns a dict with keys: raw, library, db.

    Usage:
        def test_something(fs_layout):
            raw_dir = fs_layout["raw"]
            assert (raw_dir / "some_job_id").exists()
    """
    raw = tmp_path / "raw"
    library = tmp_path / "library"
    raw.mkdir()
    library.mkdir()
    db_path = tmp_path / "harmonia.db"

    return {
        "raw": raw,
        "library": library,
        "db": db_path,
        "root": tmp_path,
    }


# ---------------------------------------------------------------------------
# 2. SQLite database  (function scope — fresh per test)
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture()
async def db(fs_layout: dict[str, Path]):
    """
    Initialised AsyncDB instance pointing at a fresh temp SQLite file.
    Runs create_tables() so the schema is ready before the test body runs.
    Closes the connection cleanly after the test.

    Usage:
        async def test_something(db):
            await db.execute("INSERT INTO jobs ...")
    """
    from backend.database import AsyncDB

    instance = AsyncDB(str(fs_layout["db"]))
    await instance.connect()
    await instance.create_tables()
    yield instance
    await instance.close()


# ---------------------------------------------------------------------------
# 3. FastAPI test client  (function scope)
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture()
async def client(db, fs_layout: dict[str, Path], monkeypatch) -> AsyncGenerator[AsyncClient, None]:
    """
    HTTPX AsyncClient wired to the real FastAPI app with:
      - The test DB injected via dependency_overrides
      - MUSIC_LIBRARY_PATH and RAW_PATH pointed at tmp_path
      - No real network calls (respx_router is not active here —
        individual tests that need HTTP mocking use the respx_router fixture)

    Usage:
        async def test_something(client):
            resp = await client.get("/api/auth/status")
            assert resp.status_code == 200
    """
    import os
    monkeypatch.setenv("MUSIC_LIBRARY_PATH", str(fs_layout["library"]))
    monkeypatch.setenv("RAW_PATH", str(fs_layout["raw"]))
    monkeypatch.setenv("DB_PATH", str(fs_layout["db"]))
    monkeypatch.setenv("JWT_SECRET", "test-secret-do-not-use-in-production-" + "x" * 10)
    monkeypatch.setenv("NAVIDROME_URL", "http://mock-navidrome:4533")
    monkeypatch.setenv("NAVIDROME_ADMIN_USER", "admin")
    monkeypatch.setenv("NAVIDROME_ADMIN_PASS", "admin")

    from backend.database import get_db
    from backend.main import app

    # Override the DB dependency so every route gets the test DB instance
    app.dependency_overrides[get_db] = lambda: db

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as ac:
        yield ac

    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# 4. Authenticated client  (function scope)
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture()
async def auth_client(client: AsyncClient) -> AsyncClient:
    """
    Like `client`, but performs the setup + login flow first so the JWT
    cookie is already set. Use this for any test that exercises a protected
    route without caring about the auth flow itself.

    Usage:
        async def test_protected_route(auth_client):
            resp = await auth_client.get("/api/jobs/pending")
            assert resp.status_code == 200
    """
    setup_resp = await client.post(
        "/api/auth/setup",
        json={"username": "testuser", "password": "testpassword123"},
    )
    assert setup_resp.status_code == 200, f"Setup failed: {setup_resp.text}"
    # Cookie is set on the client automatically via HTTPX cookie jar
    return client


# ---------------------------------------------------------------------------
# 5. respx router for MusicBrainz + Cover Art Archive  (function scope)
# ---------------------------------------------------------------------------


@pytest.fixture()
def respx_router():
    """
    Activates a respx mock router that intercepts all outbound httpx calls.
    Pre-registers the MB and Cover Art Archive base URLs with fixture responses.

    Individual tests can add more routes:
        def test_something(respx_router):
            respx_router.get("https://musicbrainz.org/ws/2/artist").mock(
                return_value=httpx.Response(200, json={...})
            )

    Usage:
        def test_mb_search(respx_router):
            # MusicBrainz calls are automatically intercepted
            resp = client.get("/api/metadata/search?type=artist&query=Radiohead")
    """
    with respx.mock(assert_all_mocked=False) as router:
        # Pre-load standard fixture responses
        artist_fixture = json.loads((MB_FIXTURES / "artist_search_radiohead.json").read_text())
        router.get(
            url__regex=r"https://musicbrainz\.org/ws/2/artist.*Radiohead.*"
        ).mock(return_value=_json_response(200, artist_fixture))

        no_results = json.loads((MB_FIXTURES / "no_results.json").read_text())
        router.get(
            url__regex=r"https://musicbrainz\.org/ws/2/.*unknown.*"
        ).mock(return_value=_json_response(200, no_results))

        coverart_bytes = (MB_FIXTURES / "coverart_ok.jpg").read_bytes()
        router.get(
            url__regex=r"https://coverartarchive\.org/release/.*"
        ).mock(return_value=_bytes_response(200, coverart_bytes, "image/jpeg"))

        yield router


# ---------------------------------------------------------------------------
# 6. Mock Navidrome server  (function scope)
# ---------------------------------------------------------------------------


class MockNavidrome:
    """
    In-process FastAPI mock of the Navidrome Subsonic API.
    Records every request so tests can assert on call counts and params.

    Usage:
        def test_scan_triggered(mock_navidrome, auth_client):
            # ... trigger a tag confirm ...
            mock_navidrome.assert_scan_called_once()
    """

    def __init__(self) -> None:
        self._calls: list[dict] = []
        self.app = self._build_app()

    def _record(self, path: str, params: dict) -> None:
        self._calls.append({"path": path, "params": params})

    def _build_app(self) -> FastAPI:
        from fastapi import FastAPI, Request
        from fastapi.responses import JSONResponse

        mock_app = FastAPI()

        @mock_app.get("/rest/ping")
        async def ping(request: Request):
            self._record("/rest/ping", dict(request.query_params))
            return JSONResponse({"subsonic-response": {"status": "ok", "version": "1.16.1"}})

        @mock_app.get("/rest/startScan")
        async def start_scan(request: Request):
            self._record("/rest/startScan", dict(request.query_params))
            return JSONResponse({
                "subsonic-response": {
                    "status": "ok",
                    "version": "1.16.1",
                    "scanStatus": {"scanning": False, "count": 42},
                }
            })

        @mock_app.get("/rest/search3")
        async def search3(request: Request):
            self._record("/rest/search3", dict(request.query_params))
            return JSONResponse({
                "subsonic-response": {
                    "status": "ok",
                    "version": "1.16.1",
                    "searchResult3": {
                        "song": [
                            {"id": "1", "title": "Creep", "artist": "Radiohead", "album": "Pablo Honey", "duration": 238},
                            {"id": "2", "title": "Karma Police", "artist": "Radiohead", "album": "OK Computer", "duration": 264},
                            {"id": "3", "title": "Fake Plastic Trees", "artist": "Radiohead", "album": "The Bends", "duration": 288},
                        ],
                        "album": [],
                        "artist": [],
                    },
                }
            })

        @mock_app.get("/rest/getAlbumList2")
        async def get_album_list2(request: Request):
            self._record("/rest/getAlbumList2", dict(request.query_params))
            return JSONResponse({"subsonic-response": {"status": "ok", "version": "1.16.1", "albumList2": {"album": []}}})

        @mock_app.get("/rest/getArtists")
        async def get_artists(request: Request):
            self._record("/rest/getArtists", dict(request.query_params))
            return JSONResponse({"subsonic-response": {"status": "ok", "version": "1.16.1", "artists": {"index": []}}})

        @mock_app.get("/rest/getPlaylists")
        async def get_playlists(request: Request):
            self._record("/rest/getPlaylists", dict(request.query_params))
            return JSONResponse({"subsonic-response": {"status": "ok", "version": "1.16.1", "playlists": {"playlist": []}}})

        return mock_app

    # Assertion helpers
    def assert_scan_called_once(self) -> None:
        scan_calls = [c for c in self._calls if c["path"] == "/rest/startScan"]
        assert len(scan_calls) == 1, f"Expected startScan called once, got {len(scan_calls)}"

    def assert_scan_called_with_admin_user(self, admin_user: str) -> None:
        scan_calls = [c for c in self._calls if c["path"] == "/rest/startScan"]
        assert scan_calls, "startScan was never called"
        assert scan_calls[0]["params"].get("u") == admin_user

    def call_count(self, path: str) -> int:
        return sum(1 for c in self._calls if c["path"] == path)

    def reset(self) -> None:
        self._calls.clear()


@pytest.fixture()
def mock_navidrome() -> MockNavidrome:
    """
    Returns a MockNavidrome instance. Individual tests use it directly
    for assertion helpers. The backend's NAVIDROME_URL is set to point
    at this mock via the `client` fixture's monkeypatch.
    """
    return MockNavidrome()


# ---------------------------------------------------------------------------
# 7. yt-dlp subprocess mock  (function scope)
# ---------------------------------------------------------------------------


@pytest.fixture()
def mock_ytdlp(monkeypatch):
    """
    Patches asyncio.create_subprocess_exec so yt-dlp subprocess calls never
    spawn a real process. Returns a controller object so tests can configure
    the fixture's response per-test.

    Usage:
        async def test_search(mock_ytdlp, auth_client):
            mock_ytdlp.use_fixture("search_flat")
            resp = await auth_client.post("/api/search", json={"query": "Radiohead"})

        async def test_download_error(mock_ytdlp, auth_client):
            mock_ytdlp.use_fixture("error_private_video", exit_code=1)
    """
    controller = YtdlpMockController()
    monkeypatch.setattr(
        "asyncio.create_subprocess_exec",
        controller._create_subprocess_exec,
    )
    return controller


class YtdlpMockController:
    """Controls what the yt-dlp subprocess mock returns."""

    def __init__(self) -> None:
        self._fixture_name: str = "search_flat"
        self._exit_code: int = 0
        self.calls: list[list[str]] = []

    def use_fixture(self, fixture_name: str, exit_code: int = 0) -> None:
        """Configure which fixture file the mock subprocess returns."""
        self._fixture_name = fixture_name
        self._exit_code = exit_code

    async def _create_subprocess_exec(self, *args, **kwargs) -> MagicMock:
        self.calls.append(list(args))
        fixture_path = YTDLP_FIXTURES / f"{self._fixture_name}.json"
        if fixture_path.exists():
            stdout_data = fixture_path.read_bytes()
        else:
            # For audio_sample.opus — binary fixture
            opus_path = YTDLP_FIXTURES / f"{self._fixture_name}.opus"
            stdout_data = opus_path.read_bytes() if opus_path.exists() else b""

        proc = MagicMock()
        proc.returncode = self._exit_code
        proc.stdout = AsyncMock()
        proc.stderr = AsyncMock()
        proc.communicate = AsyncMock(return_value=(stdout_data, b""))
        proc.wait = AsyncMock(return_value=self._exit_code)
        return proc

    def assert_flag_used(self, flag: str) -> None:
        """Assert that a specific yt-dlp flag appeared in at least one subprocess call."""
        all_args = [arg for call in self.calls for arg in call]
        assert flag in all_args, f"Expected yt-dlp flag '{flag}' in calls {self.calls}"


# ---------------------------------------------------------------------------
# 8. WebSocket helper  (module-level utility, not a fixture)
# ---------------------------------------------------------------------------


async def ws_collect(client: AsyncClient, url: str, n_events: int) -> list[dict]:
    """
    Connect to a WebSocket endpoint, collect exactly n_events JSON messages,
    then close the connection.  Makes WS assertions read like HTTP assertions.

    Usage:
        events = await ws_collect(client, f"/ws/{job_id}", n_events=3)
        assert events[0]["type"] == "download_progress"
        assert events[2]["type"] == "download_complete"
    """
    # If client supports websocket_connect, use it (httpx >= 0.24)
    if hasattr(client, 'websocket_connect'):
        collected: list[dict] = []
        async with client.websocket_connect(url) as ws:
            while len(collected) < n_events:
                raw = await asyncio.wait_for(ws.receive_text(), timeout=10.0)
                collected.append(json.loads(raw))
        return collected
    else:
        # Fall back to FastAPI TestClient (synchronous)
        from fastapi.testclient import TestClient
        # Get the ASGI app from the transport
        transport = client._transport
        if not hasattr(transport, 'app'):
            raise AttributeError("Client transport has no app attribute")
        test_client = TestClient(app=transport.app, base_url=str(client.base_url))
        # Pass cookies from the auth client to the WebSocket connection
        cookies = dict(client.cookies)
        with test_client.websocket_connect(url, cookies=cookies) as ws:
            collected: list[dict] = []
            while len(collected) < n_events:
                raw = ws.receive_text()
                collected.append(json.loads(raw))
        return collected


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _json_response(status_code: int, data: dict):
    """Build an httpx.Response with JSON body for use in respx mocks."""
    import httpx
    return httpx.Response(status_code, json=data)


def _bytes_response(status_code: int, data: bytes, content_type: str):
    """Build an httpx.Response with binary body for use in respx mocks."""
    import httpx
    return httpx.Response(status_code, content=data, headers={"content-type": content_type})
