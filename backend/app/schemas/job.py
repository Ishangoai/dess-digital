from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.job import JobStatus


class JobCreate(BaseModel):
    """Schema for creating a new background job."""

    function_name: str = Field(min_length=1, max_length=255)
    function_params: dict[str, Any] = Field(default_factory=dict)


class JobResponse(BaseModel):
    """Schema for returning a job through the API."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    function_name: str
    status: JobStatus
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    error_message: str | None


class JobListResponse(BaseModel):
    """Schema for returning a collection of jobs."""

    jobs: list[JobResponse]
    total: int
