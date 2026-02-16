"""Supabase-backed operations for authenticated user jobs."""

import asyncio
import logging
import uuid
from dataclasses import dataclass

from supabase import Client as SupabaseClient

from yoink.api.storage import BUCKET_NAME

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class UserJob:
    """Authenticated user job row from Supabase."""

    id: str
    user_id: str
    title: str
    storage_path: str | None


@dataclass(slots=True)
class DeleteResult:
    """Result summary for a user job delete operation."""

    deleted_objects: int


def _job_uuid(job_id_hex: str) -> str:
    """Convert internal hex job id to canonical UUID string."""
    return str(uuid.UUID(hex=job_id_hex))


async def count_user_jobs(user_id: str, supabase: SupabaseClient) -> int:
    """Count how many saved jobs a user has in Supabase."""
    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(
        None,
        lambda: supabase.table("jobs")
        .select("id", count="exact")
        .eq("user_id", user_id)
        .execute(),
    )
    return result.count or 0


async def get_user_job(
    user_id: str,
    job_id_hex: str,
    supabase: SupabaseClient,
) -> UserJob | None:
    """Fetch a single user-owned job from Supabase by ID."""
    loop = asyncio.get_running_loop()
    job_uuid = _job_uuid(job_id_hex)

    result = await loop.run_in_executor(
        None,
        lambda: supabase.table("jobs")
        .select("id,user_id,title,storage_path")
        .eq("id", job_uuid)
        .eq("user_id", user_id)
        .limit(1)
        .execute(),
    )

    rows = result.data or []
    if not rows:
        return None

    row = rows[0]
    row_id = str(row["id"])
    return UserJob(
        id=uuid.UUID(row_id).hex,
        user_id=str(row["user_id"]),
        title=str(row["title"]),
        storage_path=row.get("storage_path"),
    )


async def rename_user_job(
    user_id: str,
    job_id_hex: str,
    title: str,
    supabase: SupabaseClient,
) -> None:
    """Rename a user-owned job title in Supabase."""
    loop = asyncio.get_running_loop()
    job_uuid = _job_uuid(job_id_hex)
    await loop.run_in_executor(
        None,
        lambda: supabase.table("jobs")
        .update({"title": title})
        .eq("id", job_uuid)
        .eq("user_id", user_id)
        .execute(),
    )


async def delete_user_job(
    user_id: str,
    job_id_hex: str,
    supabase: SupabaseClient,
) -> DeleteResult:
    """Delete storage objects + Supabase row for a user-owned job."""
    loop = asyncio.get_running_loop()
    storage_prefix = f"{user_id}/{job_id_hex}"

    deleted_objects = 0
    files = await loop.run_in_executor(
        None,
        lambda: supabase.storage.from_(BUCKET_NAME).list(storage_prefix),
    )
    if files:
        paths = [f"{storage_prefix}/{f['name']}" for f in files]
        await loop.run_in_executor(
            None,
            lambda: supabase.storage.from_(BUCKET_NAME).remove(paths),
        )
        deleted_objects = len(paths)
        logger.info(
            "Deleted %d storage objects for user job %s",
            deleted_objects,
            job_id_hex,
        )

    job_uuid = _job_uuid(job_id_hex)
    await loop.run_in_executor(
        None,
        lambda: supabase.table("jobs")
        .delete()
        .eq("id", job_uuid)
        .eq("user_id", user_id)
        .execute(),
    )

    return DeleteResult(deleted_objects=deleted_objects)
