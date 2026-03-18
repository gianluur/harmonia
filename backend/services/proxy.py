"""
backend/services/proxy.py

Backend proxy for external metadata services (MusicBrainz, Cover Art Archive).
Strips identifying headers per Architecture §9.1, enforces 5-second timeout.
"""

from __future__ import annotations

import httpx
from typing import Literal
import structlog

from backend.config import settings
from backend.schemas import (
    MusicBrainzArtist,
    MusicBrainzRelease,
    MusicBrainzRecording,
)

# ------------------------------------------------------------------------------
# Header sanitisation
# ------------------------------------------------------------------------------


def sanitise_headers(in_headers: dict[str, str]) -> dict[str, str]:
    """
    Strip identifying headers from outbound proxy requests and replace User-Agent.

    Removes:
        - Referer
        - X-Forwarded-For
        - X-Real-IP
        - Cookie
        - Authorization

    Replaces User-Agent with the controlled Harmonia string from settings.

    Preserves safe headers like Accept, Accept-Language, Content-Type.

    Returns a new dict; does not modify the input.
    """
    out = {}
    for key, value in in_headers.items():
        lower = key.lower()
        if lower in {
            "referer",
            "x-forwarded-for",
            "x-real-ip",
            "cookie",
            "authorization",
        }:
            continue
        out[key] = value

    # Override User-Agent
    out["User-Agent"] = settings.musicbrainz_user_agent
    return out


# ------------------------------------------------------------------------------
# MusicBrainz proxy
# ------------------------------------------------------------------------------


async def search_musicbrainz(
    log: structlog.BoundLogger,
    entity_type: Literal["artist", "release", "recording"],
    query: str,
) -> list[MusicBrainzArtist | MusicBrainzRelease | MusicBrainzRecording]:
    """
    Search MusicBrainz for artists, releases or recordings.

    Args:
        log: structured logger for the request
        entity_type: which MusicBrainz entity to search for
        query: search term

    Returns:
        List of matching entities, already validated against our Pydantic schemas.

    Raises:
        httpx.TimeoutException: if the request exceeds 5 seconds
        httpx.HTTPStatusError: if MusicBrainz returns a non‑2xx status
        ValueError: if entity_type is unrecognised or the response cannot be mapped
    """
    # Build the MB URL (MusicBrainz expects query parameter 'query')
    url = f"https://musicbrainz.org/ws/2/{entity_type}"
    params = {"query": query, "fmt": "json"}

    # Prepare headers: only Accept, Accept-Language, User-Agent (via sanitise_headers)
    headers = sanitise_headers({"Accept": "application/json"})

    timeout = httpx.Timeout(5.0, connect=5.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        log.debug(
            "musicbrainz_proxy_request",
            url=url,
            params=params,
            entity_type=entity_type,
            query=query,
        )
        response = await client.get(url, params=params, headers=headers)
        response.raise_for_status()
        data = response.json()

    # MusicBrainz returns a dict with a key "artists", "releases" or "recordings"
    key = f"{entity_type}s"
    if key not in data:
        raise ValueError(f"MusicBrainz response missing expected key '{key}'")

    items = data[key]
    if not isinstance(items, list):
        raise ValueError(f"MusicBrainz key '{key}' is not a list")

    # Map each item to the appropriate Pydantic model
    if entity_type == "artist":
        return [MusicBrainzArtist(**item) for item in items]
    elif entity_type == "release":
        return [MusicBrainzRelease(**item) for item in items]
    elif entity_type == "recording":
        # MusicBrainz recordings have an "artist-credit" field; we map it to artist_credit
        # and a "releases" list that we map to our MusicBrainzRelease schema.
        mapped = []
        for item in items:
            # Extract artist-credit as a simple string (first artist name)
            artist_credit = None
            if "artist-credit" in item and len(item["artist-credit"]) > 0:
                artist_credit = item["artist-credit"][0].get("name")

            # Extract releases
            releases = []
            for rel in item.get("releases", []):
                releases.append(
                    MusicBrainzRelease(
                        mbid=rel.get("id"),
                        title=rel.get("title"),
                        date=rel.get("date"),
                        track_count=rel.get("track-count"),
                    )
                )

            mapped.append(
                MusicBrainzRecording(
                    mbid=item.get("id"),
                    title=item.get("title"),
                    artist_credit=artist_credit,
                    releases=releases,
                )
            )
        return mapped
    else:
        raise ValueError(f"Unsupported entity_type: {entity_type}")


# ------------------------------------------------------------------------------
# Cover Art Archive proxy
# ------------------------------------------------------------------------------


async def get_coverart(
    log: structlog.BoundLogger,
    mbid: str,
) -> bytes:
    """
    Fetch cover art for a MusicBrainz release MBID from the Cover Art Archive.

    Args:
        log: structured logger for the request
        mbid: MusicBrainz Release MBID (UUID)

    Returns:
        Raw image bytes (JPEG or PNG). The caller is responsible for setting the
        correct Content‑Type header.

    Raises:
        httpx.TimeoutException: if the request exceeds 5 seconds
        httpx.HTTPStatusError: if Cover Art Archive returns a non‑2xx status
    """
    # Cover Art Archive endpoint for the front‑cover of a release
    url = f"https://coverartarchive.org/release/{mbid}/front"

    headers = sanitise_headers({"Accept": "image/*"})
    timeout = httpx.Timeout(5.0, connect=5.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        log.debug("coverart_proxy_request", url=url, mbid=mbid)
        response = await client.get(url, headers=headers)
        response.raise_for_status()
        return response.content