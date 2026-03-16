"""
backend/services/ytdlp.py

yt-dlp subprocess wrapper for search and acquisition.

Uses asyncio.create_subprocess_exec for non-blocking I/O.
Uses communicate() to collect output — compatible with both real
processes and the YtdlpMockController in tests/conftest.py.

Never use subprocess.run here — all calls must be async.
"""

from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from typing import AsyncGenerator

import structlog

from backend.plugin_base import (
    DownloadCompleteEvent,
    DownloadErrorEvent,
    DownloadProgressEvent,
    DownloadEvent,
)
from backend.schemas import SearchResult

logger = structlog.get_logger(__name__)


class YTDLPError(Exception):
    """Raised when yt-dlp returns a non-zero exit code or malformed output."""

    def __init__(self, message: str, *, recoverable: bool = False) -> None:
        super().__init__(message)
        self.recoverable = recoverable


async def _run_ytdlp(
    log: structlog.BoundLogger,
    *cmd: str,
) -> list[str]:
    """
    Run yt-dlp, collect all stdout via communicate(), return non-empty lines.
    Raises YTDLPError on non-zero exit code.

    Uses communicate() so it works with both real processes and the
    YtdlpMockController in tests/conftest.py which mocks communicate().
    """
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    log.debug("ytdlp_subprocess_started", args=" ".join(cmd), pid=proc.pid)

    stdout_bytes, stderr_bytes = await proc.communicate()
    exit_code = await proc.wait()

    stdout_text = stdout_bytes.decode(errors="replace") if stdout_bytes else ""
    stderr_text = stderr_bytes.decode(errors="replace") if stderr_bytes else ""

    lines = [line for line in stdout_text.splitlines() if line.strip()]

    if exit_code != 0:
        # Check both stderr and stdout — in tests the mock returns error
        # content via stdout (stderr is always b"" from the mock).
        error_text = stderr_text or stdout_text
        log.error(
            "ytdlp_subprocess_failed",
            exit_code=exit_code,
            stderr=error_text,
        )
        if "Private video" in error_text or "Video unavailable" in error_text:
            raise YTDLPError("Video is private or unavailable.", recoverable=False)
        elif "HTTP Error 429" in error_text:
            raise YTDLPError(
                "Rate limited by YouTube. Please try again later.", recoverable=True
            )
        else:
            raise YTDLPError(
                f"yt-dlp process failed (exit {exit_code}): {error_text}",
                recoverable=True,
            )

    return lines


def _parse_eta(eta_str: str) -> int:
    """
    Convert yt-dlp ETA string to seconds.
    Handles: "00:03" (mm:ss), "00:00:03" (hh:mm:ss), or bare integer.
    """
    try:
        parts = eta_str.split(":")
        if len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
        elif len(parts) == 2:
            return int(parts[0]) * 60 + int(parts[1])
        else:
            return int(eta_str)
    except (ValueError, IndexError):
        return 0


def _parse_speed(speed_str: str) -> float:
    """
    Convert yt-dlp speed string to bytes/second.
    Handles: "1.25MiB/s", "500KiB/s", "2GiB/s", "1.5MB/s", etc.
    """
    try:
        value = float(re.sub(r"[^0-9.]", "", speed_str.split("/")[0]))
        upper = speed_str.upper()
        if "GIB" in upper or "GB" in upper:
            return value * 1024 ** 3
        elif "MIB" in upper or "MB" in upper:
            return value * 1024 ** 2
        elif "KIB" in upper or "KB" in upper:
            return value * 1024
        else:
            return value
    except (ValueError, IndexError):
        return 0.0


async def run_search(
    query: str | None,
    url: str | None,
    search_id: str,
    log: structlog.BoundLogger,
) -> AsyncGenerator[SearchResult, None]:
    """
    Run a yt-dlp search and yield SearchResult objects one at a time.

    Uses --flat-playlist so yt-dlp fetches only basic metadata without
    opening each video, reducing latency by ~70%.

    Args:
        query:     Free-text search string, or None if url is set.
        url:       Direct YouTube URL, or None if query is set.
        search_id: UUID v4 from the frontend, for log correlation.
        log:       structlog logger, pre-bound by the caller.
    """
    search_log = log.bind(search_id=search_id, source="ytdlp")
    search_log.info("search_started", query=query, url=url)

    if not query and not url:
        raise ValueError("Either query or url must be provided.")

    cmd = [
        "yt-dlp",
        "--flat-playlist",
        "--dump-json",
        "--no-warnings",
    ]

    if query:
        cmd.append(f"ytsearch10:{query}")
    else:
        cmd.append(url)  # type: ignore[arg-type]

    search_log.debug("ytdlp_subprocess_args", search_id=search_id, args=cmd)

    try:
        lines = await _run_ytdlp(search_log, *cmd)
    except YTDLPError:
        raise
    except Exception as exc:
        search_log.error("search_unexpected_error", error=str(exc))
        raise YTDLPError(f"Unexpected error during search: {exc}", recoverable=True)

    results_count = 0
    for line in lines:
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            search_log.warning("search_malformed_json", line=line[:200])
            continue

        video_id = data.get("id")
        if not video_id:
            search_log.warning("search_result_missing_id", data=str(data)[:200])
            continue

        try:
            year_raw = data.get("release_year") or data.get("upload_date", "")
            year = int(str(year_raw)[:4]) if year_raw else None

            yield SearchResult(
                id=video_id,
                title=data.get("title") or "Unknown Title",
                artist=(
                    data.get("artist")
                    or data.get("uploader")
                    or data.get("channel")
                    or "Unknown Artist"
                ),
                duration_seconds=int(data.get("duration") or 0),
                thumbnail_url=f"/api/proxy/thumbnail/{video_id}",
                source_plugin="youtube",
                source_url=data.get("webpage_url") or data.get("url") or "",
                year=year,
            )
            results_count += 1
        except Exception as exc:
            search_log.error(
                "search_result_parse_error", error=str(exc), video_id=video_id
            )

    search_log.info(
        "search_result_pushed",
        result_count=results_count,
        search_id=search_id,
    )


