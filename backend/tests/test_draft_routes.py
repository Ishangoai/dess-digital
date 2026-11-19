import io
import json
from collections.abc import Iterator
from pathlib import Path

import docx
import pytest
from docx.oxml.ns import qn
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings
from app.db import get_db
from app.llm import LLMClient, LLMProviderError
from app.minutes.profile_content import ProfileContent
from app.models.draft import DraftRun, ExportedDocument
from app.routers import draft as draft_routes
from app.services import profile as profile_svc
from tests import minutes_samples as samples
from tests.fakes import ScriptedProvider

FIXTURES = Path(__file__).parent / "fixtures" / "minutes"


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


def files(*names: str) -> dict:
    roles = {"agenda.txt": "agenda", "transcript.txt": "transcript"}
    return {roles[n]: (n, (FIXTURES / n).read_bytes(), "text/plain") for n in names}


def create(client: TestClient, **form: str) -> dict:
    response = client.post("/api/drafts", files=files("agenda.txt", "transcript.txt"), data=form)
    assert response.status_code == 201, response.text
    return response.json()


def test_upload_runs_mapping_and_waits_for_review(client: TestClient) -> None:
    run = create(client, organisation="Northbridge Housing Trust")

    assert run["status"] == "awaiting_mapping_review"
    assert run["profile_slug"] == "dess-standard"
    assert [d["source_id"] for d in run["documents"]] == ["A", "T"]
    assert run["meeting_info"]["organisation"] == "Northbridge Housing Trust"
    assert run["draft"] is None
    assert [c["stage"] for c in run["llm_calls"]] == ["evidence"]


def test_mapping_review_shows_excerpts(client: TestClient) -> None:
    run = create(client)
    review = client.get(f"/api/drafts/{run['id']}/mapping").json()

    assert review["valid_item_refs"] == ["1", "2", "3", "4", "5"]
    roof = next(s for s in review["segments"] if s["segment_id"] == "S4")
    assert roof["excerpt"].startswith("Chair: Item four.")
    assert [(u["start"], u["end"]) for u in review["uncovered"]] == [(5, 5)]  # the car park aside


def test_corrected_mapping_then_generate(client: TestClient, provider: ScriptedProvider) -> None:
    run_id = create(client)["id"]
    mapping = client.get(f"/api/drafts/{run_id}/mapping").json()["mapping"]
    mapping["segments"][3]["source"]["start"] = 5

    assert client.put(f"/api/drafts/{run_id}/mapping", json=mapping).status_code == 200
    result = client.post(f"/api/drafts/{run_id}/generate").json()

    assert result["status"] == "completed"
    assert result["mapping_edited"] is True
    assert result["draft"]["questions"][0]["question_id"] == "Q1"
    assert [c["stage"] for c in result["llm_calls"]] == [
        "evidence",
        "policy",
        "style",
        "validation",
        "reconsideration",
    ]
    assert result["usage_total"]["total_tokens"] == 5 * 110
    assert "T5-13" in provider.requests[1].messages[0].content  # corrected range was used

    debug = client.get(f"/api/drafts/{run_id}?debug=true").json()
    assert debug["selection"]["items"][3]["outcomes"][0]["outcome_type"] == "approved"


def test_generate_twice_is_409(client: TestClient) -> None:
    run_id = create(client)["id"]
    assert client.post(f"/api/drafts/{run_id}/generate").status_code == 200
    assert client.post(f"/api/drafts/{run_id}/generate").status_code == 409


def test_auto_confirm_drafts_in_one_call(client: TestClient) -> None:
    run = create(client, auto_confirm_mapping="true")
    assert run["status"] == "completed"
    assert run["draft"]["items"][3]["item_ref"] == "4"


def test_invalid_mapping_is_422(client: TestClient) -> None:
    run_id = create(client)["id"]
    mapping = client.get(f"/api/drafts/{run_id}/mapping").json()["mapping"]
    mapping["segments"][0]["item_ref"] = "42"

    response = client.put(f"/api/drafts/{run_id}/mapping", json=mapping)
    assert response.status_code == 422
    assert response.json()["detail"]["mapping_errors"] == ["segment S1: unknown item '42'"]


def test_missing_inputs_are_422(client: TestClient) -> None:
    no_proceedings = client.post("/api/drafts", files=files("agenda.txt"))
    assert no_proceedings.status_code == 422
    assert "transcript or meeting notes" in no_proceedings.json()["detail"]
    assert (
        client.post(
            "/api/drafts", files={"transcript": files("transcript.txt")["transcript"]}
        ).status_code
        == 422
    )


def test_unsupported_file_is_415(client: TestClient) -> None:
    response = client.post(
        "/api/drafts",
        files={
            "agenda": ("agenda.pdf", b"%PDF-1.7", "application/pdf"),
            "transcript": files("transcript.txt")["transcript"],
        },
    )
    assert response.status_code == 415


