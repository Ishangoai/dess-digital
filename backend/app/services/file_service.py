from pathlib import Path

from fastapi import HTTPException, UploadFile, status

MAX_FILE_SIZE = 20 * 1024 * 1024  # 20 MB
CHUNK_SIZE = 1024 * 1024  # 1 MB


async def save_upload_file(
    upload_file: UploadFile,
    target_dir: Path,
    file_type: str,
    allowed_types: list[str] | None = None,  # <-- New parameter
) -> dict:
    """Saves a single file in chunks and returns its metadata."""
    if not upload_file.filename:
        return {}

    # --- Type Validation ---
    if allowed_types and upload_file.content_type not in allowed_types:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=(
                f"The {file_type} file ('{upload_file.filename}') has an "
                "unsupported format. Please upload a PDF or Word document (.pdf, .doc, .docx)."
            ),
        )
    # -----------------------

    safe_filename = f"{file_type}_{Path(upload_file.filename).name}"
    file_path = target_dir / safe_filename
    total_size = 0

    try:
        with open(file_path, "wb") as buffer:
            while chunk := upload_file.file.read(CHUNK_SIZE):
                total_size += len(chunk)
                if total_size > MAX_FILE_SIZE:
                    buffer.close()
                    file_path.unlink(missing_ok=True)
                    raise HTTPException(
                        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        detail=f"The {file_type} file exceeded the 20MB limit.",
                    )
                buffer.write(chunk)

        return {
            "type": file_type,
            "filename": safe_filename,
            "path": str(file_path),
            "size_bytes": total_size,
        }
    except HTTPException:
        raise
    except Exception as e:
        file_path.unlink(missing_ok=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to save {file_type}: {str(e)}",
        ) from e
    finally:
        upload_file.file.close()
