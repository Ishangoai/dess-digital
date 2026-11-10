from collections.abc import Callable
from typing import Any

from fastapi import BackgroundTasks

from app.models.job import Job, JobStatus

ALLOWED_TRANSITIONS = {
    JobStatus.PENDING: {JobStatus.RUNNING},
    JobStatus.RUNNING: {
        JobStatus.COMPLETED,
        JobStatus.FAILED,
    },
    JobStatus.COMPLETED: set(),
    JobStatus.FAILED: set(),
}


def transition_job(job: Job, new_status: JobStatus) -> None:
    """Validate and perform a job status transition."""

    allowed_states = ALLOWED_TRANSITIONS[job.status]

    if new_status not in allowed_states:
        raise ValueError(f"Invalid job status transition: {job.status} -> {new_status}")

    job.status = new_status


def add_job(
    background_tasks: BackgroundTasks,
    dummy_function: Callable[..., Any],
    function_params: dict[str, Any],
) -> None:
    """Schedule a function using FastAPI background tasks."""

    background_tasks.add_task(
        dummy_function,
        **function_params,
    )
