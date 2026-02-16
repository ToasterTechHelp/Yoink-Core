"""Integration tests for the Yoink API with real extraction pipeline.

These tests use a real YOLO model and actual file processing to verify
the complete job lifecycle including worker processing, progress updates,
and cleanup behaviors.
"""

import asyncio
import os
import time
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np
import pytest
import pytest_asyncio
from fastapi.testclient import TestClient

from yoink.api.jobs import JobStore
from yoink.api.worker import ExtractionWorker


# Test fixtures directory
TEST_DATA_DIR = Path(__file__).parent / "test_data"


def create_test_image(path: Path, width: int = 800, height: int = 600) -> None:
    """Create a simple test image with some text-like regions."""
    # Create white image
    img = np.ones((height, width, 3), dtype=np.uint8) * 255
    
    # Add some dark rectangles (simulate text blocks)
    cv2.rectangle(img, (50, 50), (350, 100), (0, 0, 0), -1)
    cv2.rectangle(img, (50, 150), (750, 200), (0, 0, 0), -1)
    
    # Add a rectangle (simulate a figure/table)
    cv2.rectangle(img, (400, 300), (700, 500), (100, 100, 100), -1)
    
    cv2.imwrite(str(path), img)


@pytest_asyncio.fixture
async def real_worker_components(tmp_path):
    """Create real worker components with temp directories."""
    # Setup paths
    job_data_dir = tmp_path / "job_data"
    upload_dir = tmp_path / "uploads"
    db_path = tmp_path / "test.db"
    
    job_data_dir.mkdir()
    upload_dir.mkdir()
    
    # Create test image
    test_img_path = tmp_path / "test_page.png"
    create_test_image(test_img_path)
    
    # Initialize real components
    job_store = JobStore(db_path=str(db_path))
    await job_store.init()
    
    # Create real extractor (this will download model if needed)
    from yoink.extractor import LayoutExtractor
    extractor = LayoutExtractor()
    
    worker = ExtractionWorker(
        job_store=job_store,
        extractor=extractor,
        output_base_dir=str(job_data_dir),
    )
    worker.start()
    
    yield {
        "job_store": job_store,
        "worker": worker,
        "extractor": extractor,
        "job_data_dir": job_data_dir,
        "upload_dir": upload_dir,
        "test_img_path": test_img_path,
        "db_path": db_path,
    }
    
    # Cleanup
    await worker.stop()
    await job_store.close()


@pytest.fixture
def integration_client(tmp_path, monkeypatch):
    """Create a TestClient with real extraction enabled."""
    import sys
    
    # Clear module cache to ensure fresh app state
    modules_to_clear = [k for k in sys.modules.keys() if k.startswith("yoink.api")]
    for mod in modules_to_clear:
        del sys.modules[mod]
    
    os.environ["YOINK_JOB_DATA_DIR"] = str(tmp_path / "job_data")
    os.environ["YOINK_UPLOAD_DIR"] = str(tmp_path / "uploads")
    os.environ["YOINK_DB_PATH"] = str(tmp_path / "test.db")
    
    from yoink.api.app import create_app
    from yoink.api import routes
    
    # Patch UPLOAD_DIR in routes
    monkeypatch.setattr(routes, "UPLOAD_DIR", tmp_path / "uploads")
    
    app = create_app()
    
    with TestClient(app) as client:
        yield client
    
    # Cleanup env vars
    for key in ("YOINK_JOB_DATA_DIR", "YOINK_UPLOAD_DIR", "YOINK_DB_PATH"):
        os.environ.pop(key, None)


