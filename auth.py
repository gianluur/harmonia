"""
backend/auth.py

Pure authentication functions — no I/O, no database, no FastAPI.
Every function here is independently unit-testable in under 2ms.

Provides:
  hash_password(plain)              → bcrypt hash string
  verify_password(plain, hashed)    → bool
  encode_jwt(payload)               → signed JWT string
  decode_jwt(token)                 → decoded payload dict
  encode_stream_token(job_id)       → signed stream token string
  decode_stream_token(token,job_id) → decoded payload dict

Errors:
  TokenExpiredError    — raised by decode_jwt / decode_stream_token on expiry
  TokenInvalidError    — raised on bad signature, malformed token, wrong job

All datetimes are UTC. Never call datetime.now() without tz=UTC.
JWT algorithm: HS256 (HMAC-SHA256) — matches Architecture §10 ADR.
bcrypt cost factor: 12 — matches Architecture §10 ADR.
Stream token expiry: 10 minutes — matches Architecture §9.3.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from jose import ExpiredSignatureError, JWTError, jwt
from passlib.context import CryptContext

from backend.config import settings

# ---------------------------------------------------------------------------
# bcrypt context
# ---------------------------------------------------------------------------

_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto", bcrypt__rounds=12)

# ---------------------------------------------------------------------------
# Custom exceptions
# ---------------------------------------------------------------------------


class TokenExpiredError(Exception):
    """Raised when a JWT or stream token has passed its expiry time."""


class TokenInvalidError(Exception):
    """
    Raised when a token has an invalid signature, is malformed, or
    (for stream tokens) does not match the expected job_id.
    """


# ---------------------------------------------------------------------------
# Password hashing
# ---------------------------------------------------------------------------


def hash_password(plain: str) -> str:
    """
    Hash a plain-text password with bcrypt (cost factor 12).
    Returns a string that can be stored directly in the config table.

    Never store or log the plain-text password after calling this.
    """
    return _pwd_context.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    """
    Return True if plain matches the bcrypt hash, False otherwise.
    Constant-time comparison — safe against timing attacks.
    """
    return _pwd_context.verify(plain, hashed)


# ---------------------------------------------------------------------------
# JWT (session tokens — stored in httpOnly cookie)
# ---------------------------------------------------------------------------

_JWT_ALGORITHM = "HS256"


def encode_jwt(payload: dict[str, Any]) -> str:
    """
    Encode a JWT signed with JWT_SECRET using HS256.

    The caller is responsible for including an 'exp' key in the payload.
    Standard usage from auth_router.py:

        expires_at = datetime.now(UTC) + timedelta(days=settings.jwt_expiry_days)
        token = encode_jwt({"sub": username, "exp": expires_at})

    Returns the encoded token string.
    """
    return jwt.encode(payload, settings.jwt_secret, algorithm=_JWT_ALGORITHM)


def decode_jwt(token: str) -> dict[str, Any]:
    """
    Decode and verify a JWT signed with JWT_SECRET.

    Raises:
        TokenExpiredError   — token exp has passed
        TokenInvalidError   — signature invalid, token malformed, or any other
                              jose.JWTError

    Returns the decoded payload dict on success.
    """
    try:
        return jwt.decode(token, settings.jwt_secret, algorithms=[_JWT_ALGORITHM])
    except ExpiredSignatureError as exc:
        raise TokenExpiredError("JWT has expired") from exc
    except JWTError as exc:
        raise TokenInvalidError(f"JWT is invalid: {exc}") from exc


# ---------------------------------------------------------------------------
# Stream tokens (ephemeral, scoped to a single job)
# ---------------------------------------------------------------------------

_STREAM_TOKEN_EXPIRY_MINUTES = 10
_STREAM_TOKEN_TYPE = "stream"


def encode_stream_token(job_id: str) -> str:
    """
    Issue a short-lived (10-minute) HMAC-SHA256 token scoped to job_id.
    Used by POST /api/acquire → returned in AcquireResponse.stream_token.
    Consumed by GET /api/stream/:job_id?token=<token>.

    The token payload includes:
      sub   — the job_id this token is valid for
      type  — "stream" (prevents JWT session tokens being used as stream tokens)
      exp   — 10 minutes from now (UTC)
    """
    expires_at = datetime.now(UTC) + timedelta(minutes=_STREAM_TOKEN_EXPIRY_MINUTES)
    payload = {
        "sub": job_id,
        "type": _STREAM_TOKEN_TYPE,
        "exp": expires_at,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=_JWT_ALGORITHM)


def decode_stream_token(token: str, *, expected_job_id: str) -> dict[str, Any]:
    """
    Decode and verify a stream token, asserting it is scoped to expected_job_id.

    Raises:
        TokenExpiredError   — token exp has passed
        TokenInvalidError   — signature invalid, malformed, wrong type,
                              or job_id mismatch (token for job A used for job B)

    Returns the decoded payload dict on success.

    The job_id check is security-critical: without it, a token issued for
    job A could be used to stream job B.
    """
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[_JWT_ALGORITHM])
    except ExpiredSignatureError as exc:
        raise TokenExpiredError("Stream token has expired") from exc
    except JWTError as exc:
        raise TokenInvalidError(f"Stream token is invalid: {exc}") from exc

    if payload.get("type") != _STREAM_TOKEN_TYPE:
        raise TokenInvalidError(
            "Token type mismatch: expected 'stream', "
            f"got '{payload.get('type')}'"
        )

    if payload.get("sub") != expected_job_id:
        raise TokenInvalidError(
            f"Stream token is scoped to job '{payload.get('sub')}', "
            f"not '{expected_job_id}'"
        )

    return payload
