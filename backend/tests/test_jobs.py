import pytest

from app.models.job import Job, JobStatus
from app.services.job import transition_job


def create_test_job(status: JobStatus = JobStatus.PENDING) -> Job:
    """Create an in-memory Job object for testing."""
    return Job(
        function_name="dummy_function",
        function_params={},
        status=status,
    )


# VALID STATE TRANSITIONS


def test_pending_job_can_transition_to_running():
    job = create_test_job()

    transition_job(job, JobStatus.RUNNING)

    assert job.status == JobStatus.RUNNING


def test_running_job_can_transition_to_completed():
    job = create_test_job(JobStatus.RUNNING)

    transition_job(job, JobStatus.COMPLETED)

    assert job.status == JobStatus.COMPLETED


def test_running_job_can_transition_to_failed():
    job = create_test_job(JobStatus.RUNNING)

    transition_job(job, JobStatus.FAILED)

    assert job.status == JobStatus.FAILED


# INVALID STATE TRANSITIONS


def test_pending_job_cannot_transition_to_completed():
    job = create_test_job()

    with pytest.raises(ValueError):
        transition_job(job, JobStatus.COMPLETED)


def test_pending_job_cannot_transition_to_failed():
    job = create_test_job()

    with pytest.raises(ValueError):
        transition_job(job, JobStatus.FAILED)


def test_completed_job_cannot_transition_to_running():
    job = create_test_job(JobStatus.COMPLETED)

    with pytest.raises(ValueError):
        transition_job(job, JobStatus.RUNNING)


def test_failed_job_cannot_transition_to_running():
    job = create_test_job(JobStatus.FAILED)

    with pytest.raises(ValueError):
        transition_job(job, JobStatus.RUNNING)


def test_completed_job_cannot_transition_to_failed():
    job = create_test_job(JobStatus.COMPLETED)

    with pytest.raises(ValueError):
        transition_job(job, JobStatus.FAILED)


def test_failed_job_cannot_transition_to_completed():
    job = create_test_job(JobStatus.FAILED)

    with pytest.raises(ValueError):
        transition_job(job, JobStatus.COMPLETED)
