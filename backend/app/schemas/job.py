from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.models.job import JobStatus


class JobResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    function_name: str
    function_params: dict
    status: JobStatus
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    error_message: str | None
