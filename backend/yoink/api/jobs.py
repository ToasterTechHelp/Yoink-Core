"""JobStore: Async SQLite-backed job state management."""

import logging
import uuid
from datetime import datetime, timedelta, timezone

import aiosqlite

logger = logging.getLogger(__name__)

# SQL schema for the jobs table - stores extraction job state and metadata
JOBS_SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id           TEXT PRIMARY KEY,
    user_id      TEXT,
    status       TEXT NOT NULL DEFAULT 'queued',
    filename     TEXT NOT NULL,
    upload_path  TEXT,
    result_path  TEXT,
    error        TEXT,
    current_page     INTEGER DEFAULT 0,
    total_pages      INTEGER DEFAULT 0,
    total_components INTEGER DEFAULT 0,
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL
);
"""

# SQL schema for user feedback on jobs (bug reports, content violations)
FEEDBACK_SCHEMA = """
CREATE TABLE IF NOT EXISTS feedback (
    id         TEXT PRIMARY KEY,
    job_id     TEXT NOT NULL,
    type       TEXT NOT NULL CHECK(type IN ('bug', 'content_violation')),
    message    TEXT,
    created_at TEXT NOT NULL
);
"""

# Valid job status transitions
VALID_STATUSES = {"queued", "processing", "completed", "failed", "delivered"}


class JobStore:
    """
    Lightweight async SQLite job store.
    
    Provides CRUD operations for extraction jobs and user feedback,
    using aiosqlite for non-blocking database access.
    """

    def __init__(self, db_path: str = "yoink_jobs.db"):
        """
        Initialize the JobStore with a database path.
        
        Args:
            db_path: Path to the SQLite database file
        """
        self._db_path = db_path
        self._db: aiosqlite.Connection | None = None

    async def init(self) -> None:
        """
        Open the database connection and create tables if they don't exist.
        
        Must be called before any other operations.
        """
        self._db = await aiosqlite.connect(self._db_path)
        self._db.row_factory = aiosqlite.Row  # Enable dict-like row access
        await self._db.execute(JOBS_SCHEMA)
        await self._db.execute(FEEDBACK_SCHEMA)
        await self._migrate()
        await self._db.commit()
        logger.info("JobStore initialized: %s", self._db_path)

    async def _migrate(self) -> None:
        """Apply schema migrations for existing databases."""
        cursor = await self._db.execute("PRAGMA table_info(jobs)")
        columns = {row[1] for row in await cursor.fetchall()}
        if "total_components" not in columns:
            await self._db.execute(
                "ALTER TABLE jobs ADD COLUMN total_components INTEGER DEFAULT 0"
            )
            logger.info("Migration: added total_components column to jobs table")
        if "user_id" not in columns:
            await self._db.execute(
                "ALTER TABLE jobs ADD COLUMN user_id TEXT"
            )
            logger.info("Migration: added user_id column to jobs table")

    async def close(self) -> None:
        """Close the database connection gracefully."""
        if self._db:
            await self._db.close()
            self._db = None

    async def create_job(
        self, filename: str, upload_path: str, user_id: str | None = None,
    ) -> str:
        """
        Create a new extraction job in 'queued' status.
        
        Args:
            filename: Original name of the uploaded file
            upload_path: Path where the uploaded file is stored
            user_id: Supabase user UUID (None for guests)
            
        Returns:
            The generated job ID (hex UUID)
        """
        job_id = uuid.uuid4().hex
        now = datetime.now(timezone.utc).isoformat()
        await self._db.execute(
            """INSERT INTO jobs (id, user_id, status, filename, upload_path, created_at, updated_at)
               VALUES (?, ?, 'queued', ?, ?, ?, ?)""",
            (job_id, user_id, filename, upload_path, now, now),
        )
        await self._db.commit()
        logger.info("Created job %s for file '%s' (user=%s)", job_id, filename, user_id or "guest")
        return job_id

    async def get_job(self, job_id: str) -> dict | None:
        """
        Retrieve a job by its ID.
        
        Args:
            job_id: The unique job identifier
            
        Returns:
            Job data as a dict, or None if not found
        """
        cursor = await self._db.execute("SELECT * FROM jobs WHERE id = ?", (job_id,))
        row = await cursor.fetchone()
        if row is None:
            return None
        return dict(row)

    async def update_status(self, job_id: str, status: str, **kwargs) -> None:
        """
        Update job status and optionally other fields.
        
        Args:
            job_id: The job to update
            status: New status (must be in VALID_STATUSES)
            **kwargs: Additional fields to update (e.g., error, result_path)
            
        Raises:
            AssertionError: If status is not valid
        """
        assert status in VALID_STATUSES, f"Invalid status: {status}"
        now = datetime.now(timezone.utc).isoformat()
        
        # Build dynamic SET clause for extra fields
        fields = ["status = ?", "updated_at = ?"]
        values = [status, now]
        for key, val in kwargs.items():
            fields.append(f"{key} = ?")
            values.append(val)
        values.append(job_id)
        
        sql = f"UPDATE jobs SET {', '.join(fields)} WHERE id = ?"
        await self._db.execute(sql, values)
        await self._db.commit()

    async def update_progress(self, job_id: str, current_page: int, total_pages: int) -> None:
        """
        Update extraction progress for a job.
        
        Called by the worker as pages are processed.
        
        Args:
            job_id: The job being processed
            current_page: Number of pages processed so far
            total_pages: Total pages in the document
        """
        now = datetime.now(timezone.utc).isoformat()
        await self._db.execute(
            "UPDATE jobs SET current_page = ?, total_pages = ?, updated_at = ? WHERE id = ?",
            (current_page, total_pages, now, job_id),
        )
        await self._db.commit()

    async def delete_job(self, job_id: str) -> bool:
        """
        Delete a job from the database.
        
        Note: Does not delete associated files - caller must handle that.
        
        Args:
            job_id: The job to delete
            
        Returns:
            True if a job was deleted, False if not found
        """
        cursor = await self._db.execute("DELETE FROM jobs WHERE id = ?", (job_id,))
        await self._db.commit()
        return cursor.rowcount > 0

    async def rename_job(self, job_id: str, filename: str) -> bool:
        """
        Rename the stored filename for a job.

        Args:
            job_id: The job to rename
            filename: The new filename/title

        Returns:
            True if a job was updated, False if not found
        """
        now = datetime.now(timezone.utc).isoformat()
        cursor = await self._db.execute(
            "UPDATE jobs SET filename = ?, updated_at = ? WHERE id = ?",
            (filename, now, job_id),
        )
        await self._db.commit()
        return cursor.rowcount > 0

    async def cleanup_old_jobs(self, max_age_hours: int = 24) -> int:
        """
        Delete guest jobs older than max_age_hours from the database.
        
        Used by the cleanup loop to remove stale guest jobs.
        Authenticated user jobs (user_id IS NOT NULL) are preserved indefinitely.
        Note: Call get_old_job_paths() first to get paths for file cleanup.
        
        Args:
            max_age_hours: Maximum age of guest jobs to keep
            
        Returns:
            Number of jobs deleted
        """
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=max_age_hours)).isoformat()
        cursor = await self._db.execute(
            "SELECT id, upload_path, result_path FROM jobs WHERE created_at < ? AND user_id IS NULL",
            (cutoff,),
        )
        old_jobs = await cursor.fetchall()

        if not old_jobs:
            return 0

        # Delete all old jobs in a single query
        job_ids = [row["id"] for row in old_jobs]
        placeholders = ",".join("?" * len(job_ids))
        await self._db.execute(f"DELETE FROM jobs WHERE id IN ({placeholders})", job_ids)
        await self._db.commit()

        logger.info("Cleaned up %d old jobs", len(old_jobs))
        return len(old_jobs)

    async def get_old_job_paths(self, max_age_hours: int = 24) -> list[dict]:
        """
        Get file paths of guest jobs older than max_age_hours.
        
        Used to identify files that need cleanup before deleting job records.
        Only returns guest jobs (user_id IS NULL).
        
        Args:
            max_age_hours: Maximum age threshold
            
        Returns:
            List of dicts with 'id', 'upload_path', and 'result_path' keys
        """
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=max_age_hours)).isoformat()
        cursor = await self._db.execute(
            "SELECT id, upload_path, result_path FROM jobs WHERE created_at < ? AND user_id IS NULL",
            (cutoff,),
        )
        return [dict(row) for row in await cursor.fetchall()]

    # ---- Feedback ----

    async def create_feedback(
        self, job_id: str, feedback_type: str, message: str | None = None,
    ) -> str:
        """
        Store a user feedback entry for a job.
        
        Args:
            job_id: The job this feedback relates to
            feedback_type: Either 'bug' or 'content_violation'
            message: Optional additional details from the user
            
        Returns:
            The generated feedback ID (hex UUID)
        """
        feedback_id = uuid.uuid4().hex
        now = datetime.now(timezone.utc).isoformat()
        await self._db.execute(
            """INSERT INTO feedback (id, job_id, type, message, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (feedback_id, job_id, feedback_type, message, now),
        )
        await self._db.commit()
        logger.info("Feedback %s created for job %s (type=%s)", feedback_id, job_id, feedback_type)
        return feedback_id
