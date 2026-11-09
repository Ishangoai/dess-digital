from unittest.mock import Mock

from fastapi import BackgroundTasks

from app.services.job import add_job


def test_add_job_schedules_function_with_parameters():
    background_tasks = Mock(spec=BackgroundTasks)

    def dummy_function(document_id: str) -> None:
        pass

    function_params = {"document_id": "123"}

    add_job(
        background_tasks,
        dummy_function,
        function_params,
    )

    background_tasks.add_task.assert_called_once_with(
        dummy_function,
        document_id="123",
    )
