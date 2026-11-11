import io
from collections.abc import Iterator
from pathlib import Path

import docx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app.db import get_db
from app.llm import LLMClient, LLMProviderError
from app.minutes.profile_content import ProfileContent
from app.models.draft import DraftRun
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
