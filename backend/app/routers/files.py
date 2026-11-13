from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile, status

from app.config import settings
from app.services.file_service import save_upload_file

router = APIRouter(prefix="/files", tags=["Files"])

ALLOWED_TYPES = [
    "application/pdf",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
]


@router.post("/upload")
async def upload_files(
    agenda: UploadFile = File(...),
    transcript: UploadFile | None = File(default=None),
    meeting_notes: UploadFile | None = File(default=None),
):
    if not transcript and not meeting_notes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "You must upload either a transcript or meeting notes "
                "(or both) alongside the agenda."
            ),
        )

    upload_dir = settings.uploads_dir
    current_time = datetime.now(UTC).strftime("%Y-%m-%d_%H-%M-%S")
    target_dir = upload_dir / current_time
    target_dir.mkdir(parents=True, exist_ok=True)

    uploads = {"agenda": agenda, "transcript": transcript, "meeting_notes": meeting_notes}
    saved_files = [
        await save_upload_file(upload, target_dir, file_type, allowed_types=ALLOWED_TYPES)
        for file_type, upload in uploads.items()
        if upload
    ]

    for f in saved_files:
        if "path" in f:
            f["path"] = str(Path(f["path"]).relative_to(upload_dir))

    return {
        "message": "Files uploaded successfully",
        "timestamp_folder": current_time,
        "files": saved_files,
    }