class TestFullJobLifecycle:
    """Test complete job lifecycle from upload to cleanup."""
    
    def test_upload_image_and_get_result(self, integration_client, tmp_path):
        """Test uploading an image and retrieving the extraction result."""
        # Create a test image
        test_img = tmp_path / "test.png"
        create_test_image(test_img)
        
        # Upload the image
        with open(test_img, "rb") as f:
            resp = integration_client.post(
                "/api/v1/extract",
                files={"file": ("test.png", f, "image/png")},
            )
        
        assert resp.status_code == 202
        data = resp.json()
        job_id = data["job_id"]
        
        # Wait for job to complete (poll with timeout)
        max_wait = 60  # seconds
        start = time.time()
        final_status = None
        
        while time.time() - start < max_wait:
            resp = integration_client.get(f"/api/v1/jobs/{job_id}")
            assert resp.status_code == 200
            status_data = resp.json()
            final_status = status_data["status"]
            
            if final_status == "completed":
                # Verify progress was updated
                assert status_data["progress"]["current_page"] == 1
                assert status_data["progress"]["total_pages"] == 1
                break
            elif final_status == "failed":
                pytest.fail(f"Job failed: {status_data.get('error', 'Unknown error')}")
            
            time.sleep(0.5)
        else:
            pytest.fail(f"Job didn't complete within {max_wait}s, last status: {final_status}")
        
        # Get the result metadata
        resp = integration_client.get(f"/api/v1/jobs/{job_id}/result")
        assert resp.status_code == 200
        result = resp.json()
        
        # Verify metadata structure (no components in this response)
        assert result["source_file"] == "test.png"
        assert result["total_pages"] == 1
        assert result["total_components"] > 0
        
        # Fetch components in batches
        resp = integration_client.get(
            f"/api/v1/jobs/{job_id}/result/components",
            params={"offset": 0, "limit": 100},
        )
        assert resp.status_code == 200
        batch = resp.json()
        assert batch["total"] == result["total_components"]
        assert batch["has_more"] is False
        
        # Verify component structure
        for comp in batch["components"]:
            assert "id" in comp
            assert "category" in comp
            assert comp["category"] in ("text", "figure", "misc")
            assert "base64" in comp
            assert "bbox" in comp
            assert "page_number" in comp
        
        # Job should still be completed (no auto-cleanup)
        resp = integration_client.get(f"/api/v1/jobs/{job_id}")
        assert resp.status_code == 200
        assert resp.json()["status"] == "completed"


class TestSequentialJobProcessing:
    """Test that jobs are processed one at a time."""
    
    def test_jobs_processed_sequentially(self, integration_client, tmp_path):
        """Upload multiple jobs and verify they complete in order."""
        # Create test images
        jobs = []
        for i in range(3):
            test_img = tmp_path / f"test_{i}.png"
            create_test_image(test_img)
            
            with open(test_img, "rb") as f:
                resp = integration_client.post(
                    "/api/v1/extract",
                    files={"file": (f"test_{i}.png", f, "image/png")},
                )
            
            assert resp.status_code == 202
            jobs.append(resp.json()["job_id"])
        
        # All should be queued initially
        for job_id in jobs:
            resp = integration_client.get(f"/api/v1/jobs/{job_id}")
            assert resp.json()["status"] in ("queued", "processing")
        
        # Wait for all to complete
        max_wait = 120
        start = time.time()
        completed = set()
        
        while len(completed) < len(jobs) and time.time() - start < max_wait:
            for job_id in jobs:
                if job_id in completed:
                    continue
                resp = integration_client.get(f"/api/v1/jobs/{job_id}")
                status = resp.json()["status"]
                if status == "completed":
                    completed.add(job_id)
            time.sleep(0.5)
        
        assert len(completed) == len(jobs), f"Only {len(completed)}/{len(jobs)} jobs completed"


class TestProgressUpdates:
    """Test that progress is correctly tracked during processing."""
    
    def test_progress_updated_during_processing(self, integration_client, tmp_path):
        """Verify progress fields are updated as job processes."""
        # Create test image
        test_img = tmp_path / "test.png"
        create_test_image(test_img)
        
        with open(test_img, "rb") as f:
            resp = integration_client.post(
                "/api/v1/extract",
                files={"file": ("test.png", f, "image/png")},
            )
        
        job_id = resp.json()["job_id"]
        
        # Poll and check progress updates
        seen_progress = []
        max_wait = 60
        start = time.time()
        
        while time.time() - start < max_wait:
            resp = integration_client.get(f"/api/v1/jobs/{job_id}")
            data = resp.json()
            
            progress = (data["progress"]["current_page"], data["progress"]["total_pages"])
            if progress not in seen_progress:
                seen_progress.append(progress)
            
            if data["status"] == "completed":
                break
            elif data["status"] == "failed":
                pytest.fail("Job failed")
            
            time.sleep(0.2)
        
        # Should have seen progress advance
        assert len(seen_progress) >= 1
        # Final progress should show completion
        assert seen_progress[-1][0] == seen_progress[-1][1]  # current == total


