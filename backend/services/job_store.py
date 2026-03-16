"""
backend/services/job_store.py

Job state machine and database CRUD operations.

Enforces legal status transitions:
  pending → downloading → tagging → confirmed
  any → error
  error → pending (recoverable errors only)

Raises StateTransitionError for illegal transitions.
"""

from __future__ import annotations

import uuid
from typing import TypedDict

from backend.schemas import JobStatusEnum
from backend.database import AsyncDB


class StateTransitionError(Exception):
    """Raised when an illegal job status transition is attempted."""


class JobRow(TypedDict):
    """Type hint for rows returned from the jobs table."""
    id: str
    status: str
    youtube_id: str
    title_hint: str | None
    file_path: str | None
    library_path: str | None
    navidrome_id: str | None
    percent: float | None
    error_message: str | None
    created_at: str
    updated_at: str


# Legal transitions mapping
_ALLOWED_TRANSITIONS: dict[JobStatusEnum, set[JobStatusEnum]] = {
    JobStatusEnum.pending: {JobStatusEnum.downloading, JobStatusEnum.error},
    JobStatusEnum.downloading: {JobStatusEnum.tagging, JobStatusEnum.error},
    JobStatusEnum.tagging: {JobStatusEnum.confirmed, JobStatusEnum.error},
    JobStatusEnum.confirmed: set(),  # terminal state
    JobStatusEnum.error: {JobStatusEnum.pending},  # recoverable errors only
}


def _validate_transition(old_status: JobStatusEnum, new_status: JobStatusEnum) -> None:
    """Raise StateTransitionError if transition is illegal."""
    if new_status not in _ALLOWED_TRANSITIONS[old_status]:
        raise StateTransitionError(
            f"Cannot transition job from {old_status.value} to {new_status.value}"
        )


async def create_job(
    db: AsyncDB,
    youtube_id: str,
    title_hint: str | None = None,
) -> str:
    """
    Create a new acquisition job in the pending state.

    Returns:
        The newly created job_id (UUID v4).
    """
    job_id = str(uuid.uuid4())
    await db.execute(
        """
        INSERT INTO jobs (id, status, youtube_id, title_hint)
        VALUES (?, ?, ?, ?)
        """,
        (job_id, JobStatusEnum.pending.value, youtube_id, title_hint),
    )
    return job_id


async def get_job(db: AsyncDB, job_id: str) -> JobRow | None:
    """
    Retrieve a job by its ID.

    Returns:
        JobRow dict if found, None otherwise.
    """
    row = await db.fetchone(
        "SELECT * FROM jobs WHERE id = ?",
        (job_id,),
    )
    if row is None:
        return None
    return dict(row)


async def update_job_status(
    db: AsyncDB,
    job_id: str,
    new_status: JobStatusEnum,
    *,
    percent: float | None = None,
    error_message: str | None = None,
) -> None:
    """
    Update a job's status, enforcing legal transitions.

    Args:
        db: AsyncDB instance
        job_id: Job UUID
        new_status: Target status
        percent: Optional progress percentage (0.0–100.0)
        error_message: Optional error message (ignored unless new_status == error)
    """
    row = await get_job(db, job_id)
    if row is None:
        raise ValueError(f"Job {job_id} does not exist")

    old_status = JobStatusEnum(row["status"])
    _validate_transition(old_status, new_status)

    # Build SET clause dynamically
    updates = ["status = ?"]
    params: list[str | float | None] = [new_status.value]

    if percent is not None:
        updates.append("percent = ?")
        params.append(percent)

    if new_status == JobStatusEnum.error and error_message is not None:
        updates.append("error_message = ?")
        params.append(error_message)
    elif new_status != JobStatusEnum.error:
        # Clear error_message when leaving error state
        updates.append("error_message = NULL")

    params.append(job_id)
    await db.execute(
        f"UPDATE jobs SET {', '.join(updates)} WHERE id = ?",
        tuple(params),
    )


async def list_pending_jobs(db: AsyncDB) -> list[JobRow]:
    """
    Return all jobs that are awaiting tag confirmation — i.e. every job
    whose status is NOT 'confirmed'.

    This includes jobs in states: pending, downloading, tagging, error.
    Powers the frontend "Pending" tray so users can return to in-progress
    or failed acquisitions.

    Returns:
        List of JobRow dicts, ordered by created_at ascending.
    """
    rows = await db.fetchall(
        "SELECT * FROM jobs WHERE status != ? ORDER BY created_at",
        (JobStatusEnum.confirmed.value,),
    )
    return [dict(row) for row in rows]