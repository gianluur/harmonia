"""
backend/routers/auth.py

Authentication endpoints:
  GET  /api/auth/status   — check whether first-run setup has been completed
  POST /api/auth/setup    — first-run: create the single admin account
  POST /api/auth/login    — exchange credentials for a JWT cookie
  POST /api/auth/logout   — clear the JWT cookie

All routes in this file are PUBLIC (no JWT required).
JWT-protected routes live in the other routers and use the `require_auth`
dependency defined at the bottom of this file.

Patterns established here that ALL other routers must follow:
  - Import order: stdlib → third-party → local
  - Every route has an explicit response_model and status_code
  - Errors always raise HTTPException with detail matching the error envelope
    shape: {"error": <machine_code>, "detail": <human message>, "request_id": <uuid>}
  - structlog is bound per-request via `log = logger.bind(**)`; never use the
    module-level logger directly in route functions
  - Database access only through the `get_db` dependency; never open a
    connection manually inside a route
  - No business logic in route functions — call a service function, return its result
  - All datetime values are UTC; never use datetime.now(), always datetime.now(UTC)
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated

import structlog
from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response, status
from fastapi.security import OAuth2PasswordBearer

from backend.auth import (
    TokenExpiredError,
    TokenInvalidError,
    decode_jwt,
    encode_jwt,
    hash_password,
    verify_password,
)
from backend.database import AsyncDB, get_db
from backend.schemas import AuthStatus, LoginRequest, SetupRequest, TokenResponse

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/auth", tags=["auth"])

# ---------------------------------------------------------------------------
# Cookie name — single source of truth used by all routers
# ---------------------------------------------------------------------------

COOKIE_NAME = "harmonia_token"
COOKIE_MAX_AGE_SECONDS = 30 * 24 * 60 * 60  # 30 days, matches JWT_EXPIRY_DAYS default


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _set_auth_cookie(response: Response, token: str) -> None:
    """Write the JWT as an httpOnly, SameSite=Lax cookie on the response."""
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        max_age=COOKIE_MAX_AGE_SECONDS,
        httponly=True,
        samesite="lax",
        secure=False,  # Set to True in production behind HTTPS
    )


def _clear_auth_cookie(response: Response) -> None:
    """Expire the JWT cookie immediately."""
    response.set_cookie(
        key=COOKIE_NAME,
        value="",
        max_age=0,
        httponly=True,
        samesite="lax",
    )


async def _is_configured(db: AsyncDB) -> bool:
    """Return True if the config table has a username row (first-run setup is done)."""
    row = await db.fetchone(
        "SELECT value FROM config WHERE key = 'username'"
    )
    return row is not None


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get(
    "/status",
    response_model=AuthStatus,
    status_code=status.HTTP_200_OK,
    summary="Check whether first-run setup has been completed",
)
async def get_auth_status(
    db: Annotated[AsyncDB, Depends(get_db)],
) -> AuthStatus:
    """
    Returns { configured: false } on a fresh install, which causes the
    frontend to redirect to /setup.  Returns { configured: true } thereafter.
    This endpoint is intentionally public — it contains no sensitive data.
    """
    configured = await _is_configured(db)
    return AuthStatus(configured=configured)


@router.post(
    "/setup",
    response_model=TokenResponse,
    status_code=status.HTTP_200_OK,
    summary="First-run setup: create the admin account",
)
async def setup(
    body: SetupRequest,
    request: Request,
    response: Response,
    db: Annotated[AsyncDB, Depends(get_db)],
) -> TokenResponse:
    """
    Creates the single admin account and issues a JWT cookie.
    Returns 409 if setup has already been completed.
    Can never be called again after the first successful invocation.
    """
    log = logger.bind(username=body.username, path="/api/auth/setup")

    if await _is_configured(db):
        log.warning("setup_already_configured")
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "already_configured",
                "detail": "Setup has already been completed. Use /api/auth/login.",
                "request_id": request.state.request_id,
            },
        )

    password_hash = hash_password(body.password)
    await db.execute(
        "INSERT INTO config (key, value) VALUES ('username', ?), ('password_hash', ?)",
        (body.username, password_hash),
    )

    expires_at = datetime.now(UTC) + timedelta(days=30)
    token = encode_jwt({"sub": body.username, "exp": expires_at})
    token_response = TokenResponse(
        access_token=token,
        token_type="bearer",
        expires_at=expires_at,
    )

    _set_auth_cookie(response, token)
    log.info("first_run_setup_complete")
    return token_response


@router.post(
    "/login",
    response_model=TokenResponse,
    status_code=status.HTTP_200_OK,
    summary="Exchange credentials for a JWT cookie",
)
async def login(
    body: LoginRequest,
    request: Request,
    response: Response,
    db: Annotated[AsyncDB, Depends(get_db)],
) -> TokenResponse:
    """
    Verifies username + bcrypt password hash.
    On success, issues a fresh 30-day JWT cookie.
    Returns 401 for wrong credentials (deliberately vague — no user enumeration).
    """
    log = logger.bind(
        username=body.username,
        ip=request.client.host if request.client else "unknown",
        path="/api/auth/login",
    )

    username_row = await db.fetchone(
        "SELECT value FROM config WHERE key = 'username'"
    )
    hash_row = await db.fetchone(
        "SELECT value FROM config WHERE key = 'password_hash'"
    )

    credentials_valid = (
        username_row is not None
        and hash_row is not None
        and username_row["value"] == body.username
        and verify_password(body.password, hash_row["value"])
    )

    if not credentials_valid:
        reason = (
            "user_not_found"
            if username_row is None or username_row["value"] != body.username
            else "wrong_password"
        )
        log.warning("login_failed", reason=reason)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "error": "invalid_credentials",
                "detail": "Username or password is incorrect.",
                "request_id": request.state.request_id,
            },
        )

    expires_at = datetime.now(UTC) + timedelta(days=30)
    token = encode_jwt({"sub": body.username, "exp": expires_at})
    token_response = TokenResponse(
        access_token=token,
        token_type="bearer",
        expires_at=expires_at,
    )

    _set_auth_cookie(response, token)
    log.info("login_success")
    return token_response


@router.post(
    "/logout",
    response_model=None,
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Clear the JWT cookie",
)
async def logout(
    request: Request,
    response: Response,
    db: Annotated[AsyncDB, Depends(get_db)],
) -> None:
    """
    Expires the JWT cookie. No server-side token revocation — the cookie
    expiry is the logout mechanism. Requires a valid JWT cookie to call
    (prevents unauthenticated logout spam from poisoning logs).
    """
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "error": "not_authenticated",
                "detail": "No active session.",
                "request_id": request.state.request_id,
            },
        )

    try:
        payload = decode_jwt(token)
    except (TokenExpiredError, TokenInvalidError) as exc:
        # Even an expired token gets a clean logout — just clear the cookie.
        logger.bind(path="/api/auth/logout").debug("logout_with_invalid_token", reason=str(exc))
        _clear_auth_cookie(response)
        return

    _clear_auth_cookie(response)
    logger.bind(username=payload.get("sub"), path="/api/auth/logout").info("logout")


# ---------------------------------------------------------------------------
# JWT dependency — used by ALL other routers
# ---------------------------------------------------------------------------
#
# Usage in any protected router:
#
#   from backend.routers.auth import require_auth
#
#   @router.get("/something")
#   async def something(
#       auth: Annotated[dict, Depends(require_auth)],
#       db: Annotated[AsyncDB, Depends(get_db)],
#   ) -> ...:
#       username = auth["sub"]
#
# The dependency reads the JWT from the cookie, validates it, and returns
# the decoded payload. Raises 401 on any auth failure — expired, missing,
# tampered. Never raises 403 (single-user app, no permission tiers).
# ---------------------------------------------------------------------------


async def require_auth(
    request: Request,
    harmonia_token: Annotated[str | None, Cookie()] = None,
) -> dict:
    """
    FastAPI dependency. Validates the JWT cookie and returns the decoded payload.
    Raises HTTP 401 for missing, expired, or invalid tokens.

    Bind this to a route with: auth: Annotated[dict, Depends(require_auth)]
    """
    log = logger.bind(path=request.url.path)

    if harmonia_token is None:
        log.warning("jwt_validation_failed", reason="missing")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "error": "not_authenticated",
                "detail": "Authentication required. Please log in.",
                "request_id": request.state.request_id,
            },
        )

    try:
        payload = decode_jwt(harmonia_token)
    except TokenExpiredError:
        log.warning("jwt_validation_failed", reason="expired")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "error": "token_expired",
                "detail": "Your session has expired. Please log in again.",
                "request_id": request.state.request_id,
            },
        )
    except TokenInvalidError:
        log.warning("jwt_validation_failed", reason="invalid_signature")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "error": "token_invalid",
                "detail": "Invalid authentication token.",
                "request_id": request.state.request_id,
            },
        )

    return payload