class TestCleanupBehavior:
    """Test file and job cleanup in various scenarios."""
    
    def test_job_data_persists_after_result_fetch(self, integration_client, tmp_path):
        """Verify job data persists after fetching results (no auto-cleanup)."""
        job_data_dir = tmp_path / "job_data"
        
        # Create and upload test image
        test_img = tmp_path / "test.png"
        create_test_image(test_img)
        
        with open(test_img, "rb") as f:
            resp = integration_client.post(
                "/api/v1/extract",
                files={"file": ("test.png", f, "image/png")},
            )
        
        job_id = resp.json()["job_id"]
        
        # Wait for completion
        max_wait = 60
        start = time.time()
        while time.time() - start < max_wait:
            resp = integration_client.get(f"/api/v1/jobs/{job_id}")
            if resp.json()["status"] == "completed":
                break
            time.sleep(0.5)
        
        # Job data directory should exist with results
        job_dir = job_data_dir / job_id
        assert job_dir.exists(), "Job directory should exist after completion"
        
        # Fetch metadata and components
        resp = integration_client.get(f"/api/v1/jobs/{job_id}/result")
        assert resp.status_code == 200
        resp = integration_client.get(
            f"/api/v1/jobs/{job_id}/result/components",
            params={"offset": 0, "limit": 10},
        )
        assert resp.status_code == 200
        
        # Job data should STILL exist (no auto-cleanup on fetch)
        assert job_dir.exists(), "Job directory should persist after result fetch"
        resp = integration_client.get(f"/api/v1/jobs/{job_id}")
        assert resp.json()["status"] == "completed"
    
    def test_delete_job_requires_authentication(self, integration_client, tmp_path):
        """Guest delete attempts should be blocked with 401."""
        # Create and upload
        test_img = tmp_path / "test.png"
        create_test_image(test_img)
        
        with open(test_img, "rb") as f:
            resp = integration_client.post(
                "/api/v1/extract",
                files={"file": ("test.png", f, "image/png")},
            )
        
        job_id = resp.json()["job_id"]
        
        # Wait for completion
        max_wait = 60
        start = time.time()
        while time.time() - start < max_wait:
            resp = integration_client.get(f"/api/v1/jobs/{job_id}")
            if resp.json()["status"] == "completed":
                break
            time.sleep(0.5)
        
        # Guest delete should be rejected
        resp = integration_client.delete(f"/api/v1/jobs/{job_id}")
        assert resp.status_code == 401

        # Verify job still exists
        resp = integration_client.get(f"/api/v1/jobs/{job_id}")
        assert resp.status_code == 200


class TestErrorHandling:
    """Test error scenarios and recovery."""

    MISSING_JOB_ID = "11111111-1111-1111-1111-111111111111"
    
    def test_invalid_file_type_rejected(self, integration_client):
        """Test that a corrupt/invalid file fails during processing."""
        resp = integration_client.post(
            "/api/v1/extract",
            files={"file": ("test.pdf", b"not a real pdf", "application/pdf")},
        )
        
        # Accepted initially (validation is async)
        assert resp.status_code == 202
        job_id = resp.json()["job_id"]
        
        # Must reach 'failed' status
        max_wait = 30
        start = time.time()
        while time.time() - start < max_wait:
            resp = integration_client.get(f"/api/v1/jobs/{job_id}")
            data = resp.json()
            if data["status"] == "failed":
                assert data["error"] is not None, "Failed job should have an error message"
                break
            elif data["status"] == "completed":
                pytest.fail("Corrupt file should not complete successfully")
            time.sleep(0.5)
        else:
            pytest.fail(f"Job didn't fail within {max_wait}s, last status: {data['status']}")
    
    def test_file_too_large_rejected(self, integration_client):
        """Upload exceeding MAX_UPLOAD_SIZE should return 413."""
        from yoink.api import routes
        original = routes.MAX_UPLOAD_SIZE
        # Temporarily lower limit so we don't need 100MB of RAM
        routes.MAX_UPLOAD_SIZE = 1024  # 1KB
        try:
            big_content = b"x" * 2048  # 2KB > 1KB limit
            resp = integration_client.post(
                "/api/v1/extract",
                files={"file": ("big.png", big_content, "image/png")},
            )
            assert resp.status_code == 413
            assert "too large" in resp.json()["detail"].lower()
        finally:
            routes.MAX_UPLOAD_SIZE = original
    
    def test_get_result_404_nonexistent_job(self, integration_client):
        """GET /result for nonexistent job should return 404."""
        resp = integration_client.get(
            f"/api/v1/jobs/{self.MISSING_JOB_ID}/result"
        )
        assert resp.status_code == 404

    def test_delete_nonexistent_job_requires_auth(self, integration_client):
        """DELETE should require authentication before ownership checks."""
        resp = integration_client.delete(f"/api/v1/jobs/{self.MISSING_JOB_ID}")
        assert resp.status_code == 401

    def test_get_status_nonexistent_job_404(self, integration_client):
        """GET /jobs/{id} for nonexistent job should return 404."""
        resp = integration_client.get(f"/api/v1/jobs/{self.MISSING_JOB_ID}")
        assert resp.status_code == 404


