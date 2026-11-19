import uuid
from datetime import datetime

from pydantic import BaseModel

from app.minutes.docx_compare import Comparison
from app.minutes.edit_review import EditClassificationResult
from app.models.draft import ClassificationStatus, EditedDocument
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
    classification_status: ClassificationStatus | None
    classification_error: str | None
    classified_at: datetime | None
    classification: EditClassificationResult | None

    @classmethod
    def of(cls, document: EditedDocument) -> "EditedDocumentOut":
        summary = EditedDocumentSummary.of(document)
        row = document.comparison
        assert row is not None
        return cls(
            **summary.model_dump(),
            comparison=svc.comparison_of(document),
            classification_status=row.classification_status,
            classification_error=row.classification_error,
            classified_at=row.classified_at,
            classification=svc.classification_of(document),
        )
