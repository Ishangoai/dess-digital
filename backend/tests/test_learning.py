from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app.db import get_db
from app.llm import LLMClient
from app.minutes.profile_content import ProfileContent
from app.routers import draft as draft_routes
from app.routers import profile as profile_routes
from app.services import learning
from app.services import profile as profile_svc
from tests import minutes_samples as samples
from tests.fakes import ScriptedProvider
from tests.test_draft_routes import create
from tests.test_feedback import edited_copy, upload


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


# Organisation profiles and house examples


def test_organisation_profile_starts_as_a_confirmed_copy(client: TestClient) -> None:
    profile = org_profile(client)
    assert profile["active_version"] == 1

    v1 = client.get("/api/profiles/northbridge/versions/1").json()
    base = client.get("/api/profiles/dess-standard/versions/1").json()
    assert v1["content"]["logic"] == base["content"]["logic"]
    assert v1["content"]["name"] == "Northbridge minutes"
    assert v1["origin"] == "customisation"


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
