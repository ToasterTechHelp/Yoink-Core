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


class RenameJobRequest(BaseModel):
    """Request body for PATCH /jobs/{id}/rename."""
    base_name: str = Field(..., max_length=120)


class RenameJobResponse(BaseModel):
    """Returned on successful job rename."""
    job_id: str
    title: str


class ResultMetadataResponse(BaseModel):
    """Returned on GET /jobs/{id}/result — metadata only, no components."""
    source_file: str
    total_pages: int
    total_components: int
    is_guest: bool = False


class ComponentBatchResponse(BaseModel):
    """Returned on GET /jobs/{id}/result/components — a batch of components."""
    offset: int
    limit: int
    total: int
    has_more: bool
    components: list[dict]


class ComponentOut(BaseModel):
    """A single extracted component with a URL (no base64)."""
    id: int
    page_number: int
    category: str
    original_label: str = ""
    confidence: float = 0.0
    bbox: list = []
    url: str


class GuestResultResponse(BaseModel):
    """Full result for guest jobs — metadata + component URLs."""
    source_file: str
    total_pages: int
    total_components: int
    components: list[ComponentOut]


class ErrorResponse(BaseModel):
    detail: str
