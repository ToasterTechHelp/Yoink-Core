"""Focused API tests for user-job rename/delete + ID normalization behavior."""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from yoink.api import routes
from yoink.api.user_jobs import DeleteResult, UserJob

HEX_JOB_ID = "0123456789abcdef0123456789abcdef"
DASHED_JOB_ID = "01234567-89ab-cdef-0123-456789abcdef"
OWNER_ID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
OTHER_USER_ID = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"


class InMemoryJobStore:
    """Minimal async job store for route testing."""

    def __init__(self, jobs: dict[str, dict] | None = None):
        self.jobs = jobs or {}
        self.feedback: list[dict] = []

    async def get_job(self, job_id: str):
        job = self.jobs.get(job_id)
        if job is None:
            return None
        return dict(job)

    async def delete_job(self, job_id: str) -> bool:
        return self.jobs.pop(job_id, None) is not None

    async def rename_job(self, job_id: str, filename: str) -> bool:
        job = self.jobs.get(job_id)
        if job is None:
            return False
        job["filename"] = filename
        return True

    async def create_feedback(self, job_id: str, feedback_type: str, message: str | None = None):
        self.feedback.append(
            {"job_id": job_id, "type": feedback_type, "message": message}
        )
        return "f" * 32


def _sample_local_job(user_id: str | None = OWNER_ID) -> dict:
    return {
        "id": HEX_JOB_ID,
        "user_id": user_id,
        "status": "completed",
        "filename": "slides.pdf",
        "upload_path": None,
        "result_path": None,
        "error": None,
        "current_page": 1,
        "total_pages": 1,
        "created_at": "2024-01-01T00:00:00+00:00",
    }


def _sample_user_job(title: str = "slides.pdf") -> UserJob:
    return UserJob(
        id=HEX_JOB_ID,
        user_id=OWNER_ID,
        title=title,
        storage_path=f"scans/{OWNER_ID}/{HEX_JOB_ID}/",
    )


def _client_with_store(store: InMemoryJobStore, supabase=object()) -> TestClient:
    app = FastAPI()
    app.include_router(routes.router, prefix="/api/v1")
    app.state.job_store = store
    app.state.supabase = supabase
    return TestClient(app)


def test_rename_success_supabase_authoritative_without_local_row(monkeypatch):
    store = InMemoryJobStore({})
    captured: dict = {}

    async def fake_get_optional_user(_request):
        return OWNER_ID

    async def fake_get_user_job(user_id, job_id_hex, supabase):
        captured["lookup"] = (user_id, job_id_hex, supabase)
        return _sample_user_job("lecture.pdf")

    async def fake_rename_user_job(user_id, job_id_hex, title, supabase):
        captured["rename"] = (user_id, job_id_hex, title, supabase)

    monkeypatch.setattr(routes, "get_optional_user", fake_get_optional_user)
    monkeypatch.setattr(routes, "get_user_job", fake_get_user_job)
    monkeypatch.setattr(routes, "rename_user_job", fake_rename_user_job)

    with _client_with_store(store, supabase="supabase-client") as client:
        resp = client.patch(
            f"/api/v1/jobs/{DASHED_JOB_ID}/rename",
            json={"base_name": "lecture-notes"},
        )

    assert resp.status_code == 200
    assert resp.json() == {"job_id": HEX_JOB_ID, "title": "lecture-notes.pdf"}
    assert captured["lookup"] == (OWNER_ID, HEX_JOB_ID, "supabase-client")
    assert captured["rename"] == (OWNER_ID, HEX_JOB_ID, "lecture-notes.pdf", "supabase-client")


def test_rename_requires_auth(monkeypatch):
    store = InMemoryJobStore({})

    async def fake_get_optional_user(_request):
        return None

    monkeypatch.setattr(routes, "get_optional_user", fake_get_optional_user)

    with _client_with_store(store) as client:
        resp = client.patch(
            f"/api/v1/jobs/{HEX_JOB_ID}/rename",
            json={"base_name": "renamed"},
        )

    assert resp.status_code == 401


def test_rename_non_owner_or_missing_returns_404(monkeypatch):
    store = InMemoryJobStore({})

    async def fake_get_optional_user(_request):
        return OTHER_USER_ID

    async def fake_get_user_job(_user_id, _job_id_hex, _supabase):
        return None

    monkeypatch.setattr(routes, "get_optional_user", fake_get_optional_user)
    monkeypatch.setattr(routes, "get_user_job", fake_get_user_job)

    with _client_with_store(store) as client:
        resp = client.patch(
            f"/api/v1/jobs/{HEX_JOB_ID}/rename",
            json={"base_name": "renamed"},
        )

    assert resp.status_code == 404


def test_rename_422_for_invalid_job_id(monkeypatch):
    store = InMemoryJobStore({})

    async def fake_get_optional_user(_request):
        return OWNER_ID

    monkeypatch.setattr(routes, "get_optional_user", fake_get_optional_user)

    with _client_with_store(store) as client:
        resp = client.patch(
            "/api/v1/jobs/not-a-uuid/rename",
            json={"base_name": "renamed"},
        )

    assert resp.status_code == 422


