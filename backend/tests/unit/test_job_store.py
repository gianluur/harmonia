"""
backend/tests/unit/test_job_store.py

Unit tests for backend/services/job_store.py state machine.
"""

import pytest
from backend.services.job_store import (
    create_job,
    get_job,
    update_job_status,
    list_pending_jobs,
    StateTransitionError,
)
from backend.schemas import JobStatusEnum


@pytest.mark.asyncio
async def test_create_job_initial_state(db):
    """Verify a new job is created in the pending state."""
    job_id = await create_job(db, youtube_id="video123", title_hint="Test Title")
    assert job_id is not None
    
    job = await get_job(db, job_id)
    assert job["id"] == job_id
    assert job["status"] == JobStatusEnum.pending.value
    assert job["youtube_id"] == "video123"
    assert job["title_hint"] == "Test Title"
    assert job["percent"] is None
    assert job["error_message"] is None


@pytest.mark.asyncio
async def test_get_job_missing(db):
    """Verify get_job returns None for non-existent IDs."""
    job = await get_job(db, "non-existent-uuid")
    assert job is None


@pytest.mark.asyncio
async def test_list_pending_jobs_filtering(db):
    """Verify list_pending_jobs returns only pending jobs in correct order."""
    # Create jobs in different states
    job1_id = await create_job(db, youtube_id="v1")
    job2_id = await create_job(db, youtube_id="v2")
    job3_id = await create_job(db, youtube_id="v3")
    
    # Transition job2 to downloading
    await update_job_status(db, job2_id, JobStatusEnum.downloading)
    
    pending = await list_pending_jobs(db)
    assert len(pending) == 3  # all non-confirmed jobs
    ids = [j["id"] for j in pending]
    assert job1_id in ids
    assert job2_id in ids  # downloading is included
    assert job3_id in ids


@pytest.mark.asyncio
async def test_valid_transition_lifecycle(db):
    """Verify the standard success lifecycle: pending -> downloading -> tagging -> confirmed."""
    job_id = await create_job(db, youtube_id="v1")
    
    # pending -> downloading
    await update_job_status(db, job_id, JobStatusEnum.downloading)
    job = await get_job(db, job_id)
    assert job["status"] == JobStatusEnum.downloading.value
    
    # downloading -> tagging
    await update_job_status(db, job_id, JobStatusEnum.tagging)
    job = await get_job(db, job_id)
    assert job["status"] == JobStatusEnum.tagging.value
    
    # tagging -> confirmed
    await update_job_status(db, job_id, JobStatusEnum.confirmed)
    job = await get_job(db, job_id)
    assert job["status"] == JobStatusEnum.confirmed.value


@pytest.mark.asyncio
async def test_invalid_transition_raises(db):
    """Verify illegal transitions raise StateTransitionError."""
    job_id = await create_job(db, youtube_id="v1")
    
    # pending -> tagging (skip downloading)
    with pytest.raises(StateTransitionError):
        await update_job_status(db, job_id, JobStatusEnum.tagging)
    
    # pending -> confirmed (skip downloading and tagging)
    with pytest.raises(StateTransitionError):
        await update_job_status(db, job_id, JobStatusEnum.confirmed)
        
    # confirmed -> downloading (terminal state)
    await update_job_status(db, job_id, JobStatusEnum.downloading)
    await update_job_status(db, job_id, JobStatusEnum.tagging)
    await update_job_status(db, job_id, JobStatusEnum.confirmed)
    with pytest.raises(StateTransitionError):
        await update_job_status(db, job_id, JobStatusEnum.downloading)


@pytest.mark.asyncio
async def test_transition_to_error_anywhere(db):
    """Verify that any non-terminal state can transition to error."""
    # pending -> error
    j1 = await create_job(db, youtube_id="v1")
    await update_job_status(db, j1, JobStatusEnum.error, error_message="fail1")
    assert (await get_job(db, j1))["status"] == JobStatusEnum.error.value
    
    # downloading -> error
    j2 = await create_job(db, youtube_id="v2")
    await update_job_status(db, j2, JobStatusEnum.downloading)
    await update_job_status(db, j2, JobStatusEnum.error, error_message="fail2")
    assert (await get_job(db, j2))["status"] == JobStatusEnum.error.value
    
    # tagging -> error
    j3 = await create_job(db, youtube_id="v3")
    await update_job_status(db, j3, JobStatusEnum.downloading)
    await update_job_status(db, j3, JobStatusEnum.tagging)
    await update_job_status(db, j3, JobStatusEnum.error, error_message="fail3")
    assert (await get_job(db, j3))["status"] == JobStatusEnum.error.value


@pytest.mark.asyncio
async def test_transition_from_error_retry(db):
    """Verify that an error state can transition back to pending for retry."""
    job_id = await create_job(db, youtube_id="v1")
    await update_job_status(db, job_id, JobStatusEnum.error, error_message="something broke")
    
    # error -> pending
    await update_job_status(db, job_id, JobStatusEnum.pending)
    job = await get_job(db, job_id)
    assert job["status"] == JobStatusEnum.pending.value
    assert job["error_message"] is None  # Should be cleared


@pytest.mark.asyncio
async def test_update_progress_and_error_message(db):
    """Verify that percent and error_message are correctly updated."""
    job_id = await create_job(db, youtube_id="v1")
    
    # Update percent during downloading
    await update_job_status(db, job_id, JobStatusEnum.downloading, percent=45.5)
    job = await get_job(db, job_id)
    assert job["percent"] == 45.5
    
    # Transition to error with message
    await update_job_status(db, job_id, JobStatusEnum.error, error_message="Network timeout")
    job = await get_job(db, job_id)
    assert job["status"] == JobStatusEnum.error.value
    assert job["error_message"] == "Network timeout"
    assert job["percent"] == 45.5  # percent should still be there
