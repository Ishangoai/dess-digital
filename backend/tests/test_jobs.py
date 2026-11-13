from collections.abc import Generator
from datetime import datetime
from uuid import UUID

import pytest
from fastapi import BackgroundTasks
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models.job import Job, JobStatus
from app.routers import job as job_router


@pytest.fixture
def test_session_factory() -> Generator[sessionmaker[Session]]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(engine)
    Base.metadata.create_all(engine)

    yield TestingSessionLocal

    Base.metadata.drop_all(engine)
    engine.dispose()


def test_add_job_creates_pending_job(test_session_factory: sessionmaker[Session]) -> None:
    background_tasks = BackgroundTasks()

    def process_document(filename: str) -> None:
        pass

    with test_session_factory() as db:
        created_job = job_router.add_job(
            background_tasks=background_tasks,
            func=process_document,
            function_params={"filename": "document.pdf"},
            db=db,
        )

        assert created_job.status == JobStatus.PENDING
        assert created_job.function_name == "process_document"
        assert created_job.function_params == {"filename": "document.pdf"}
        assert isinstance(created_job.id, UUID)
        assert isinstance(created_job.created_at, datetime)
        assert created_job.started_at is None
        assert created_job.completed_at is None
        assert len(background_tasks.tasks) == 1

        job_id = created_job.id

    # Verify that the job was persisted in the database.
    with test_session_factory() as db:
        saved_job = db.get(Job, job_id)

        assert saved_job is not None
        assert saved_job.status == JobStatus.PENDING


def test_execute_job_completes_successfully(
    test_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def process_document(filename: str) -> None:
        assert filename == "document.pdf"

    with test_session_factory() as db:
        created_job = Job(
            function_name="process_document",
            function_params={"filename": "document.pdf"},
            status=JobStatus.PENDING,
        )

        db.add(created_job)
        db.commit()
        db.refresh(created_job)

        job_id = created_job.id

    monkeypatch.setattr(job_router, "SessionLocal", test_session_factory)

    job_router.execute_job(
        job_id=job_id,
        func=process_document,
        function_params={"filename": "document.pdf"},
    )

    with test_session_factory() as db:
        completed_job = db.get(Job, job_id)

        assert completed_job is not None
        assert completed_job.status == JobStatus.COMPLETED
        assert completed_job.started_at is not None
        assert completed_job.completed_at is not None
        assert completed_job.error_message is None


def test_execute_job_records_failure(
    test_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def process_document(filename: str) -> None:
        raise ValueError("Document processing failed")

    with test_session_factory() as db:
        created_job = Job(
            function_name="process_document",
            function_params={"filename": "document.pdf"},
            status=JobStatus.PENDING,
        )

        db.add(created_job)
        db.commit()
        db.refresh(created_job)

        job_id = created_job.id

    monkeypatch.setattr(job_router, "SessionLocal", test_session_factory)

    job_router.execute_job(
        job_id=job_id,
        func=process_document,
        function_params={"filename": "document.pdf"},
    )

    with test_session_factory() as db:
        failed_job = db.get(Job, job_id)

        assert failed_job is not None
        assert failed_job.status == JobStatus.FAILED
        assert failed_job.started_at is not None
        assert failed_job.completed_at is not None
        assert failed_job.error_message == "Document processing failed"


def test_invalid_job_transition_is_rejected(
    test_session_factory: sessionmaker[Session],
) -> None:
    with test_session_factory() as db:
        created_job = Job(
            function_name="process_document",
            function_params={},
            status=JobStatus.PENDING,
        )

        db.add(created_job)
        db.commit()

        with pytest.raises(ValueError, match="Invalid job transition"):
            job_router.transition_job(
                db=db,
                job=created_job,
                new_status=JobStatus.COMPLETED,
            )
