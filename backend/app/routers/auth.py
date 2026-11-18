import hashlib
import hmac
import secrets

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel

from app.config import settings

COOKIE_NAME = "dess_session"
router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(BaseModel):
    username: str
    password: str


def _make_token(username: str) -> str:
    sig = hmac.new(settings.auth_secret.encode(), username.encode(), hashlib.sha256).hexdigest()
    return f"{username}:{sig}"


def _verify_token(token: str | None) -> bool:
    if not token or ":" not in token:
        return False
    username, _ = token.split(":", 1)
    expected = _make_token(username)
    return hmac.compare_digest(token, expected) and secrets.compare_digest(
        username, settings.auth_user
    )


def require_auth(request: Request) -> None:
    if not _verify_token(request.cookies.get(COOKIE_NAME)):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")


@router.post("/login")
def login(payload: LoginRequest, response: Response) -> dict[str, str]:
    user_ok = secrets.compare_digest(payload.username, settings.auth_user)
    pass_ok = secrets.compare_digest(payload.password, settings.auth_password)
    if not (user_ok and pass_ok):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    response.set_cookie(
        key=COOKIE_NAME,
        value=_make_token(payload.username),
        httponly=True,
        samesite="lax",
        path="/",
    )
    return {"status": "ok"}


@router.post("/logout")
def logout(response: Response) -> dict[str, str]:
    response.delete_cookie(key=COOKIE_NAME, path="/")
    return {"status": "ok"}


@router.get("/me", dependencies=[Depends(require_auth)])
def me() -> dict[str, str]:
    return {"username": settings.auth_user}
