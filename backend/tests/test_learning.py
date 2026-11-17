from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app.db import get_db
from app.llm import LLMClient
from app.minutes.evidence import EvidenceBundle, MeetingInfo
from app.minutes.profile_content import ProfileContent
from app.minutes.prompts import LESSONS_HEADING, PromptContext
from app.routers import draft as draft_routes
from app.routers import profile as profile_routes
from app.services import learning
from app.services import profile as profile_svc
from app.services.learning import Entry, Lesson, LessonAction, LessonChange, LessonsUpdate
from tests import minutes_samples as samples
from tests.fakes import ScriptedProvider
from tests.test_draft_routes import create
from tests.test_feedback import edited_copy, upload, vote


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
    app.include_router(profile_routes.router, prefix="/api")

    def override_db() -> Iterator[Session]:
        with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[draft_routes.llm_client] = lambda: LLMClient(provider, "fake-model")
    return TestClient(app)


def org_profile(client: TestClient) -> dict:
    body = {"slug": "northbridge", "name": "Northbridge minutes", "body_name": "Board",
            "based_on_slug": "dess-standard"}  # fmt: skip
    response = client.post("/api/profiles", json=body)
    assert response.status_code == 201, response.text
    return response.json()


def edited_run(client: TestClient, profile: str = "northbridge") -> str:
    run_id = create(client, auto_confirm_mapping="true", profile_slug=profile)["id"]
    assert upload(client, run_id, edited_copy(client, run_id)).status_code == 201
    return run_id


def entries(*runs: str) -> list[Entry]:
    return [Entry(f"F{n}", run, "edit", "...") for n, run in enumerate(runs, 1)]


def change(action: LessonAction, text: str, support: list[str], lesson_id: str | None = None):  # noqa: ANN201
    return LessonChange(action=action, lesson_id=lesson_id, text=text, support=support)


# The curator's rules


def test_a_lesson_needs_two_drafts_or_a_stated_reason() -> None:
    once = change(LessonAction.ADD, "Name the seconder.", ["F1"])
    twice = change(LessonAction.ADD, "Record vote counts.", ["F1", "F2"])
    same_run = change(LessonAction.ADD, "Use 'the Board'.", ["F1", "F3"])
    found = entries("run-a", "run-b", "run-a")

    lessons = learning.apply_changes([], [once, twice, same_run], found)

    assert [(x.id, x.text, x.support) for x in lessons] == [("L1", "Record vote counts.", 2)]

    stated = [Entry("F1", "run-a", "revision_request", "Always name the seconder.")]
    lessons = learning.apply_changes([], [once], stated)
    assert [x.text for x in lessons] == ["Name the seconder."]


def test_revise_and_remove_need_backing() -> None:
    lessons = [Lesson("L1", "Old", 2), Lesson("L2", "Keep", 1), Lesson("L3", "Drop", 1)]
    changes = [
        change(LessonAction.REVISE, "New", ["F1"], "L1"),
        change(LessonAction.REMOVE, "", [], "L2"),  # no backing: ignored
        change(LessonAction.REMOVE, "", ["F1"], "L3"),
        change(LessonAction.REVISE, "Ghost", ["F1"], "L9"),  # unknown id: ignored
    ]

    result = learning.apply_changes(lessons, changes, entries("run-a"))

    assert [(x.id, x.text, x.support) for x in result] == [("L1", "New", 3), ("L2", "Keep", 1)]


def test_lessons_round_trip_as_markdown() -> None:
    lessons = [Lesson("L1", "Record vote counts.", 3), Lesson("L4", "Name the seconder.", 1)]
    text = learning.render_lessons(lessons)
    assert text.splitlines()[0] == "- [L1] Record vote counts. _(seen in 3 drafts)_"
    assert learning.parse_lessons(text) == lessons


def test_lessons_follow_the_logic_in_the_system_prompt(profile_content: ProfileContent) -> None:
    content = profile_content.model_copy(update={"lessons": "- [L1] Record vote counts."})
    system = PromptContext(content, EvidenceBundle([]), MeetingInfo()).system()
    assert system.index(content.logic) < system.index(LESSONS_HEADING)
    assert system.endswith("- [L1] Record vote counts.")


# Organisation profiles and the learn endpoint


def test_organisation_profile_starts_as_a_confirmed_copy(client: TestClient) -> None:
    profile = org_profile(client)
    assert profile["active_version"] == 1

    v1 = client.get("/api/profiles/northbridge/versions/1").json()
    base = client.get("/api/profiles/dess-standard/versions/1").json()
    assert v1["content"]["logic"] == base["content"]["logic"]
    assert v1["content"]["name"] == "Northbridge minutes"
    assert v1["origin"] == "customisation"


def test_learning_proposes_a_version_for_a_person_to_confirm(
    client: TestClient, provider: ScriptedProvider
) -> None:
    org_profile(client)
    first = edited_run(client)
    edited_run(client)
    vote(client, first, "revision_requested", "Always record who abstained.")
    provider.responses["LessonsUpdate"] = LessonsUpdate(
        changes=[
            change(LessonAction.ADD, "Record who abstained on each resolution.", ["F1", "F2", "F3"])
        ],  # fmt: skip
        summary="Abstentions were added by hand.",
    )

    response = client.post("/api/profiles/northbridge/learn")

    assert response.status_code == 201, response.text
    v2 = response.json()
    assert (v2["version_number"], v2["status"], v2["origin"]) == (2, "proposed", "feedback")
    assert v2["content"]["lessons"] == (
        "- [L1] Record who abstained on each resolution. _(seen in 2 drafts)_"
    )
    assert client.get("/api/profiles/northbridge").json()["active_version"] == 1
    sent = provider.requests[-1].messages[0].content
    assert "Priya Shah abstained." in sent and "Always record who abstained." in sent
    assert "[F3] revision_request" in sent and "[F4]" not in sent  # two edits and one reason

    # The same feedback is not learned twice.
    assert client.post("/api/profiles/northbridge/learn").status_code == 409


def test_the_shared_standard_does_not_learn(client: TestClient) -> None:
    edited_run(client, profile="dess-standard")
    response = client.post("/api/profiles/dess-standard/learn")
    assert response.status_code == 409
    assert "per organisation" in response.json()["detail"]


def test_nothing_to_learn_is_409(client: TestClient) -> None:
    org_profile(client)
    assert client.post("/api/profiles/northbridge/learn").status_code == 409


def test_house_examples_come_only_from_the_same_organisation(
    client: TestClient, provider: ScriptedProvider, db: Session
) -> None:
    org_profile(client)
    edited_run(client, profile="dess-standard")  # another client's edit
    assert learning.house_examples(db, profile_svc.get_profile(db, "northbridge")) == {}

    edited_run(client)
    examples = learning.house_examples(db, profile_svc.get_profile(db, "northbridge"))
    assert examples["approval"][0].startswith("Minutes of the previous meeting\n")
    assert any("Priya Shah abstained." in e for e in examples["approval"])

    provider.requests.clear()
    create(client, auto_confirm_mapping="true", profile_slug="northbridge")
    roof = next(
        r.messages[0].content
        for r in provider.requests
        if r.schema and r.schema.__name__ == "ItemDraft" and samples.item_ref(r) == "4"
    )
    assert "<house_examples>" in roof and "Priya Shah abstained." in roof
