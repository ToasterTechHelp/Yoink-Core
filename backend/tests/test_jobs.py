"""Tests for yoink.api.jobs — JobStore."""

import asyncio

import aiosqlite
import pytest
import pytest_asyncio

from yoink.api.jobs import JobStore


@pytest_asyncio.fixture
async def job_store(tmp_path):
    """Create a JobStore backed by a temp SQLite DB."""
    store = JobStore(db_path=str(tmp_path / "test_jobs.db"))
    await store.init()
    yield store
    await store.close()


@pytest_asyncio.fixture
async def db_path(tmp_path):
    """Return a temp DB path for migration tests."""
    return str(tmp_path / "migrate_test.db")


@pytest.mark.asyncio
async def test_create_and_get_job(job_store):
    job_id = await job_store.create_job("lecture.pdf", "/tmp/uploads/lecture.pdf")
    assert len(job_id) == 32  # hex UUID

    job = await job_store.get_job(job_id)
    assert job is not None
    assert job["filename"] == "lecture.pdf"
    assert job["status"] == "queued"
    assert job["upload_path"] == "/tmp/uploads/lecture.pdf"
    assert job["current_page"] == 0
    assert job["total_pages"] == 0


@pytest.mark.asyncio
async def test_get_nonexistent_job(job_store):
    job = await job_store.get_job("nonexistent")
    assert job is None


@pytest.mark.asyncio
async def test_update_status(job_store):
    job_id = await job_store.create_job("test.pdf", "/tmp/test.pdf")
    await job_store.update_status(job_id, "processing")

    job = await job_store.get_job(job_id)
    assert job["status"] == "processing"


@pytest.mark.asyncio
async def test_update_status_with_extra_fields(job_store):
    job_id = await job_store.create_job("test.pdf", "/tmp/test.pdf")
    await job_store.update_status(job_id, "failed", error="Something broke")

    job = await job_store.get_job(job_id)
    assert job["status"] == "failed"
    assert job["error"] == "Something broke"


@pytest.mark.asyncio
async def test_update_progress(job_store):
    job_id = await job_store.create_job("test.pdf", "/tmp/test.pdf")
    await job_store.update_progress(job_id, 5, 10)

    job = await job_store.get_job(job_id)
    assert job["current_page"] == 5
    assert job["total_pages"] == 10


@pytest.mark.asyncio
async def test_delete_job(job_store):
    job_id = await job_store.create_job("test.pdf", "/tmp/test.pdf")
    deleted = await job_store.delete_job(job_id)
    assert deleted is True

    job = await job_store.get_job(job_id)
    assert job is None


@pytest.mark.asyncio
async def test_delete_nonexistent_job(job_store):
    deleted = await job_store.delete_job("nonexistent")
    assert deleted is False


@pytest.mark.asyncio
async def test_invalid_status_raises(job_store):
    job_id = await job_store.create_job("test.pdf", "/tmp/test.pdf")
    with pytest.raises(AssertionError, match="Invalid status"):
        await job_store.update_status(job_id, "bogus")


@pytest.mark.asyncio
async def test_migrate_adds_total_components_to_old_db(db_path):
    """Simulate a pre-existing DB without total_components column.
    
    This is the exact bug that was hit in production: the DB was created
    before total_components existed, and CREATE TABLE IF NOT EXISTS
    silently skipped the new column.
    """
    # Step 1: Create old-schema DB (no total_components column)
    async with aiosqlite.connect(db_path) as db:
        await db.execute("""
            CREATE TABLE jobs (
                id           TEXT PRIMARY KEY,
                status       TEXT NOT NULL DEFAULT 'queued',
                filename     TEXT NOT NULL,
                upload_path  TEXT,
                result_path  TEXT,
                error        TEXT,
                current_page     INTEGER DEFAULT 0,
                total_pages      INTEGER DEFAULT 0,
                created_at   TEXT NOT NULL,
                updated_at   TEXT NOT NULL
            )
        """)
        await db.execute("""
            CREATE TABLE feedback (
                id         TEXT PRIMARY KEY,
                job_id     TEXT NOT NULL,
                type       TEXT NOT NULL CHECK(type IN ('bug', 'content_violation')),
                message    TEXT,
                created_at TEXT NOT NULL
            )
        """)
        await db.commit()

    # Step 2: Open with JobStore — migration should add the column
    store = JobStore(db_path=db_path)
    await store.init()

    # Step 3: Verify we can create a job and set total_components
    job_id = await store.create_job("test.pdf", "/tmp/test.pdf")
    await store.update_status(
        job_id, "completed",
        result_path="/tmp/result.json",
        total_components=42,
    )

    job = await store.get_job(job_id)
    assert job["total_components"] == 42

    await store.close()


@pytest.mark.asyncio
async def test_total_components_stored_on_completion(job_store):
    """Verify total_components round-trips through update_status."""
    job_id = await job_store.create_job("test.pdf", "/tmp/test.pdf")

    # Initially 0
    job = await job_store.get_job(job_id)
    assert job["total_components"] == 0

    # Update with total_components via kwargs
    await job_store.update_status(
        job_id, "completed",
        result_path="/tmp/result.json",
        total_components=150,
    )

    job = await job_store.get_job(job_id)
    assert job["total_components"] == 150


@pytest.mark.asyncio
async def test_create_feedback(job_store):
    """Verify feedback is stored correctly."""
    job_id = await job_store.create_job("test.pdf", "/tmp/test.pdf")
    feedback_id = await job_store.create_feedback(
        job_id=job_id,
        feedback_type="bug",
        message="Something is wrong",
    )
    assert len(feedback_id) == 32  # hex UUID


@pytest.mark.asyncio
async def test_create_feedback_without_message(job_store):
    """Verify feedback works with no message."""
    job_id = await job_store.create_job("test.pdf", "/tmp/test.pdf")
    feedback_id = await job_store.create_feedback(
        job_id=job_id,
        feedback_type="content_violation",
    )
    assert len(feedback_id) == 32


@pytest.mark.asyncio
async def test_get_old_job_paths(tmp_path):
    """Verify get_old_job_paths returns paths for expired jobs."""
    db_path = str(tmp_path / "test.db")
    store = JobStore(db_path=db_path)
    await store.init()

    # Create a job and manually backdate it
    job_id = await store.create_job("old.pdf", "/tmp/old.pdf")
    await store.update_status(job_id, "completed", result_path="/tmp/result.json")

    old_time = "2024-01-01T00:00:00+00:00"
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            "UPDATE jobs SET created_at = ? WHERE id = ?",
            (old_time, job_id),
        )
        await db.commit()

    # Also create a recent job — should NOT be returned
    recent_id = await store.create_job("new.pdf", "/tmp/new.pdf")

    paths = await store.get_old_job_paths(max_age_hours=24)
    assert len(paths) == 1
    assert paths[0]["id"] == job_id
    assert paths[0]["result_path"] == "/tmp/result.json"

    await store.close()


@pytest.mark.asyncio
async def test_cleanup_old_jobs_returns_zero_when_none_expired(job_store):
    """Cleanup should return 0 when no jobs are old enough."""
    await job_store.create_job("recent.pdf", "/tmp/recent.pdf")
    count = await job_store.cleanup_old_jobs(max_age_hours=24)
    assert count == 0


@pytest.mark.asyncio
async def test_close_is_idempotent(tmp_path):
    """Calling close() twice should not raise."""
    store = JobStore(db_path=str(tmp_path / "test.db"))
    await store.init()
    await store.close()
    await store.close()  # Should not raise