class TestHealthEndpoint:
    """Test the health check endpoint."""
    
    def test_health_returns_ok(self, integration_client):
        """Health endpoint should return status ok."""
        resp = integration_client.get("/api/v1/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "model_loaded" in data


class TestFeedbackEndpoint:
    """Test the POST /api/v1/feedback endpoint."""
    
    def test_submit_bug_report(self, integration_client, tmp_path):
        """Submit a bug report for an existing job."""
        # First create a job
        test_img = tmp_path / "test.png"
        create_test_image(test_img)
        with open(test_img, "rb") as f:
            resp = integration_client.post(
                "/api/v1/extract",
                files={"file": ("test.png", f, "image/png")},
            )
        job_id = resp.json()["job_id"]
        
        # Submit feedback
        resp = integration_client.post(
            "/api/v1/feedback",
            json={
                "job_id": job_id,
                "type": "bug",
                "message": "Table structure is broken on row 3.",
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert "feedback_id" in data
        assert data["status"] == "submitted"
    
    def test_submit_content_violation(self, integration_client, tmp_path):
        """Submit a content violation report without a message."""
        test_img = tmp_path / "test.png"
        create_test_image(test_img)
        with open(test_img, "rb") as f:
            resp = integration_client.post(
                "/api/v1/extract",
                files={"file": ("test.png", f, "image/png")},
            )
        job_id = resp.json()["job_id"]
        
        resp = integration_client.post(
            "/api/v1/feedback",
            json={"job_id": job_id, "type": "content_violation"},
        )
        assert resp.status_code == 201
    
    def test_feedback_invalid_job_id(self, integration_client):
        """Feedback for a nonexistent job should return 404."""
        resp = integration_client.post(
            "/api/v1/feedback",
            json={"job_id": "11111111-1111-1111-1111-111111111111", "type": "bug"},
        )
        assert resp.status_code == 404
    
    def test_feedback_invalid_type(self, integration_client, tmp_path):
        """Feedback with an invalid type should return 422."""
        test_img = tmp_path / "test.png"
        create_test_image(test_img)
        with open(test_img, "rb") as f:
            resp = integration_client.post(
                "/api/v1/extract",
                files={"file": ("test.png", f, "image/png")},
            )
        job_id = resp.json()["job_id"]
        
        resp = integration_client.post(
            "/api/v1/feedback",
            json={"job_id": job_id, "type": "spam"},
        )
        assert resp.status_code == 422


class TestBatchedComponentLoading:
    """Test the batched component loading endpoints."""
    
    def _upload_and_wait(self, client, tmp_path, max_wait=60):
        """Helper: upload a test image and wait for completion. Returns job_id."""
        test_img = tmp_path / "test_batch.png"
        create_test_image(test_img)
        with open(test_img, "rb") as f:
            resp = client.post(
                "/api/v1/extract",
                files={"file": ("test_batch.png", f, "image/png")},
            )
        assert resp.status_code == 202
        job_id = resp.json()["job_id"]
        
        start = time.time()
        while time.time() - start < max_wait:
            resp = client.get(f"/api/v1/jobs/{job_id}")
            if resp.json()["status"] == "completed":
                return job_id
            elif resp.json()["status"] == "failed":
                pytest.fail(f"Job failed: {resp.json().get('error')}")
            time.sleep(0.5)
        pytest.fail("Job didn't complete in time")
    
    def test_result_metadata_returns_no_components(self, integration_client, tmp_path):
        """GET /result should return metadata only, no page/component data."""
        job_id = self._upload_and_wait(integration_client, tmp_path)
        resp = integration_client.get(f"/api/v1/jobs/{job_id}/result")
        assert resp.status_code == 200
        data = resp.json()
        assert "source_file" in data
        assert "total_pages" in data
        assert "total_components" in data
        assert "pages" not in data
        assert "components" not in data
    
    def test_batch_loading_first_batch(self, integration_client, tmp_path):
        """Fetch the first batch of components with offset=0."""
        job_id = self._upload_and_wait(integration_client, tmp_path)
        resp = integration_client.get(
            f"/api/v1/jobs/{job_id}/result/components",
            params={"offset": 0, "limit": 3},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["offset"] == 0
        assert data["limit"] == 3
        assert data["total"] > 0
        assert len(data["components"]) <= 3
        for comp in data["components"]:
            assert "page_number" in comp
            assert "id" in comp
            assert "category" in comp
            assert "base64" in comp
    
    def test_batch_loading_sequential_fetches_all(self, integration_client, tmp_path):
        """Sequentially fetch all components in batches of 3."""
        job_id = self._upload_and_wait(integration_client, tmp_path)
        
        # Get total
        resp = integration_client.get(f"/api/v1/jobs/{job_id}/result")
        total = resp.json()["total_components"]
        
        # Fetch all in batches
        all_components = []
        offset = 0
        limit = 3
        while True:
            resp = integration_client.get(
                f"/api/v1/jobs/{job_id}/result/components",
                params={"offset": offset, "limit": limit},
            )
            assert resp.status_code == 200
            data = resp.json()
            all_components.extend(data["components"])
            if not data["has_more"]:
                break
            offset += limit
        
        assert len(all_components) == total
    
    def test_batch_offset_beyond_total(self, integration_client, tmp_path):
        """Offset beyond total components should return empty list."""
        job_id = self._upload_and_wait(integration_client, tmp_path)
        resp = integration_client.get(
            f"/api/v1/jobs/{job_id}/result/components",
            params={"offset": 9999, "limit": 10},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["components"]) == 0
        assert data["has_more"] is False
    
    def test_different_offsets_return_different_components(self, integration_client, tmp_path):
        """Verify that offset=0 and offset=N return different component IDs."""
        job_id = self._upload_and_wait(integration_client, tmp_path)
        
        resp1 = integration_client.get(
            f"/api/v1/jobs/{job_id}/result/components",
            params={"offset": 0, "limit": 3},
        )
        resp2 = integration_client.get(
            f"/api/v1/jobs/{job_id}/result/components",
            params={"offset": 3, "limit": 3},
        )
        assert resp1.status_code == 200
        assert resp2.status_code == 200
        
        ids_batch1 = {c["id"] for c in resp1.json()["components"]}
        ids_batch2 = {c["id"] for c in resp2.json()["components"]}
        
        # The two batches must not overlap
        assert ids_batch1.isdisjoint(ids_batch2), (
            f"Batches overlap: {ids_batch1 & ids_batch2}"
        )
    
    def test_result_metadata_409_when_not_completed(self, integration_client, tmp_path):
        """GET /result should return 409 for a job that hasn't completed."""
        test_img = tmp_path / "test.png"
        create_test_image(test_img)
        with open(test_img, "rb") as f:
            resp = integration_client.post(
                "/api/v1/extract",
                files={"file": ("test.png", f, "image/png")},
            )
        job_id = resp.json()["job_id"]
        
        # Immediately check — job should still be queued/processing
        resp_status = integration_client.get(f"/api/v1/jobs/{job_id}")
        if resp_status.json()["status"] != "completed":
            resp = integration_client.get(f"/api/v1/jobs/{job_id}/result")
            assert resp.status_code == 409
            
            resp = integration_client.get(
                f"/api/v1/jobs/{job_id}/result/components",
                params={"offset": 0, "limit": 10},
            )
            assert resp.status_code == 409
    
    def test_components_nonexistent_job(self, integration_client):
        """Components endpoint should return 404 for nonexistent job."""
        resp = integration_client.get(
            "/api/v1/jobs/11111111-1111-1111-1111-111111111111/result/components",
            params={"offset": 0, "limit": 10},
        )
        assert resp.status_code == 404


class TestJobStoreUnit:
    """Unit tests for JobStore - these are real tests of actual behavior."""
    
    @pytest.mark.asyncio
    async def test_cleanup_old_jobs_removes_expired(self, tmp_path):
        """Test that cleanup_old_jobs actually deletes old job records."""
        db_path = tmp_path / "test.db"
        store = JobStore(db_path=str(db_path))
        await store.init()
        
        # Create a job
        job_id = await store.create_job("test.pdf", "/tmp/test.pdf")
        
        # Manually update created_at to be old (simulate 25 hours ago)
        old_time = "2024-01-01T00:00:00+00:00"
        import aiosqlite
        async with aiosqlite.connect(db_path) as db:
            await db.execute(
                "UPDATE jobs SET created_at = ? WHERE id = ?",
                (old_time, job_id)
            )
            await db.commit()
        
        # Cleanup should remove it
        count = await store.cleanup_old_jobs(max_age_hours=24)
        assert count == 1
        
        # Verify it's gone
        job = await store.get_job(job_id)
        assert job is None
        
        await store.close()
