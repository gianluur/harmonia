# Unit tests for backend/services/proxy.py — see Testing spec §3.1.3

from __future__ import annotations

import pytest

from backend.services.proxy import sanitise_headers
from backend.config import settings


def test_referer_stripped() -> None:
    """sanitise_headers() removes Referer from outbound request headers."""
    input_headers = {
        "Referer": "https://example.com/page",
        "Accept": "application/json",
        "User-Agent": "Mozilla/5.0",
    }
    output = sanitise_headers(input_headers)
    assert "Referer" not in output
    assert output["Accept"] == "application/json"
    assert output["User-Agent"] == settings.musicbrainz_user_agent


def test_forwarded_for_stripped() -> None:
    """sanitise_headers() removes X-Forwarded-For and X-Real-IP."""
    input_headers = {
        "X-Forwarded-For": "192.168.1.1",
        "X-Real-IP": "10.0.0.1",
        "Accept": "application/json",
        "User-Agent": "Mozilla/5.0",
    }
    output = sanitise_headers(input_headers)
    assert "X-Forwarded-For" not in output
    assert "X-Real-IP" not in output
    assert output["Accept"] == "application/json"
    assert output["User-Agent"] == settings.musicbrainz_user_agent


def test_user_agent_replaced() -> None:
    """sanitise_headers() replaces User-Agent with the controlled Harmonia string."""
    input_headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept-Language": "en-US,en;q=0.9",
    }
    output = sanitise_headers(input_headers)
    assert output["User-Agent"] == settings.musicbrainz_user_agent
    assert output["Accept-Language"] == "en-US,en;q=0.9"


def test_auth_header_stripped() -> None:
    """sanitise_headers() removes Authorization and Cookie headers."""
    input_headers = {
        "Authorization": "Bearer secret-token",
        "Cookie": "sessionid=abc123; csrftoken=def456",
        "Accept": "application/json",
        "User-Agent": "Mozilla/5.0",
    }
    output = sanitise_headers(input_headers)
    assert "Authorization" not in output
    assert "Cookie" not in output
    assert output["Accept"] == "application/json"
    assert output["User-Agent"] == settings.musicbrainz_user_agent


def test_safe_headers_preserved() -> None:
    """Accept and Accept-Language headers are preserved unchanged."""
    input_headers = {
        "Accept": "application/json",
        "Accept-Language": "en-US,en;q=0.9",
        "Content-Type": "application/json",
        "Referer": "https://example.com",  # will be stripped
        "User-Agent": "Mozilla/5.0",
    }
    output = sanitise_headers(input_headers)
    assert output["Accept"] == "application/json"
    assert output["Accept-Language"] == "en-US,en;q=0.9"
    assert output["Content-Type"] == "application/json"
    assert "Referer" not in output
    assert output["User-Agent"] == settings.musicbrainz_user_agent