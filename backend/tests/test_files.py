from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app
from app.services import file_service

client = TestClient(app)

PDF = "application/pdf"
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


@pytest.fixture(autouse=True)
def files_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(settings, "files_dir", tmp_path)
    return tmp_path


def test_upload_saves_files(files_dir: Path) -> None:
    response = client.post(
        "/api/files/upload",
        files={
            "agenda": ("agenda.pdf", b"%PDF agenda", PDF),
            "transcript": ("t.docx", b"transcript", DOCX),
        },
    )

    assert response.status_code == 200
    body = response.json()
    folder = body["timestamp_folder"]
    assert [f["path"] for f in body["files"]] == [
        f"{folder}/agenda_agenda.pdf",
        f"{folder}/transcript_t.docx",
    ]
    saved = files_dir / "uploads" / folder
    assert (saved / "agenda_agenda.pdf").read_bytes() == b"%PDF agenda"
    assert (saved / "transcript_t.docx").read_bytes() == b"transcript"


def test_upload_requires_transcript_or_notes() -> None:
    response = client.post("/api/files/upload", files={"agenda": ("agenda.pdf", b"%PDF", PDF)})

    assert response.status_code == 400


def test_upload_rejects_unsupported_type() -> None:
    response = client.post(
        "/api/files/upload",
        files={
            "agenda": ("agenda.txt", b"text", "text/plain"),
            "meeting_notes": ("notes.pdf", b"%PDF", PDF),
        },
    )

    assert response.status_code == 415


def test_upload_rejects_oversized_file(files_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(file_service, "MAX_FILE_SIZE", 4)

    response = client.post(
        "/api/files/upload",
        files={
            "agenda": ("agenda.pdf", b"%PDF too big", PDF),
            "meeting_notes": ("notes.pdf", b"%PDF", PDF),
        },
    )

    assert response.status_code == 413
    assert not list((files_dir / "uploads").glob("*/agenda_agenda.pdf"))
