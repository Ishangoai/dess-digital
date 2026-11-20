"""Tests for amendment proposal and review REST endpoints."""

import uuid
from collections.abc import Iterator
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app.db import get_db
from app.llm.client import LLMClient
from app.minutes.profile_content import ProfileContent
from app.routers import profile as profile_routes
from app.services import profile as svc
from app.services.amendment import ConflictCheckResult
from tests.fakes import ScriptedProvider


def make_llm(warning: str | None = None) -> LLMClient:
    response = ConflictCheckResult(
        has_conflict=warning is not None,
        conflict_type="contradiction" if warning else None,
        warning=warning,
    )
    provider = ScriptedProvider({"ConflictCheckResult": response})
    return LLMClient(provider, "test-model")


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
def seeded(db: Session, profile_content: ProfileContent) -> tuple:
    result = svc.seed_profile(db, profile_content, slug="std", confirm_version=True)
    return result.profile, result.version, profile_content


def _proposal_payload(
    operation: str = "replace",
    target: str | None = "ws4-names-for-actions",
    dim: str = "WS4",
    text: str | None = "New text.",
) -> dict:
    return {
        "target_dimension": dim,
        "target_provision": target,
        "target_type": "provision",
        "operation": operation,
        "proposed_text": text,
        "kind": "preference",
        "provenance": "professional_preference",
        "scope": "Board",
        "reason": "Client requested change during onboarding",
        "evidence": "Interview transcript #12",
    }


def test_create_and_list_amendment_sets(client: TestClient, seeded: tuple) -> None:
    profile, version, content = seeded

    with patch("app.services.amendment.check_proposal_conflicts", return_value=None):
        payload = {
            "profile_version_id": str(version.id),
            "origin": "feedback",
            "title": "Onboarding tweaks",
            "created_by": "tester",
            "proposals": [_proposal_payload()],
        }
        r = client.post("/api/profiles/std/amendment-sets", json=payload)
        assert r.status_code == 201, r.text
        data = r.json()
        assert data["origin"] == "feedback"
        assert data["title"] == "Onboarding tweaks"
        assert len(data["proposals"]) == 1
        assert data["proposals"][0]["status"] == "proposed"
        assert data["proposals"][0]["conflict_warning"] is None
        set_id = data["id"]

    # List all sets
    r = client.get("/api/profiles/std/amendment-sets")
    assert r.status_code == 200
    sets = r.json()
    assert len(sets) >= 1
    assert any(s["id"] == set_id for s in sets)

    # Filter by version_id
    r = client.get(f"/api/profiles/std/amendment-sets?version_id={version.id}")
    assert r.status_code == 200
    assert len(r.json()) == 1

    # Filter by non-existent version_id
    r = client.get(f"/api/profiles/std/amendment-sets?version_id={uuid.uuid4()}")
    assert r.status_code == 200
    assert len(r.json()) == 0

    # Get single set
    r = client.get(f"/api/profiles/std/amendment-sets/{set_id}")
    assert r.status_code == 200
    assert r.json()["id"] == set_id


def test_conflict_warning_in_route(
    client: TestClient, seeded: tuple, session_factory: sessionmaker[Session]
) -> None:
    profile, version, content = seeded

    mock_warning = "Contradicts existing provision ws4-names-for-actions."
    app = FastAPI()
    app.include_router(profile_routes.router, prefix="/api")

    def override_db() -> Iterator[Session]:
        with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[profile_routes.llm_client] = lambda: make_llm(mock_warning)
    custom_client = TestClient(app)

    payload = {
        "profile_version_id": str(version.id),
        "origin": "customisation",
        "title": "Conflicting set",
        "proposals": [_proposal_payload()],
    }
    r = custom_client.post("/api/profiles/std/amendment-sets", json=payload)
    assert r.status_code == 201, r.text
    data = r.json()
    assert data["proposals"][0]["conflict_warning"] == mock_warning
    assert data["proposals"][0]["status"] == "proposed"


def test_update_proposal_reword_and_accept(client: TestClient, seeded: tuple) -> None:
    profile, version, content = seeded

    with patch("app.services.amendment.check_proposal_conflicts", return_value=None):
        payload = {
            "profile_version_id": str(version.id),
            "origin": "feedback",
            "proposals": [_proposal_payload()],
        }
        r = client.post("/api/profiles/std/amendment-sets", json=payload)
        assert r.status_code == 201
        data = r.json()
        set_id = data["id"]
        prop_id = data["proposals"][0]["id"]

    # Reword proposal
    r = client.patch(
        f"/api/profiles/std/amendment-sets/{set_id}/proposals/{prop_id}",
        json={"proposed_text": "Reworded plain English text."},
    )
    assert r.status_code == 200
    assert r.json()["proposed_text"] == "Reworded plain English text."
    assert r.json()["status"] == "proposed"

    # Accept proposal
    r = client.patch(
        f"/api/profiles/std/amendment-sets/{set_id}/proposals/{prop_id}",
        json={"status": "accepted", "decided_by": "auditor"},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "accepted"
    assert r.json()["decided_by"] == "auditor"
    assert r.json()["decided_at"] is not None


def test_apply_amendment_set_workflow(client: TestClient, seeded: tuple) -> None:
    profile, version, content = seeded

    with patch("app.services.amendment.check_proposal_conflicts", return_value=None):
        payload = {
            "profile_version_id": str(version.id),
            "origin": "feedback",
            "proposals": [
                _proposal_payload(operation="replace", text="Accepted custom text."),
                _proposal_payload(operation="replace", text="Rejected proposal."),
            ],
        }
        r = client.post("/api/profiles/std/amendment-sets", json=payload)
        assert r.status_code == 201
        set_id = r.json()["id"]
        prop0_id = r.json()["proposals"][0]["id"]
        prop1_id = r.json()["proposals"][1]["id"]

    # Reject prop1
    client.patch(
        f"/api/profiles/std/amendment-sets/{set_id}/proposals/{prop1_id}",
        json={"status": "rejected", "decided_by": "reviewer"},
    )

    # Trying to apply before accepting any returns 422
    r = client.post(f"/api/profiles/std/amendment-sets/{set_id}/apply", json={})
    assert r.status_code == 422
    assert "No accepted proposals" in r.json()["detail"]

    # Accept prop0
    client.patch(
        f"/api/profiles/std/amendment-sets/{set_id}/proposals/{prop0_id}",
        json={"status": "accepted", "decided_by": "reviewer"},
    )

    # Apply accepted
    r = client.post(
        f"/api/profiles/std/amendment-sets/{set_id}/apply",
        json={"confirmed_by": "governance_officer"},
    )
    assert r.status_code == 201
    new_v = r.json()
    assert new_v["version_number"] == 2
    assert new_v["status"] == "confirmed"
    assert new_v["origin"] == "feedback"
    assert new_v["confirmed_by"] == "governance_officer"
    assert "Accepted custom text." in new_v["change_summary"]
    assert "Rejected proposal." not in new_v["change_summary"]


def test_404_cases(client: TestClient, seeded: tuple) -> None:
    profile, version, content = seeded
    fake_id = str(uuid.uuid4())

    # Unknown profile
    assert client.get("/api/profiles/non-existent/amendment-sets").status_code == 404
    # Unknown set
    assert client.get(f"/api/profiles/std/amendment-sets/{fake_id}").status_code == 404
    # Unknown proposal
    assert (
        client.patch(
            f"/api/profiles/std/amendment-sets/{fake_id}/proposals/{fake_id}",
            json={"status": "accepted"},
        ).status_code
        == 404
    )
