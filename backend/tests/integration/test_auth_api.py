# Integration tests for /api/auth/* — see Testing spec §4.1
"""
backend/tests/integration/test_auth_api.py

Integration tests for authentication endpoints.
Covers all 11 scenarios from Testing spec §4.1.

Fixtures used (all from conftest.py — never redefined here):
  client       — unauthenticated AsyncClient with fresh DB
  auth_client  — authenticated AsyncClient with JWT cookie set
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_setup_first_run(client: AsyncClient):
    """
    POST /api/auth/setup on empty DB returns 200, sets httpOnly cookie,
    GET /api/auth/status now returns configured:true.
    """
    # Ensure DB is empty — status should return configured: false
    status_resp = await client.get("/api/auth/status")
    assert status_resp.status_code == 200
    assert status_resp.json()["configured"] is False

    # Perform setup
    setup_resp = await client.post(
        "/api/auth/setup",
        json={"username": "admin", "password": "securepassword123"},
    )
    assert setup_resp.status_code == 200
    # Check cookie is set (httpx stores cookies automatically)
    assert "harmonia_token" in client.cookies
    # Cookie should be httpOnly (not accessible to JavaScript) but httpx doesn't expose that.
    # We'll trust the backend's set_cookie configuration.

    # Verify status now returns configured: true
    status_resp2 = await client.get("/api/auth/status")
    assert status_resp2.status_code == 200
    assert status_resp2.json()["configured"] is True


@pytest.mark.asyncio
async def test_setup_already_configured(client: AsyncClient):
    """
    POST /api/auth/setup when already configured returns 409 Conflict.
    """
    # First setup
    setup_resp = await client.post(
        "/api/auth/setup",
        json={"username": "admin", "password": "securepassword123"},
    )
    assert setup_resp.status_code == 200

    # Second setup should fail
    setup_resp2 = await client.post(
        "/api/auth/setup",
        json={"username": "another", "password": "different"},
    )
    assert setup_resp2.status_code == 409
    # Verify error envelope shape
    envelope = setup_resp2.json()["detail"]
    assert "error" in envelope
    assert "detail" in envelope
    assert "request_id" in envelope
    assert envelope["error"] == "already_configured"


@pytest.mark.asyncio
async def test_login_correct_credentials(client: AsyncClient):
    """
    POST /api/auth/login with correct creds returns 200 and sets JWT cookie.
    """
    # First, set up the account
    await client.post(
        "/api/auth/setup",
        json={"username": "admin", "password": "securepassword123"},
    )
    # Clear cookies (simulate fresh client) — but we can just use the same client
    # since cookies are already set; we need to test login after logout.
    # Let's clear the cookie manually by deleting the cookie jar entry.
    client.cookies.clear()
    # Now login with correct credentials
    login_resp = await client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "securepassword123"},
    )
    assert login_resp.status_code == 200
    assert "harmonia_token" in client.cookies


@pytest.mark.asyncio
async def test_login_wrong_password(client: AsyncClient):
    """
    POST /api/auth/login with wrong password returns 401.
    """
    # Set up account
    await client.post(
        "/api/auth/setup",
        json={"username": "admin", "password": "securepassword123"},
    )
    client.cookies.clear()
    # Wrong password
    login_resp = await client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "wrongpassword"},
    )
    assert login_resp.status_code == 401
    envelope = login_resp.json()["detail"]
    assert "error" in envelope
    assert envelope["error"] == "invalid_credentials"
    # Ensure no cookie set
    assert "harmonia_token" not in client.cookies


@pytest.mark.asyncio
async def test_protected_route_no_cookie(client: AsyncClient):
    """
    GET /api/jobs/pending without cookie returns 401.
    """
    # Ensure no cookie (client fixture starts fresh)
    resp = await client.get("/api/jobs/pending")
    assert resp.status_code == 401
    envelope = resp.json()["detail"]
    assert "error" in envelope
    assert envelope["error"] == "not_authenticated"


@pytest.mark.asyncio
async def test_protected_route_with_cookie(auth_client: AsyncClient):
    """
    GET /api/jobs/pending with valid JWT cookie returns 200.
    """
    resp = await auth_client.get("/api/jobs/pending")
    assert resp.status_code == 200
    # Expect empty list (no pending jobs)
    assert resp.json() == []


@pytest.mark.asyncio
async def test_protected_route_expired_cookie(client: AsyncClient):
    """
    GET /api/jobs/pending with expired JWT returns 401.
    """
    # Need to create an expired token. We can manipulate JWT secret?
    # Instead, we can rely on auth.py's TokenExpiredError being raised
    # when we pass a token with expired exp claim.
    # Let's generate an expired token using the same encode_jwt function.
    # Import backend.auth.encode_jwt
    from backend.auth import encode_jwt
    from datetime import UTC, datetime, timedelta

    expired_at = datetime.now(UTC) - timedelta(hours=1)
    token = encode_jwt({"sub": "admin", "exp": expired_at})
    # Set cookie on client
    client.cookies.set("harmonia_token", token)
    resp = await client.get("/api/jobs/pending")
    assert resp.status_code == 401
    envelope = resp.json()["detail"]
    assert "error" in envelope
    assert envelope["error"] == "token_expired"


@pytest.mark.asyncio
async def test_logout_clears_cookie(auth_client: AsyncClient):
    """
    POST /api/auth/logout sets cookie with max-age=0; subsequent protected request returns 401.
    """
    # auth_client already has a valid cookie
    logout_resp = await auth_client.post("/api/auth/logout")
    assert logout_resp.status_code == 204
    # Cookie should be cleared (max-age=0). httpx may remove it automatically.
    # Let's check that subsequent protected request fails
    resp = await auth_client.get("/api/jobs/pending")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_request_id_present_in_response_header(auth_client: AsyncClient):
    """
    Every authenticated response includes X-Request-ID header echoing the inbound value.
    """
    request_id = str(uuid.uuid4())
    resp = await auth_client.get(
        "/api/jobs/pending",
        headers={"X-Request-ID": request_id}
    )
    assert resp.status_code == 200
    assert resp.headers.get("X-Request-ID") == request_id


@pytest.mark.asyncio
async def test_request_id_generated_if_absent(client: AsyncClient):
    """
    Request with no X-Request-ID header → backend generates one; response header contains a valid UUID.
    """
    resp = await client.get("/api/auth/status")
    assert resp.status_code == 200
    request_id_header = resp.headers.get("X-Request-ID")
    assert request_id_header is not None
    # Validate it's a UUID v4
    try:
        uuid_obj = uuid.UUID(request_id_header, version=4)
        assert str(uuid_obj) == request_id_header
    except ValueError:
        pytest.fail(f"X-Request-ID header is not a valid UUID v4: {request_id_header}")


@pytest.mark.asyncio
async def test_error_envelope_shape(client: AsyncClient):
    """
    All error responses (4xx, 5xx) follow the same envelope shape:
    {"error": "machine_code", "detail": "human message", "request_id": "uuid"}.
    """
    # Trigger a 401 by accessing protected route without cookie
    resp = await client.get("/api/jobs/pending")
    assert resp.status_code == 401
    envelope = resp.json()["detail"]
    assert "error" in envelope
    assert "detail" in envelope
    assert "request_id" in envelope
    # request_id should be a valid UUID
    try:
        uuid.UUID(envelope["request_id"], version=4)
    except ValueError:
        pytest.fail(f"request_id is not a valid UUID v4: {envelope['request_id']}")
    # Ensure error is a string
    assert isinstance(envelope["error"], str)
    assert isinstance(envelope["detail"], str)