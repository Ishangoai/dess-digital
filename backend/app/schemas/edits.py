import uuid
from datetime import datetime

from pydantic import BaseModel

from app.minutes.amendments import Operation, Overlap, dimension_of
from app.minutes.docx_compare import Comparison
from app.minutes.edit_review import EditClassificationResult
from app.minutes.profile_content import DimensionCode, ProfileContent, ProvisionKind
from app.models.draft import (
    AmendmentProposal,
    AmendmentSet,
    ClassificationStatus,
    EditedDocument,
    ProposalStatus,
)
from app.services import amendments as amendments_svc
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


class AmendmentProposalOut(BaseModel):
    id: uuid.UUID
    pattern_id: str
    change_ids: list[str]
    dimension: DimensionCode
    dimension_title: str
    operation: Operation
    target_rule_id: str | None
    current_text: str | None  # the rule being replaced or removed
    text: str | None
    proposed_text: str | None
    kind: ProvisionKind
    overlap: Overlap
    overlap_with: str | None
    reason: str
    refused: str | None
    status: ProposalStatus
    decided_by: str | None
    decided_at: datetime | None

    @classmethod
    def of(cls, p: AmendmentProposal, rules: ProfileContent) -> "AmendmentProposalOut":
        dim = dimension_of(rules, DimensionCode(p.dimension))
        current = next((r.text for r in dim.provisions if r.id == p.target_rule_id), None)
        return cls(
            id=p.id,
            pattern_id=p.pattern_id,
            change_ids=p.change_ids,
            dimension=dim.code,
            dimension_title=dim.title,
            operation=p.operation,
            target_rule_id=p.target_rule_id,
            current_text=current,
            text=p.text,
            proposed_text=p.proposed_text,
            kind=p.kind,
            overlap=p.overlap,
            overlap_with=p.overlap_with,
            reason=p.reason,
            refused=p.refused,
            status=p.status,
            decided_by=p.decided_by,
            decided_at=p.decided_at,
        )


class AmendmentSetOut(BaseModel):
    id: uuid.UUID
    status: ClassificationStatus
    error: str | None
    profile_slug: str
    profile_name: str
    base_version: int
    applied_version: int | None
    applied_at: datetime | None
    proposals: list[AmendmentProposalOut]

    @classmethod
    def of(cls, found: AmendmentSet) -> "AmendmentSetOut":
        rules = amendments_svc.current_rules(found)
        profile = found.profile_version.profile
        return cls(
            id=found.id,
            status=found.status,
            error=found.error,
            profile_slug=profile.slug,
            profile_name=profile.name,
            base_version=found.profile_version.version_number,
            applied_version=found.applied_version.version_number if found.applied_version else None,
            applied_at=found.applied_at,
            proposals=[AmendmentProposalOut.of(p, rules) for p in found.proposals],
        )


class ProposalUpdate(BaseModel):
    status: ProposalStatus | None = None
    text: str | None = None
    by: str | None = None


class ApplyAmendments(BaseModel):
    by: str | None = None


class EditedDocumentOut(EditedDocumentSummary):
    comparison: Comparison
    classification_status: ClassificationStatus | None
    classification_error: str | None
    classified_at: datetime | None
    classification: EditClassificationResult | None
    amendments: AmendmentSetOut | None

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
            amendments=AmendmentSetOut.of(document.amendments) if document.amendments else None,
        )
