"""Thin HTTP client for the minutes API."""

from pathlib import Path
from typing import Any

import httpx


class ApiError(Exception):
    pass


class MinutesApi:
    def __init__(self, base_url: str, timeout: float = 1800) -> None:  # long meetings take a while
        self.http = httpx.Client(base_url=base_url.rstrip("/") + "/api", timeout=timeout)

    def _json(self, response: httpx.Response) -> Any:
        if response.is_error:
            try:
                detail = response.json().get("detail", response.text)
            except ValueError:
                detail = response.text
            raise ApiError(f"{response.status_code}: {detail}")
        return response.json()

    def create_draft(
        self,
        agenda: Path,
        transcript: Path | None,
        notes: Path | None,
        form: dict[str, str],
    ) -> dict[str, Any]:
        files = [("agenda", (agenda.name, agenda.read_bytes()))]
        for role, path in (("transcript", transcript), ("notes", notes)):
            if path:
                files.append((role, (path.name, path.read_bytes())))
        return self._json(self.http.post("/drafts", files=files, data=form))

    def get_draft(self, run_id: str, debug: bool = True) -> dict[str, Any]:
        return self._json(self.http.get(f"/drafts/{run_id}", params={"debug": debug}))

    def list_drafts(self) -> list[dict[str, Any]]:
        return self._json(self.http.get("/drafts", params={"limit": 50}))

    def get_mapping(self, run_id: str) -> dict[str, Any]:
        return self._json(self.http.get(f"/drafts/{run_id}/mapping"))

    def retry_analysis(self, run_id: str) -> dict[str, Any]:
        return self._json(self.http.post(f"/drafts/{run_id}/analyse"))

    def generate(self, run_id: str, mapping: dict[str, Any] | None) -> dict[str, Any]:
        return self._json(self.http.post(f"/drafts/{run_id}/generate", json=mapping))

    def document(self, run_id: str, template: Path | None = None) -> bytes:
        if template:
            files = {"template": (template.name, template.read_bytes())}
            response = self.http.post(f"/drafts/{run_id}/document", files=files)
        else:
            response = self.http.get(f"/drafts/{run_id}/document.docx")
        if response.is_error:
            self._json(response)
        return response.content

    def list_profiles(self) -> list[dict[str, Any]]:
        return self._json(self.http.get("/profiles"))

    def active_profile(self, slug: str) -> dict[str, Any]:
        return self._json(self.http.get(f"/profiles/{slug}/active"))

    def create_profile_version(self, slug: str, content: dict[str, Any], summary: str) -> dict:
        body = {"content": content, "change_summary": summary or None, "created_by": "dev-ui"}
        return self._json(self.http.post(f"/profiles/{slug}/versions", json=body))

    def set_status(self, slug: str, number: int, status: str) -> dict[str, Any]:
        body = {"status": status, "by": "dev-ui"}
        return self._json(self.http.post(f"/profiles/{slug}/versions/{number}/status", json=body))
