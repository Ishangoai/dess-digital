import io
from collections.abc import Iterator

import docx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app.db import get_db
from app.llm import LLMClient
from app.minutes.profile_content import ProfileContent
from app.routers import draft as draft_routes
from app.routers import feedback as feedback_routes
from app.services import profile as profile_svc
from tests import minutes_samples as samples
from tests.fakes import ScriptedProvider
from tests.test_draft_routes import create


@pytest.fixture
def client(
    session_factory: sessionmaker[Session], db: Session, profile_content: ProfileContent
) -> TestClient:
    profile_svc.seed_profile(db, profile_content, slug="dess-standard", confirm_version=True)
    app = FastAPI()
    app.include_router(draft_routes.router, prefix="/api")
    app.include_router(feedback_routes.router, prefix="/api")

    def override_db() -> Iterator[Session]:
        with session_factory() as session:
            yield session

    provider = ScriptedProvider(samples.all_stage_outputs())
    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[draft_routes.llm_client] = lambda: LLMClient(provider, "fake-model")
    return TestClient(app)


def finished_draft(client: TestClient) -> str:
    """A completed run: mapping confirmed and minutes drafted in one call."""
    return create(client, auto_confirm_mapping="true")["id"]


def vote(client: TestClient, run_id: str, verdict: str, reason: str | None = None):  # noqa: ANN201
    return client.post(
        f"/api/drafts/{run_id}/feedback", json={"verdict": verdict, "reason": reason}
    )


def upload(client: TestClient, run_id: str, data: bytes, name: str = "final.docx"):  # noqa: ANN201
    return client.post(f"/api/drafts/{run_id}/final", files={"file": (name, data)})


def edited_copy(client: TestClient, run_id: str) -> bytes:
    """The downloaded draft with one sentence added to item 4."""
    doc = docx.Document(io.BytesIO(client.get(f"/api/drafts/{run_id}/document.docx").content))
    roof = next(p for p in doc.paragraphs if p.text.startswith("The Board approved phase one"))
    roof.add_run(" Priya Shah abstained.")
    buffer = io.BytesIO()
    doc.save(buffer)
    return buffer.getvalue()


def test_approving_a_finished_draft_scores_one(client: TestClient) -> None:
    run_id = finished_draft(client)

    response = vote(client, run_id, "approved")

    assert response.status_code == 201, response.text
    body = response.json()
    assert (body["verdict"], body["reward"], body["model"]) == ("approved", 1, "fake-model")
    assert [v["verdict"] for v in client.get(f"/api/drafts/{run_id}/feedback").json()] == [
        "approved"
    ]


def test_revision_needs_a_reason(client: TestClient) -> None:
    run_id = finished_draft(client)

    assert vote(client, run_id, "revision_requested").status_code == 422
    assert vote(client, run_id, "revision_requested", "   ").status_code == 422

    response = vote(client, run_id, "revision_requested", "Item 4 misses the dissent.")
    assert response.status_code == 201
    assert response.json()["reward"] == 0


def test_edited_is_only_by_upload(client: TestClient) -> None:
    assert vote(client, finished_draft(client), "edited").status_code == 422


def test_unfinished_draft_cannot_be_reviewed(client: TestClient) -> None:
    run_id = create(client)["id"]  # waiting for the mapping review
    assert vote(client, run_id, "approved").status_code == 409
    assert upload(client, run_id, b"x").status_code == 409


def test_unknown_verdict_is_rejected(client: TestClient) -> None:
    assert vote(client, finished_draft(client), "maybe").status_code == 422


def test_uploaded_edit_is_compared_with_the_draft(client: TestClient) -> None:
    run_id = finished_draft(client)

    response = upload(client, run_id, edited_copy(client, run_id))

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["verdict"] == "edited"
    assert body["filename"] == "final.docx"
    assert 0.8 < body["reward"] < 1
    changed = [i for i in body["comparison"]["items"] if i["status"] != "unchanged"]
    assert [(i["item_ref"], i["status"], i["words_added"]) for i in changed] == [("4", "edited", 3)]


def test_upload_from_another_draft_is_422(client: TestClient) -> None:
    first, second = finished_draft(client), finished_draft(client)
    assert upload(client, second, edited_copy(client, first)).status_code == 422


def test_upload_must_be_word(client: TestClient) -> None:
    run_id = finished_draft(client)
    assert upload(client, run_id, b"text", name="final.txt").status_code == 415
    assert upload(client, run_id, b"junk", name="final.docx").status_code == 415


def test_scores_group_feedback_by_setup(client: TestClient) -> None:
    first, second = finished_draft(client), finished_draft(client)
    vote(client, first, "approved")
    vote(client, first, "revision_requested", "Too short.")
    vote(client, second, "approved")
    similarity = upload(client, second, edited_copy(client, second)).json()["reward"]

    [score] = client.get("/api/feedback/scores").json()

    assert score == {
        "profile_slug": "dess-standard",
        "profile_version": 1,
        "model": "fake-model",
        "approvals": 2,
        "revisions": 1,
        "edits": 1,
        "votes": 4,
        "net": 1,
        "approval_rate": pytest.approx(2 / 3),
        "mean_similarity": pytest.approx(similarity),
        "expected": pytest.approx((2 + similarity + 1) / (4 + 2)),
    }


def test_scores_are_empty_without_feedback(client: TestClient) -> None:
    assert client.get("/api/feedback/scores").json() == []
