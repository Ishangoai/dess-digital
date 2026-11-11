
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
    """Validate and apply a job status transition."""
    allowed_states = ALLOWED_TRANSITIONS[job.status]

    if new_status not in allowed_states:
        raise ValueError(
            f"Invalid job status transition: {job.status} -> {new_status}"
        )

    job.status = new_status


def execute_job(
    job_id: UUID,
    func: Callable[..., Any],
    function_params: dict[str, Any],
) -> None:
    """Execute a background function and persist its job status."""

    # Use a separate database session to mark the job as RUNNING.
    with SessionLocal() as db:
        job = db.get(Job, job_id)

        if job is None:
            return

        transition_job(job, JobStatus.RUNNING)
        job.started_at = datetime.now(timezone.utc)
        db.commit()

    # Execute the actual function without holding a database session open.
    try:
        func(**function_params)

    except Exception as exc:
        # Record failure using a new database session.
        with SessionLocal() as db:
            job = db.get(Job, job_id)

            if job is not None:
                transition_job(job, JobStatus.FAILED)
                job.completed_at = datetime.now(timezone.utc)
                job.error_message = str(exc)
                db.commit()

    else:
        # Record successful completion using a new database session.
        with SessionLocal() as db:
            job = db.get(Job, job_id)

            if job is not None:
                transition_job(job, JobStatus.COMPLETED)
                job.completed_at = datetime.now(timezone.utc)
                db.commit()


def add_job(
    background_tasks: BackgroundTasks,
    db: Session,
    func: Callable[..., Any],
    function_params: dict[str, Any] | None = None,
) -> Job:
    """Create a job record and schedule its background execution."""

    params = function_params or {}

    # Create and save the job record before scheduling execution.
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