def test_rename_422_for_invalid_base_name(monkeypatch):
    store = InMemoryJobStore({})

    async def fake_get_optional_user(_request):
        return OWNER_ID

    async def fake_get_user_job(_user_id, _job_id_hex, _supabase):
        return _sample_user_job()

    monkeypatch.setattr(routes, "get_optional_user", fake_get_optional_user)
    monkeypatch.setattr(routes, "get_user_job", fake_get_user_job)

    with _client_with_store(store) as client:
        empty = client.patch(
            f"/api/v1/jobs/{HEX_JOB_ID}/rename",
            json={"base_name": "   "},
        )
        bad_chars = client.patch(
            f"/api/v1/jobs/{HEX_JOB_ID}/rename",
            json={"base_name": "new/name"},
        )

    assert empty.status_code == 422
    assert bad_chars.status_code == 422


def test_rename_502_when_supabase_update_fails(monkeypatch):
    store = InMemoryJobStore({})

    async def fake_get_optional_user(_request):
        return OWNER_ID

    async def fake_get_user_job(_user_id, _job_id_hex, _supabase):
        return _sample_user_job("slides.pdf")

    async def failing_rename(*_args, **_kwargs):
        raise RuntimeError("supabase is down")

    monkeypatch.setattr(routes, "get_optional_user", fake_get_optional_user)
    monkeypatch.setattr(routes, "get_user_job", fake_get_user_job)
    monkeypatch.setattr(routes, "rename_user_job", failing_rename)

    with _client_with_store(store) as client:
        resp = client.patch(
            f"/api/v1/jobs/{HEX_JOB_ID}/rename",
            json={"base_name": "renamed"},
        )

    assert resp.status_code == 502


def test_delete_requires_auth():
    store = InMemoryJobStore({})
    with _client_with_store(store) as client:
        resp = client.delete(f"/api/v1/jobs/{HEX_JOB_ID}")
    assert resp.status_code == 401


def test_delete_blocks_guest_job(monkeypatch):
    store = InMemoryJobStore({HEX_JOB_ID: _sample_local_job(user_id=None)})

    async def fake_get_optional_user(_request):
        return OWNER_ID

    monkeypatch.setattr(routes, "get_optional_user", fake_get_optional_user)

    with _client_with_store(store) as client:
        resp = client.delete(f"/api/v1/jobs/{HEX_JOB_ID}")

    assert resp.status_code == 403


def test_delete_success_supabase_authoritative_without_local_row(monkeypatch):
    store = InMemoryJobStore({})
    captured: dict = {}

    async def fake_get_optional_user(_request):
        return OWNER_ID

    async def fake_get_user_job(user_id, job_id_hex, supabase):
        captured["lookup"] = (user_id, job_id_hex, supabase)
        return _sample_user_job()

    async def fake_delete_user_job(user_id, job_id_hex, supabase):
        captured["delete"] = (user_id, job_id_hex, supabase)
        return DeleteResult(deleted_objects=3)

    monkeypatch.setattr(routes, "get_optional_user", fake_get_optional_user)
    monkeypatch.setattr(routes, "get_user_job", fake_get_user_job)
    monkeypatch.setattr(routes, "delete_user_job", fake_delete_user_job)

    with _client_with_store(store, supabase="supabase-client") as client:
        resp = client.delete(f"/api/v1/jobs/{DASHED_JOB_ID}")

    assert resp.status_code == 204
    assert captured["lookup"] == (OWNER_ID, HEX_JOB_ID, "supabase-client")
    assert captured["delete"] == (OWNER_ID, HEX_JOB_ID, "supabase-client")


def test_delete_missing_or_non_owned_returns_404(monkeypatch):
    store = InMemoryJobStore({})

    async def fake_get_optional_user(_request):
        return OWNER_ID

    async def fake_get_user_job(_user_id, _job_id_hex, _supabase):
        return None

    monkeypatch.setattr(routes, "get_optional_user", fake_get_optional_user)
    monkeypatch.setattr(routes, "get_user_job", fake_get_user_job)

    with _client_with_store(store) as client:
        resp = client.delete(f"/api/v1/jobs/{HEX_JOB_ID}")

    assert resp.status_code == 404


def test_delete_502_when_storage_or_supabase_delete_fails(monkeypatch):
    store = InMemoryJobStore({})

    async def fake_get_optional_user(_request):
        return OWNER_ID

    async def fake_get_user_job(_user_id, _job_id_hex, _supabase):
        return _sample_user_job()

    async def failing_delete(*_args, **_kwargs):
        raise RuntimeError("storage failure")

    monkeypatch.setattr(routes, "get_optional_user", fake_get_optional_user)
    monkeypatch.setattr(routes, "get_user_job", fake_get_user_job)
    monkeypatch.setattr(routes, "delete_user_job", failing_delete)

    with _client_with_store(store) as client:
        resp = client.delete(f"/api/v1/jobs/{HEX_JOB_ID}")

    assert resp.status_code == 502


def test_feedback_accepts_dashed_id_and_stores_normalized_hex():
    store = InMemoryJobStore({HEX_JOB_ID: _sample_local_job()})

    with _client_with_store(store) as client:
        resp = client.post(
            "/api/v1/feedback",
            json={
                "job_id": DASHED_JOB_ID,
                "type": "bug",
                "message": "mismatch",
            },
        )

    assert resp.status_code == 201
    assert store.feedback[0]["job_id"] == HEX_JOB_ID


def test_get_job_status_accepts_dashed_and_undashed_ids():
    store = InMemoryJobStore({HEX_JOB_ID: _sample_local_job()})

    with _client_with_store(store) as client:
        dashed = client.get(f"/api/v1/jobs/{DASHED_JOB_ID}")
        undashed = client.get(f"/api/v1/jobs/{HEX_JOB_ID}")

    assert dashed.status_code == 200
    assert undashed.status_code == 200
