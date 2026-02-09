"""Pydantic request/response schemas for the Yoink API."""

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field


class ProgressInfo(BaseModel):
    current_page: int = 0
    total_pages: int = 0


class JobResponse(BaseModel):
    """Returned on job creation (POST /extract)."""
    job_id: str
    status: str


class JobStatusResponse(BaseModel):
    """Returned on job status poll (GET /jobs/{id})."""
    job_id: str
    status: str
    filename: str
    progress: ProgressInfo
    error: Optional[str] = None
    created_at: str


class HealthResponse(BaseModel):
    status: str = "ok"
    model_loaded: bool = False


class FeedbackRequest(BaseModel):
    """Request body for POST /feedback."""
    job_id: str
    type: Literal["bug", "content_violation"]
    message: Optional[str] = None


class FeedbackResponse(BaseModel):
    """Returned on feedback submission."""
    feedback_id: str
    status: str = "submitted"


class ResultMetadataResponse(BaseModel):
    """Returned on GET /jobs/{id}/result — metadata only, no components."""
    source_file: str
    total_pages: int
    total_components: int


class ComponentBatchResponse(BaseModel):
    """Returned on GET /jobs/{id}/result/components — a batch of components."""
    offset: int
    limit: int
    total: int
    has_more: bool
    components: list[dict]


class ErrorResponse(BaseModel):
    detail: str
