from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app.db import get_db
from app.main import app as main_app
from app.minutes.profile_content import ProfileContent
from app.routers import profile as profile_routes
from app.services import profile as svc


@pytest.fixture
def client(session_factory: sessionmaker[Session]) -> TestClient:
    app = FastAPI()
    app.include_router(profile_routes.router, prefix="/api")

    def override_db() -> Iterator[Session]:
        with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_db
    return TestClient(app)


@pytest.fixture
def seeded(db: Session, profile_content: ProfileContent) -> ProfileContent:
    svc.seed_profile(db, profile_content, slug="std", confirm_version=True)
    return profile_content


def test_routes_are_off_by_default() -> None:
    paths = {getattr(r, "path", "") for r in main_app.routes}
    assert "/api/profiles" not in paths


def test_schema_endpoint(client: TestClient) -> None:
    response = client.get("/api/profiles/schema")
    assert response.status_code == 200
    assert response.json()["title"] == "MinutesProfileContent"


def test_list_and_get_profile(client: TestClient, seeded: ProfileContent) -> None:
    listing = client.get("/api/profiles").json()
    assert listing == [
        {
            "slug": "std",
            "name": "Test Standard Profile",
            "description": "Minimal profile used by the test suite.",
            "body_name": None,
            "based_on_slug": None,
            "active_version": 1,
            "latest_version": 1,
        }
    ]

    detail = client.get("/api/profiles/std").json()
    assert [v["status"] for v in detail["versions"]] == ["confirmed"]


def test_get_active_version_returns_content(client: TestClient, seeded: ProfileContent) -> None:
    body = client.get("/api/profiles/std/active").json()
    assert body["version_number"] == 1
    assert body["origin"] == "seed"
    assert ProfileContent.model_validate(body["content"]) == seeded


def test_unknown_profile_is_404(client: TestClient) -> None:
    assert client.get("/api/profiles/nope").status_code == 404
    assert client.get("/api/profiles/nope/active").status_code == 404


def test_create_profile_and_conflict(client: TestClient) -> None:
    payload = {"slug": "audit-committee", "name": "Audit Committee", "body_name": "Audit Committee"}
    assert client.post("/api/profiles", json=payload).status_code == 201
    assert client.post("/api/profiles", json=payload).status_code == 409
    assert client.post("/api/profiles", json={**payload, "slug": "Bad Slug"}).status_code == 422
    assert client.get("/api/profiles/audit-committee/active").status_code == 404


def test_version_lifecycle(client: TestClient, seeded: ProfileContent) -> None:
    content = seeded.model_dump(mode="json") | {"description": "Second edition"}
    created = client.post(
        "/api/profiles/std/versions",
        json={"content": content, "change_summary": "tweak", "created_by": "fiifi"},
    )
    assert created.status_code == 201
    assert created.json()["version_number"] == 2
    assert created.json()["status"] == "proposed"
    assert created.json()["parent_version"] == 1

    skip = client.post("/api/profiles/std/versions/2/status", json={"status": "confirmed"})
    assert skip.status_code == 409

    for step in ("reviewed", "confirmed"):
        r = client.post("/api/profiles/std/versions/2/status", json={"status": step, "by": "paul"})
        assert r.status_code == 200
    assert client.get("/api/profiles/std/active").json()["version_number"] == 2
    assert client.get("/api/profiles/std/versions/2").json()["confirmed_by"] == "paul"


def test_floor_violation_is_422(client: TestClient, seeded: ProfileContent) -> None:
    content = seeded.model_dump(mode="json") | {"hard_floors": ["Anything goes."]}
    response = client.post("/api/profiles/std/versions", json={"content": content})
    assert response.status_code == 422
    assert response.json()["detail"] == {
        "floor_violations": ["hard_floors differ from the parent version"]
    }


def test_invalid_content_is_422(client: TestClient, seeded: ProfileContent) -> None:
    content = seeded.model_dump(mode="json")
    content["writing_style"] = content["writing_style"][:3]
    response = client.post("/api/profiles/std/versions", json={"content": content})
    assert response.status_code == 422
