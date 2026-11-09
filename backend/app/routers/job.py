from collections.abc import Generator
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models.job import Job
from app.schemas.job import JobListResponse, JobResponse

router = APIRouter(
    prefix="/jobs",
    tags=["Jobs"],
)


def get_db() -> Generator[Session]:
    """Provide a database session for an API request."""

    db = SessionLocal()

    try:
        yield db
    finally:
        db.close()


@router.get(
    "/",
    response_model=JobListResponse,
    status_code=status.HTTP_200_OK,
)
def get_jobs(
    db: Annotated[Session, Depends(get_db)],
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
) -> JobListResponse:
    """Retrieve a paginated list of jobs."""

    # Build the database query.
    statement = (
        select(Job)
        .order_by(Job.created_at.desc())
        .offset(offset)
        .limit(limit)
    )

    # Retrieve Job objects from PostgreSQL.
    jobs = db.scalars(statement).all()

    # Convert SQLAlchemy Job objects into Pydantic JobResponse objects.
    job_responses = [
        JobResponse.model_validate(job)
        for job in jobs
    ]

    # Count the total number of jobs.
    total = db.scalar(
        select(func.count()).select_from(Job)
    )

    # Return the response.
    return JobListResponse(
        jobs=job_responses,
        total=total or 0,
    )


@router.get(
    "/{job_id}",
    response_model=JobResponse,
    status_code=status.HTTP_200_OK,
)
def get_job(
    job_id: UUID,
    db: Annotated[Session, Depends(get_db)],
) -> JobResponse:
    """Retrieve a specific job using its UUID."""

    # Retrieve the job using its primary key.
    job = db.get(Job, job_id)

    # Check whether the job exists.
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job with ID {job_id} was not found.",
        )

    # Convert the SQLAlchemy object into a Pydantic response.
    return JobResponse.model_validate(job)
