from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile, status

from app.config import settings
from app.services.file_service import save_upload_file

router = APIRouter(prefix="/files", tags=["Files"])


@router.post("/upload")
async def upload_files(
    agenda: UploadFile = File(...),
    transcript: UploadFile | None = File(default=None),
    meeting_notes: UploadFile | None = File(default=None),
):
    BASE_UPLOAD_DIR = settings.uploads_dir

    if not transcript and not meeting_notes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "You must upload either a transcript or meeting notes "
                "(or both) alongside the agenda."
            ),
        )

    # Define your allowed MIME types
    WORD_TYPES = [
        "application/msword",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ]
    PDF_TYPES = ["application/pdf"]

    current_time = datetime.now(UTC).strftime("%Y-%m-%d_%H-%M-%S")
    target_dir = BASE_UPLOAD_DIR / current_time
    target_dir.mkdir(parents=True, exist_ok=True)

    saved_files = []

    agenda_data = await save_upload_file(
        agenda, 
        target_dir, 
        "agenda", 
        allowed_types=WORD_TYPES + PDF_TYPES
    )
    saved_files.append(agenda_data)

    if transcript:
        transcript_data = await save_upload_file(
            transcript, 
            target_dir, 
            "transcript", 
            allowed_types=WORD_TYPES + PDF_TYPES
        )
        saved_files.append(transcript_data)

    if meeting_notes:
        notes_data = await save_upload_file(
            meeting_notes, 
            target_dir, 
            "meeting_notes", 
            allowed_types=WORD_TYPES + PDF_TYPES
        )
        saved_files.append(notes_data)

    for f in saved_files:
        if "path" in f:
            f["path"] = str(Path(f["path"]).relative_to(BASE_UPLOAD_DIR))

    return {
        "message": "Files uploaded successfully",
        "timestamp_folder": current_time,
        "files": saved_files,
    }
