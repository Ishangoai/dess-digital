"""Edited copies through the API: stored originals, the side-by-side review, and edit labels."""

import io
import re
from collections.abc import Iterator

import docx
import pytest
from docx.document import Document
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.db import get_db
from app.llm import LLMClient
from app.llm.types import CompletionRequest
from app.minutes.edit_labels import EditLabel, EditLabels
from app.minutes.profile_content import ProfileContent
from app.models.edits import ExportedDocument
from app.routers import draft as draft_routes
from app.services import profile as profile_svc
from tests import minutes_samples as samples
from tests.fakes import ScriptedProvider
from tests.test_alignment import _link_reply
from tests.test_draft_routes import create


@pytest.fixture
def provider() -> ScriptedProvider:
    return ScriptedProvider(samples.all_stage_outputs())


@pytest.fixture
def client(
    session_factory: sessionmaker[Session],
    db: Session,
    profile_content: ProfileContent,
    provider: ScriptedProvider,
) -> TestClient:
    profile_svc.seed_profile(db, profile_content, slug="dess-standard", confirm_version=True)
    app = FastAPI()
    app.include_router(draft_routes.router, prefix="/api")

    def override_db() -> Iterator[Session]:
        with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[draft_routes.llm_client] = lambda: LLMClient(provider, "fake-model")
    return TestClient(app)


def download(client: TestClient, run_id: str) -> Document:
    response = client.get(f"/api/drafts/{run_id}/document.docx")
    assert response.status_code == 200
    return docx.Document(io.BytesIO(response.content))


def upload(client: TestClient, run_id: str, doc: Document) -> dict:
    buffer = io.BytesIO()
    doc.save(buffer)
    files = {"file": ("final.docx", buffer.getvalue())}
    response = client.post(f"/api/drafts/{run_id}/final", files=files)
    assert response.status_code == 201, response.text
    return response.json()


def para(doc: Document, starts: str):  # noqa: ANN201
    return next(p for p in doc.paragraphs if p.text.startswith(starts))


def edited_draft(client: TestClient) -> tuple[str, str]:
    """A finished draft, downloaded, edited the way a professional would, and uploaded."""
    run_id = create(client, auto_confirm_mapping="true")["id"]
    doc = download(client, run_id)
    roof = para(doc, "The Board approved phase one only")
    roof.runs[0].text = roof.runs[0].text.replace("The Board approved", "It was resolved that")
    apologies = para(doc, "Apologies were received from Daniel.")
    apologies.runs[0].text = "Apologies were received from the Chief Executive."
    doc.add_comment(runs=[roof.runs[-1]], text="The Company Secretary will write.", author="Jane")
    _link_reply(doc, reply_index=-1, parent_index=0)
    feedback = upload(client, run_id, doc)
    return run_id, feedback["edited_document_id"]


def test_every_download_is_stored_exactly(client: TestClient, db: Session) -> None:
    run_id = create(client, auto_confirm_mapping="true")["id"]
    first = client.get(f"/api/drafts/{run_id}/document.docx").content
    client.get(f"/api/drafts/{run_id}/document.docx")

    exports = list(db.scalars(select(ExportedDocument).order_by(ExportedDocument.created_at)))
    assert len(exports) == 2
    assert exports[0].data == first
    assert exports[0].marks[0]["role"] == "title"


def test_upload_is_lined_up_with_the_download_it_came_from(client: TestClient) -> None:
    run_id, edited_id = edited_draft(client)

    [summary] = client.get(f"/api/drafts/{run_id}/edits").json()
    assert summary["id"] == edited_id
    assert summary["original_recreated"] is False
    assert summary["counts"]["changed"] == 2

    review = client.get(f"/api/drafts/{run_id}/edits/{edited_id}").json()
    roof = next(p for p in review["paragraphs"] if p["paragraph_id"] == "4.p2")
    assert roof["status"] == "changed"
    assert roof["diff"][0] == {"op": "delete", "text": "The Board approved "}
    assert review["answers"] == [{
        "question_id": "Q1",
        "question": "Who was asked to write to tenants about the roof works?",
        "reply": "The Company Secretary will write.",
        "author": "Jane",
    }]  # fmt: skip
    assert review["comments"][0]["question_id"] == "Q1"


