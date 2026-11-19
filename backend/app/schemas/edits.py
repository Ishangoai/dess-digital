import uuid
from datetime import datetime

from pydantic import BaseModel

from app.minutes.docx_compare import Comparison
from app.models.draft import EditedDocument
from app.services import edits as svc


class EditedDocumentSummary(BaseModel):
    id: uuid.UUID
    filename: str
    uploaded_at: datetime
    export_id: uuid.UUID
    exported_at: datetime
    export_used_template: bool

    @classmethod
    def of(cls, document: EditedDocument) -> "EditedDocumentSummary":
        return cls(
            id=document.id,
            filename=document.filename,
            uploaded_at=document.uploaded_at,
            export_id=document.export_id,
            exported_at=document.export.created_at,
            export_used_template=document.export.used_template,
        )


class EditedDocumentOut(EditedDocumentSummary):
    comparison: Comparison

    @classmethod
    def of(cls, document: EditedDocument) -> "EditedDocumentOut":
        summary = EditedDocumentSummary.of(document)
        return cls(**summary.model_dump(), comparison=svc.comparison_of(document))
