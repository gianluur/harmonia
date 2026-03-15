"""
backend/config.py

Application configuration — single source of truth for every env var.

All environment variables are defined in .env.example with descriptions.
Copy .env.example to .env and fill in values before running.

Usage anywhere in the backend:
    from backend.config import settings
    print(settings.jwt_secret)
    print(settings.music_library_path)

Never call os.environ or os.getenv directly outside this file.
Never import settings inside a function — import at module level so missing
vars fail loudly at startup, not mid-request.

The `settings` singleton at the bottom of this file is the only instance
that should ever be created. It is safe to import from multiple modules.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Reads configuration from environment variables (and .env file if present).
    All fields map 1-to-1 to the variables documented in .env.example and
    Architecture spec §8.2.

    Required fields (no default) will raise a ValidationError at startup
    if not set — this is intentional. A missing JWT_SECRET or NAVIDROME_URL
    should crash immediately, not silently produce broken behaviour.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",        # ignore unknown env vars — don't crash on typos
    )

    # ----------------------------------------------------------------
    # Navidrome
    # ----------------------------------------------------------------

    navidrome_url: str
    """Internal Navidrome URL for rescan API calls. Example: http://navidrome:4533"""

    navidrome_admin_user: str
    """Admin Navidrome account — backend only, used exclusively for startScan."""

    navidrome_admin_pass: str
    """Admin Navidrome password."""

    navidrome_app_user: str
    """Non-admin Navidrome account — frontend Subsonic API user."""

    navidrome_app_pass: str
    """Non-admin Navidrome password."""

    # ----------------------------------------------------------------
    # JWT & Security
    # ----------------------------------------------------------------

    jwt_secret: str
    """
    Random secret for signing JWTs and stream tokens (HMAC-SHA256).
    Generate with: openssl rand -hex 32
    Must be at least 32 characters.
    """

    jwt_expiry_days: int = 30
    """JWT lifetime in days. Default: 30."""

    # ----------------------------------------------------------------
    # File paths
    # ----------------------------------------------------------------

    music_library_path: Path = Path("/data/library")
    """Absolute path to Navidrome music root."""

    raw_path: Path = Path("/data/raw")
    """Absolute path to in-progress download staging folder."""

    db_path: Path = Path("/data/custom_metadata.db")
    """Absolute path to the SQLite database file."""

    # ----------------------------------------------------------------
    # Workers
    # ----------------------------------------------------------------

    gc_raw_max_age_hours: int = 48
    """Hours before unconfirmed raw/ folders are deleted by the GC worker."""

    # ----------------------------------------------------------------
    # Logging
    # ----------------------------------------------------------------

    log_level: str = "INFO"
    """Structlog level: DEBUG | INFO | WARNING | ERROR"""

    log_format: str = "pretty"
    """Structlog renderer: json (production) | pretty (development)"""

    # ----------------------------------------------------------------
    # Server
    # ----------------------------------------------------------------

    host: str = "0.0.0.0"
    port: int = 8000

    # ----------------------------------------------------------------
    # MusicBrainz
    # ----------------------------------------------------------------

    musicbrainz_app_name: str = "Harmonia"
    """App name component of the outbound User-Agent header."""

    musicbrainz_contact_url: str
    """
    Contact URL included in User-Agent per MusicBrainz API policy.
    Example: https://github.com/yourname/harmonia
    """

    # ----------------------------------------------------------------
    # Validators
    # ----------------------------------------------------------------

    @field_validator("jwt_secret")
    @classmethod
    def jwt_secret_must_be_long_enough(cls, v: str) -> str:
        if len(v) < 32:
            raise ValueError(
                "JWT_SECRET must be at least 32 characters. "
                "Generate one with: openssl rand -hex 32"
            )
        return v

    @field_validator("log_level")
    @classmethod
    def log_level_must_be_valid(cls, v: str) -> str:
        valid = {"DEBUG", "INFO", "WARNING", "ERROR"}
        upper = v.upper()
        if upper not in valid:
            raise ValueError(f"LOG_LEVEL must be one of {valid}, got '{v}'")
        return upper

    @field_validator("log_format")
    @classmethod
    def log_format_must_be_valid(cls, v: str) -> str:
        valid = {"json", "pretty"}
        lower = v.lower()
        if lower not in valid:
            raise ValueError(f"LOG_FORMAT must be one of {valid}, got '{v}'")
        return lower

    # ----------------------------------------------------------------
    # Computed properties
    # ----------------------------------------------------------------

    @property
    def musicbrainz_user_agent(self) -> str:
        """
        Full User-Agent string sent to MusicBrainz and Cover Art Archive.
        Format required by MusicBrainz API policy:
        AppName/version (description; +contact_url)
        """
        return (
            f"{self.musicbrainz_app_name}/1.0 "
            f"(self-hosted music platform; +{self.musicbrainz_contact_url})"
        )


# ---------------------------------------------------------------------------
# Singleton — import this everywhere
# ---------------------------------------------------------------------------

settings = Settings()  # type: ignore[call-arg]
# type: ignore above because required fields have no default — mypy sees
# them as missing args, but pydantic-settings reads them from env at runtime.