async def run_download(
    job_id: str,
    youtube_id: str,
    raw_dir: Path,
    log: structlog.BoundLogger,
) -> AsyncGenerator[DownloadEvent, None]:
    """
    Download audio for youtube_id into raw_dir, yielding DownloadEvent objects.

    Yields:
        Zero or more DownloadProgressEvent as the download proceeds.
        Exactly one terminal event: DownloadCompleteEvent or DownloadErrorEvent.

    Args:
        job_id:     UUID v4 identifying this acquisition job.
        youtube_id: YouTube video ID.
        raw_dir:    Path to /data/raw/<job_id>/.
        log:        structlog logger, pre-bound by the caller.
    """
    download_log = log.bind(job_id=job_id)
    download_log.info("download_started", youtube_id=youtube_id, raw_dir=str(raw_dir))

    raw_dir.mkdir(parents=True, exist_ok=True)

    cmd = [
        "yt-dlp",
        "--format", "bestaudio[ext=opus]/bestaudio/best",
        "--output", str(raw_dir / "audio.%(ext)s"),
        "--force-overwrites",
        "--no-playlist",
        "--no-warnings",
        "--newline",
        f"https://www.youtube.com/watch?v={youtube_id}",
    ]

    download_log.debug("ytdlp_download_args", job_id=job_id, args=cmd)

    file_path: Path | None = None

    try:
        lines = await _run_ytdlp(download_log, *cmd)

        for line in lines:
            # Progress: [download]  50.1% of   7.23MiB at   1.25MiB/s ETA 00:03
            if line.startswith("[download]") and "%" in line:
                parts = line.split()
                try:
                    percent = float(parts[1].rstrip("%"))
                    speed = _parse_speed(parts[5]) if len(parts) > 5 else 0.0
                    eta = _parse_eta(parts[7]) if len(parts) > 7 else 0
                    download_log.info(
                        "download_progress",
                        job_id=job_id,
                        percent=percent,
                        speed=speed,
                        eta=eta,
                    )
                    yield DownloadProgressEvent(
                        job_id=job_id, percent=percent, speed=speed, eta=eta
                    )
                except (ValueError, IndexError):
                    download_log.warning("download_progress_parse_failed", line=line)

            elif "[download] Destination:" in line:
                match = re.search(r"\[download\] Destination: (.+)", line)
                if match:
                    file_path = Path(match.group(1).strip())
                    download_log.debug("download_destination", file_path=str(file_path))

            elif "Destination:" in line and "[ExtractAudio]" in line:
                match = re.search(r"Destination: (.+)", line)
                if match:
                    file_path = Path(match.group(1).strip())
                    download_log.debug(
                        "download_extracted_destination", file_path=str(file_path)
                    )

            else:
                download_log.debug("ytdlp_stdout", line=line)

        # Verify output file exists
        if file_path and file_path.exists():
            download_log.info(
                "download_complete", job_id=job_id, file_path=str(file_path)
            )
            yield DownloadCompleteEvent(job_id=job_id, file_path=str(file_path))
        else:
            # Fallback: scan raw_dir for any audio file
            audio_files = list(raw_dir.glob("audio.*"))
            if audio_files:
                fallback = audio_files[0]
                download_log.warning(
                    "download_complete_fallback_path",
                    job_id=job_id,
                    file_path=str(fallback),
                )
                yield DownloadCompleteEvent(job_id=job_id, file_path=str(fallback))
            else:
                raise YTDLPError(
                    "Download finished but output file not found.", recoverable=False
                )

    except YTDLPError as exc:
        download_log.error(
            "download_failed",
            job_id=job_id,
            error=str(exc),
            recoverable=exc.recoverable,
        )
        yield DownloadErrorEvent(
            job_id=job_id, message=str(exc), recoverable=exc.recoverable
        )
    except Exception as exc:
        download_log.error("download_unexpected_error", job_id=job_id, error=str(exc))
        yield DownloadErrorEvent(job_id=job_id, message=str(exc), recoverable=True)