def test_blocked_run_cannot_generate(client: TestClient, provider: ScriptedProvider) -> None:
    provider.responses["EvidenceAnalysis"] = samples.analysis(problems=True)
    run = create(client)

    assert run["status"] == "blocked"
    assert run["blocked_reasons"] == ["proceedings_unusable: Empty."]
    assert client.post(f"/api/drafts/{run['id']}/generate").status_code == 409


def test_failed_stage_is_recorded_and_retryable(
    client: TestClient, provider: ScriptedProvider, db: Session
) -> None:
    run_id = create(client)["id"]
    provider.responses["DraftMinutes"] = LLMProviderError("quota exceeded")

    failed = client.post(f"/api/drafts/{run_id}/generate").json()
    assert failed["status"] == "failed"
    assert failed["error_stage"] == "style"
    assert failed["llm_calls"][-1]["ok"] is False

    provider.responses["DraftMinutes"] = samples.draft()
    assert client.post(f"/api/drafts/{run_id}/generate").json()["status"] == "completed"
    assert db.query(DraftRun).count() == 1


def test_unknown_profile_is_422(client: TestClient) -> None:
    response = client.post(
        "/api/drafts", files=files("agenda.txt", "transcript.txt"), data={"profile_slug": "nope"}
    )
    assert response.status_code == 422


def test_list_drafts(client: TestClient) -> None:
    create(client)
    create(client)
    assert len(client.get("/api/drafts").json()) == 2


def test_unknown_run_is_404(client: TestClient) -> None:
    assert client.get("/api/drafts/00000000-0000-0000-0000-000000000000").status_code == 404


def test_document_download(client: TestClient) -> None:
    run_id = create(client, auto_confirm_mapping="true")["id"]

    response = client.get(f"/api/drafts/{run_id}/document.docx")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/vnd.openxmlformats")
    doc = docx.Document(io.BytesIO(response.content))
    assert len(list(doc.comments)) == 1


def test_document_with_template(client: TestClient) -> None:
    run_id = create(client, auto_confirm_mapping="true")["id"]
    template = docx.Document()
    template.add_paragraph("{{MINUTES}}")
    buffer = io.BytesIO()
    template.save(buffer)

    response = client.post(
        f"/api/drafts/{run_id}/document",
        files={"template": ("t.docx", buffer.getvalue(), "application/octet-stream")},
    )
    assert response.status_code == 200
    assert "{{MINUTES}}" not in [
        p.text for p in docx.Document(io.BytesIO(response.content)).paragraphs
    ]

    bad = client.post(f"/api/drafts/{run_id}/document", files={"template": ("t.docx", b"junk")})
    assert bad.status_code == 415


def test_document_before_draft_is_409(client: TestClient) -> None:
    run_id = create(client)["id"]
    assert client.get(f"/api/drafts/{run_id}/document.docx").status_code == 409


def test_failed_analysis_can_be_retried_without_reupload(
    client: TestClient, provider: ScriptedProvider
) -> None:
    good = provider.responses["EvidenceAnalysis"]
    provider.responses["EvidenceAnalysis"] = LLMProviderError("429 quota exceeded")
    failed = create(client)
    assert failed["status"] == "failed"
    assert failed["error_stage"] == "evidence"

    generate = client.post(f"/api/drafts/{failed['id']}/generate")
    assert generate.status_code == 409
    assert "retry it first" in generate.json()["detail"]

    provider.responses["EvidenceAnalysis"] = good
    retried = client.post(f"/api/drafts/{failed['id']}/analyse").json()
    assert retried["status"] == "awaiting_mapping_review"
    assert retried["error"] is None
    assert [c["ok"] for c in retried["llm_calls"]] == [False, True]
    assert client.post(f"/api/drafts/{failed['id']}/generate").json()["status"] == "completed"


def test_only_failed_analysis_can_be_retried(client: TestClient) -> None:
    run_id = create(client)["id"]
    assert client.post(f"/api/drafts/{run_id}/analyse").status_code == 409


def test_calls_show_what_was_sent_and_received(client: TestClient) -> None:
    run = create(client, auto_confirm_mapping="true")
    calls = client.get(f"/api/drafts/{run['id']}/calls").json()

    assert [c["stage"] for c in calls] == [c["stage"] for c in run["llm_calls"]]
    evidence, style = calls[0], next(c for c in calls if c["stage"] == "style")
    assert "Minutes Profile" in evidence["system_prompt"]
    assert "<transcript" in evidence["prompt"] and "<task>" in evidence["prompt"]
    assert "<selection>" in style["prompt"]
    assert json.loads(style["output"])["items"]
    # The run payload stays small.
    assert "prompt" not in run["llm_calls"][0]


def test_failed_call_keeps_its_input(client: TestClient, provider: ScriptedProvider) -> None:
    run_id = create(client)["id"]
    provider.responses["DraftMinutes"] = LLMProviderError("quota exceeded")
    client.post(f"/api/drafts/{run_id}/generate")

    failed = client.get(f"/api/drafts/{run_id}/calls").json()[-1]
    assert failed["ok"] is False
    assert "<task>" in failed["prompt"]
    assert failed["output"] is None


