
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from fastapi import BackgroundTasks
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models.job import Job, JobStatus


ALLOWED_TRANSITIONS = {
    JobStatus.PENDING: {JobStatus.RUNNING},
    JobStatus.RUNNING: {JobStatus.COMPLETED, JobStatus.FAILED},
    JobStatus.COMPLETED: set(),
    JobStatus.FAILED: set(),
}


def transition_job(job: Job, new_status: JobStatus) -> None:
    """Validate a job status transition and update its timestamps."""

    allowed_states = ALLOWED_TRANSITIONS[job.status]

    if new_status not in allowed_states:
        raise ValueError(
            f"Invalid job status transition: {job.status} -> {new_status}"
        )

    job.status = new_status

    if new_status == JobStatus.RUNNING:
        job.started_at = datetime.now(timezone.utc)

    elif new_status in {JobStatus.COMPLETED, JobStatus.FAILED}:
        job.completed_at = datetime.now(timezone.utc)


def execute_job(
    job_id: UUID,
    func: Callable[..., Any],
    function_params: dict[str, Any],
) -> None:
    """Execute a background function and persist its job status."""

    # First, mark the job as RUNNING.
    with SessionLocal() as db:
        job = db.get(Job, job_id)

        if job is None:
            return

        transition_job(job, JobStatus.RUNNING)
        db.commit()

    # Execute the actual function outside the database session.
    try:
        func(**function_params)

    except Exception as exc:
        # If execution fails, record the failure in a new session.
        with SessionLocal() as db:
            job = db.get(Job, job_id)

            if job is not None:
                transition_job(job, JobStatus.FAILED)
                job.error_message = str(exc)
                db.commit()

        return

    # If execution succeeds, record completion.
    with SessionLocal() as db:
        job = db.get(Job, job_id)

        if job is not None:
            transition_job(job, JobStatus.COMPLETED)
            db.commit()


def add_job(
    background_tasks: BackgroundTasks,
    db: Session,
    func: Callable[..., Any],
    function_params: dict[str, Any] | None = None,
) -> Job:
    """Create a job record and schedule its background execution."""

    params = function_params or {}

    # Create the job record.
    job = Job(
        function_name=func.__name__,
        function_params=params,
        status=JobStatus.PENDING,
    )

    db.add(job)
    db.commit()
    db.refresh(job)

    # Schedule the execution wrapper, not the original function directly.
    background_tasks.add_task(
        execute_job,
        job.id,
        func,
        params,
    )

    return job
