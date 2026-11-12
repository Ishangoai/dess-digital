import logging
from datetime import UTC, datetime
from types import FunctionType
from typing import Any
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models.job import Job, JobStatus
from app.schemas.job import JobResponse

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/jobs", tags=["jobs"])

ALLOWED_TRANSITIONS = {
    JobStatus.PENDING: {JobStatus.RUNNING},
    JobStatus.RUNNING: {JobStatus.COMPLETED, JobStatus.FAILED},
}


def transition_job(
    db: Session, job: Job, new_status: JobStatus, error_message: str | None = None
) -> Job:
    """Validate a job status transition and update its timestamps."""
    now = datetime.now(UTC)
    allowed_statuses = ALLOWED_TRANSITIONS.get(job.status, set())
    if new_status not in allowed_statuses:
        raise ValueError(f"Invalid job transition: {job.status} -> {new_status}")
    job.status = new_status
    if new_status == JobStatus.RUNNING:
        job.started_at = now
    elif new_status in {JobStatus.COMPLETED, JobStatus.FAILED}:
        job.completed_at = now
        job.error_message = error_message
    db.commit()
    db.refresh(job)
    return job


def execute_job(job_id: UUID, func: FunctionType, function_params: dict[str, Any]) -> None:
    """Execute a background function and track its status."""
    with SessionLocal() as db:
        job = db.get(Job, job_id)
        if job is None:
            logger.error("Job %s was not found.", job_id)
            return
        try:
            transition_job(db=db, job=job, new_status=JobStatus.RUNNING)
            func(**function_params)
            transition_job(db=db, job=job, new_status=JobStatus.COMPLETED)
        except Exception as exc:
            logger.exception("Job %s failed.", job_id)
            db.rollback()
            job = db.get(Job, job_id)
            if job is not None and job.status == JobStatus.RUNNING:
                transition_job(db=db, job=job, new_status=JobStatus.FAILED, error_message=str(exc))


def add_job(
    background_tasks: BackgroundTasks,
    func: FunctionType,
    function_params: dict[str, Any],
    db: Session,
) -> Job:
    """Create a job record and schedule its background execution."""
    job = Job(
        function_name=func.__name__, function_params=function_params, status=JobStatus.PENDING
    )
    db.add(job)
    db.flush()
    # The model's created_at default is applied when the row is inserted.
    db.commit()
    db.refresh(job)
    background_tasks.add_task(execute_job, job.id, func, function_params)
    return job


@router.get("/", response_model=list[JobResponse])
def get_jobs() -> list[JobResponse]:
    """Retrieve all jobs, newest first."""
    with SessionLocal() as db:
        statement = select(Job).order_by(Job.created_at.desc())
        jobs = db.scalars(statement).all()
        return [JobResponse.model_validate(job) for job in jobs]


@router.get("/{job_id}", response_model=JobResponse)
def get_job(job_id: UUID) -> JobResponse:
    """Retrieve a specific job by its ID."""
    with SessionLocal() as db:
        job = db.get(Job, job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Job not found.")
        return JobResponse.model_validate(job)
