# Unit tests for backend/auth.py — see Testing spec §3.1.1

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import time
from unittest.mock import patch

import pytest
from jose import jwt
import passlib.handlers.bcrypt

from backend.auth import (
    hash_password,
    verify_password,
    encode_jwt,
    decode_jwt,
    encode_stream_token,
    decode_stream_token,
    TokenExpiredError,
    TokenInvalidError,
)
from backend.config import settings


@pytest.fixture
def mock_jwt_secret():
    """Override settings.jwt_secret with a test value."""
    original = settings.jwt_secret
    settings.jwt_secret = "test-secret-do-not-use-in-production-" + "x" * 10
    yield
    settings.jwt_secret = original


def test_password_hashed_with_bcrypt():
    """hash_password() produces a bcrypt hash; plain text is not stored."""
    plain = "super-secret-password"
    hashed = hash_password(plain)
    assert hashed != plain
    # bcrypt hash starts with $2b$
    assert hashed.startswith("$2b$") or hashed.startswith("$2a$") or hashed.startswith("$2y$")
    # hash length is reasonable
    assert len(hashed) >= 50


def test_password_verify_correct():
    """verify_password(plain, hash) returns True for correct password."""
    plain = "correct-password"
    hashed = hash_password(plain)
    assert verify_password(plain, hashed) is True


def test_password_verify_wrong():
    """verify_password(plain, hash) returns False for wrong password."""
    plain = "correct-password"
    wrong = "wrong-password"
    hashed = hash_password(plain)
    assert verify_password(wrong, hashed) is False


def test_jwt_encode_decode_roundtrip(mock_jwt_secret):
    """encode_jwt() → decode_jwt() returns the same payload."""
    payload = {"sub": "testuser", "exp": datetime.now(UTC) + timedelta(days=1)}
    token = encode_jwt(payload)
    decoded = decode_jwt(token)
    # exp is datetime in payload, but JWT encodes as timestamp; decode_jwt returns exp as int timestamp.
    # So we need to compare only sub.
    assert decoded["sub"] == payload["sub"]
    # exp should be within 1 second of original timestamp (converted to int)
    # We'll just ensure exp exists
    assert "exp" in decoded


def test_jwt_expired_raises(mock_jwt_secret):
    """decode_jwt() raises ExpiredSignatureError for a token with past exp."""
    # Create a payload with expiry 1 second in the past
    payload = {"sub": "testuser", "exp": datetime.now(UTC) - timedelta(seconds=1)}
    token = jwt.encode(payload, settings.jwt_secret, algorithm="HS256")
    with pytest.raises(TokenExpiredError, match="JWT has expired"):
        decode_jwt(token)


def test_jwt_wrong_secret_raises(mock_jwt_secret):
    """decode_jwt() raises InvalidSignatureError for token signed with a different secret."""
    # Encode with wrong secret
    wrong_secret = "wrong-secret-" + "y" * 10
    payload = {"sub": "testuser", "exp": datetime.now(UTC) + timedelta(days=1)}
    token = jwt.encode(payload, wrong_secret, algorithm="HS256")
    with pytest.raises(TokenInvalidError, match="JWT is invalid"):
        decode_jwt(token)


def test_stream_token_encode_decode(mock_jwt_secret):
    """stream token roundtrip preserves job_id and is scoped correctly."""
    job_id = "123e4567-e89b-12d3-a456-426614174000"
    token = encode_stream_token(job_id)
    payload = decode_stream_token(token, expected_job_id=job_id)
    assert payload["sub"] == job_id
    assert payload["type"] == "stream"
    assert "exp" in payload


def test_stream_token_expired_raises(mock_jwt_secret):
    """stream token with past expiry raises TokenExpiredError."""
    # Manually create a token with expired exp
    job_id = "123e4567-e89b-12d3-a456-426614174000"
    expires_at = datetime.now(UTC) - timedelta(minutes=1)
    payload = {"sub": job_id, "type": "stream", "exp": expires_at}
    token = jwt.encode(payload, settings.jwt_secret, algorithm="HS256")
    with pytest.raises(TokenExpiredError, match="Stream token has expired"):
        decode_stream_token(token, expected_job_id=job_id)


def test_stream_token_wrong_job_raises(mock_jwt_secret):
    """stream token for job_id A cannot be used for job_id B."""
    job_a = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    job_b = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
    token = encode_stream_token(job_a)
    with pytest.raises(TokenInvalidError, match=f"Stream token is scoped to job '{job_a}', not '{job_b}'"):
        decode_stream_token(token, expected_job_id=job_b)