def test_background_upload_returns_at_once_then_maps(client: TestClient) -> None:
    response = client.post(
        "/api/drafts", files=files("agenda.txt", "transcript.txt"), data={"background": "true"}
    )
    assert response.status_code == 201, response.text
    created = response.json()
    assert created["status"] == "analysing"
    assert created["llm_calls"] == []

    # TestClient runs background tasks before returning, so stage 1 has finished here.
    run = client.get(f"/api/drafts/{created['id']}").json()
    assert run["status"] == "awaiting_mapping_review"
    assert [c["stage"] for c in run["llm_calls"]] == ["evidence"]


def test_background_failure_marks_run_failed(
    client: TestClient, provider: ScriptedProvider
) -> None:
    provider.responses["EvidenceAnalysis"] = LLMProviderError("quota exceeded")
    created = client.post(
        "/api/drafts", files=files("agenda.txt", "transcript.txt"), data={"background": "true"}
    ).json()

    run = client.get(f"/api/drafts/{created['id']}").json()
    assert run["status"] == "failed"
    assert run["error_stage"] == "evidence"


def _edited(original: bytes) -> bytes:
    doc = docx.Document(io.BytesIO(original))
    target = next(p for p in doc.paragraphs if p.text == "The Board noted the report.")
    target.runs[0].text = "The Board noted the report and thanked the team."
    buffer = io.BytesIO()
    doc.save(buffer)
    return buffer.getvalue()


def _upload(client: TestClient, run_id: str, data: bytes, name: str = "edited.docx"):
    return client.post(
        f"/api/drafts/{run_id}/edited-document",
        files={"file": (name, data, "application/octet-stream")},
    )


def test_downloads_are_stored(client: TestClient, db: Session) -> None:
    run_id = create(client, auto_confirm_mapping="true")["id"]
    first = client.get(f"/api/drafts/{run_id}/document.docx").content
    client.get(f"/api/drafts/{run_id}/document.docx")

    exports = db.scalars(select(ExportedDocument)).all()
    assert len(exports) == 2
    assert exports[0].data == first
    assert exports[0].manifest["questions"] == {"0": "Q1"}
    assert docx.Document(io.BytesIO(first)).core_properties.identifier == (
        f"dess-export:{exports[0].id}"
    )


def test_upload_edited_minutes_and_compare(client: TestClient) -> None:
    run_id = create(client, auto_confirm_mapping="true")["id"]
    client.get(f"/api/drafts/{run_id}/document.docx")
    original = client.get(f"/api/drafts/{run_id}/document.docx").content

    response = _upload(client, run_id, _edited(original))
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["filename"] == "edited.docx"
    assert body["comparison"]["counts"]["changed"] == 1
    changed = [
        c for s in body["comparison"]["sections"] for c in s["changes"] if c["status"] == "changed"
    ]
    assert changed[0]["paragraph_id"] == "3.p1"

    exports = client.get(f"/api/drafts/{run_id}/edited-document").json()
    assert exports["id"] == body["id"]
    assert client.get(f"/api/drafts/{run_id}").json()["edited_document"]["id"] == body["id"]


def test_upload_finds_the_export_it_came_from(client: TestClient, db: Session) -> None:
    run_id = create(client, auto_confirm_mapping="true")["id"]
    original = client.get(f"/api/drafts/{run_id}/document.docx").content
    client.get(f"/api/drafts/{run_id}/document.docx")  # a later download

    body = _upload(client, run_id, _edited(original)).json()
    first = db.scalars(select(ExportedDocument).order_by(ExportedDocument.created_at)).first()
    assert first is not None and body["export_id"] == str(first.id)


def test_upload_without_a_stored_download(client: TestClient, db: Session) -> None:
    """Files downloaded before exports were stored have no bookmarks; text matching applies."""
    run_id = create(client, auto_confirm_mapping="true")["id"]
    doc = docx.Document(io.BytesIO(client.get(f"/api/drafts/{run_id}/document.docx").content))
    for tag in ("w:bookmarkStart", "w:bookmarkEnd"):
        for el in list(doc.element.body.iter(qn(tag))):
            el.getparent().remove(el)
    doc.core_properties.identifier = ""
    buffer = io.BytesIO()
    doc.save(buffer)
    for export in db.scalars(select(ExportedDocument)):
        db.delete(export)
    db.commit()

    response = _upload(client, run_id, buffer.getvalue())
    assert response.status_code == 201
    comparison = response.json()["comparison"]
    assert comparison["bookmarks_found"] == 0
    assert {k for k, v in comparison["counts"].items() if v} == {"unchanged"}


def test_upload_errors(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    run_id = create(client)["id"]
    assert _upload(client, run_id, b"junk").status_code == 409  # no draft yet
    assert client.get(f"/api/drafts/{run_id}/edited-document").status_code == 404

    done = create(client, auto_confirm_mapping="true")["id"]
    assert _upload(client, done, b"junk").status_code == 415
    monkeypatch.setattr(settings, "minutes_max_upload_bytes", 10)
    assert _upload(client, done, b"x" * 11).status_code == 413
