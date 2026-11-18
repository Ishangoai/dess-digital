from fastapi.testclient import TestClient

from app.config import settings
from app.main import app
from app.routers.auth import require_auth


def test_protected_route_requires_auth() -> None:
    app.dependency_overrides.pop(require_auth, None)
    client = TestClient(app)

    res = client.get("/api/auth/me")
    assert res.status_code == 401


def test_login_and_logout_flow() -> None:
    app.dependency_overrides.pop(require_auth, None)
    client = TestClient(app)

    bad = client.post("/api/auth/login", json={"username": "wrong", "password": "wrong"})
    assert bad.status_code == 401

    ok = client.post(
        "/api/auth/login",
        json={"username": settings.auth_user, "password": settings.auth_password},
    )
    assert ok.status_code == 200
    assert client.get("/api/auth/me").status_code == 200

    out = client.post("/api/auth/logout")
    assert out.status_code == 200
    assert client.get("/api/auth/me").status_code == 401
