import os
import shutil
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile

router = APIRouter(prefix="/files", tags=["Files"])


BASE_DIR = Path(__file__).resolve().parent.parent.parent
LOCAL_DEV_DIR = BASE_DIR / "data" / "files" / "uploads"

# Read from the environment variable 'UPLOAD_DIR', fallback to local directory
BASE_UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR", LOCAL_DEV_DIR))


@router.post("/upload")
async def upload_file(file: UploadFile = File(...)):
    if not file.filename:
        raise HTTPException(status_code=400, detail="No file provided")

    # --- Optional: Restrict to Microsoft Word formats only (.doc, .docx) ---
    # ALLOWED_TYPES = [
    #     "application/msword",
    #     "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    # ]
    # if file.content_type not in ALLOWED_TYPES:
    #     raise HTTPException(
    #         status_code=415,
    #         detail="Unsupported file type. Only MS Word documents are allowed."
    #     )
    # ------------------------------------------------------------------------

    current_time = datetime.now(UTC).strftime("%Y-%m-%d_%H-%M-%S")
    target_dir = BASE_UPLOAD_DIR / current_time

    os.makedirs(target_dir, exist_ok=True)

    safe_filename = Path(file.filename).name

    file_path = target_dir / safe_filename

    try:
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save file: {str(e)}") from e
    finally:
        file.file.close()

    relative_path = file_path.relative_to(BASE_DIR)

    return {
        "message": "File uploaded successfully",
        "filename": safe_filename,
        "path": str(relative_path),
        "timestamp_folder": current_time,
    }