def test_a_copy_without_its_id_uses_the_latest_download(client: TestClient) -> None:
    run_id = create(client, auto_confirm_mapping="true")["id"]
    doc = download(client, run_id)
    doc.core_properties.identifier = ""  # e.g. pasted into another file

    edited = upload(client, run_id, doc)
    [summary] = client.get(f"/api/drafts/{run_id}/edits").json()

    assert edited["reward"] == 1.0
    assert summary["original_recreated"] is False


def test_without_any_stored_download_the_original_is_rendered_again(
    client: TestClient, db: Session
) -> None:
    run_id = create(client, auto_confirm_mapping="true")["id"]
    doc = download(client, run_id)
    db.query(ExportedDocument).delete()  # as if it was downloaded before exports were stored
    db.commit()

    edited = upload(client, run_id, doc)
    [summary] = client.get(f"/api/drafts/{run_id}/edits").json()

    assert edited["reward"] == 1.0
    assert summary["original_recreated"] is True


def test_unknown_edit_is_404(client: TestClient) -> None:
    run_id = create(client, auto_confirm_mapping="true")["id"]
    missing = "00000000-0000-0000-0000-000000000000"
    assert client.get(f"/api/drafts/{run_id}/edits/{missing}").status_code == 404


def test_classify_labels_cheap_edits_in_code_and_the_rest_by_model(
    client: TestClient, provider: ScriptedProvider
) -> None:
    run_id, edited_id = edited_draft(client)

    def labels(request: CompletionRequest) -> EditLabels:
        content = request.messages[0].content
        assert isinstance(content, str)
        return EditLabels(labels=[
            EditLabel(edit_id=e, kind="wording_style", dimensions=["WS5"], cause="profile_silent",
                      support="not_applicable", evidence=[], profile_basis=None,
                      pattern="resolution wording", reason="House phrasing for resolutions.")
            for e in re.findall(r"^\[(E\d+)\]", content, flags=re.M)
        ])  # fmt: skip

    provider.responses["EditLabels"] = labels
    review = client.post(f"/api/drafts/{run_id}/edits/{edited_id}/classify").json()

    by_paragraph = {p["paragraph_id"]: p["labels"] for p in review["paragraphs"]}
    [role] = by_paragraph["1.p1"]
    assert (role["source"], role["dimensions"], role["cause"], role["route"]) == (
        "code",
        ["WS4"],
        "profile_not_applied",
        "defect",
    )
    [wording] = by_paragraph["4.p2"]
    assert (wording["source"], wording["route"]) == ("model", "candidate")
    assert [(f["pattern"], f["route"], f["count"]) for f in review["findings"]] == [
        ("resolution wording", "candidate", 1),
        ("name replaced by role", "defect", 1),
    ]
    assert review["classified_at"] is not None and review["classify_error"] is None

    sent = provider.requests[-1].messages[0].content
    assert "<selection>" in sent and "<item_evidence>" in sent
    stages = [c["stage"] for c in client.get(f"/api/drafts/{run_id}").json()["llm_calls"]]
    assert stages[-1] == "classify:4"


def test_classifying_again_replaces_the_labels(
    client: TestClient, provider: ScriptedProvider
) -> None:
    run_id, edited_id = edited_draft(client)
    provider.responses["EditLabels"] = EditLabels(labels=[])
    url = f"/api/drafts/{run_id}/edits/{edited_id}/classify"

    first = client.post(url).json()
    second = client.post(url).json()

    assert len(second["findings"]) == len(first["findings"]) == 1  # the code label only
    assert "no label for" in second["classify_error"]
