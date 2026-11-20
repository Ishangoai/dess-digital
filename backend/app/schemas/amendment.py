"""Pydantic schemas for Profile Amendment Proposal & Review."""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.minutes.profile_content import DimensionCode, Provenance, ProvisionKind
from app.models.amendment import (
    AmendmentOperation,
    AmendmentStatus,
    AmendmentTargetType,
    ProfileAmendmentProposal,
    ProfileAmendmentSet,
)
from app.models.profile import VersionOrigin

# ---------------------------------------------------------------------------
# Input schemas
# ---------------------------------------------------------------------------


class ProposalCreate(BaseModel):
    target_dimension: DimensionCode
    target_provision: str | None = None
    target_type: AmendmentTargetType = AmendmentTargetType.PROVISION
    operation: AmendmentOperation
    proposed_text: str | None = None
    kind: ProvisionKind | None = None
    provenance: Provenance | None = None
    scope: str | None = None
    reason: str | None = None
    evidence: str | None = None


class AmendmentSetCreate(BaseModel):
    profile_version_id: uuid.UUID
    origin: VersionOrigin  # only feedback or customisation are valid at service layer
    title: str | None = None
    created_by: str | None = None
    proposals: list[ProposalCreate] = Field(min_length=1)


# ---------------------------------------------------------------------------
# Output schemas
# ---------------------------------------------------------------------------


class ProposalOut(BaseModel):
    id: uuid.UUID
    amendment_set_id: uuid.UUID
    target_dimension: str
    target_provision: str | None
    target_type: AmendmentTargetType
    operation: AmendmentOperation
    proposed_text: str | None
    kind: ProvisionKind | None
    provenance: Provenance | None
    scope: str | None
    reason: str | None
    evidence: str | None
    status: AmendmentStatus
    decided_by: str | None
    decided_at: datetime | None
    conflict_warning: str | None
    created_at: datetime

    @classmethod
    def of(cls, p: ProfileAmendmentProposal) -> "ProposalOut":
        return cls(
            id=p.id,
            amendment_set_id=p.amendment_set_id,
            target_dimension=p.target_dimension,
            target_provision=p.target_provision,
            target_type=p.target_type,
            operation=p.operation,
            proposed_text=p.proposed_text,
            kind=p.kind,
            provenance=p.provenance,
            scope=p.scope,
            reason=p.reason,
            evidence=p.evidence,
            status=p.status,
            decided_by=p.decided_by,
            decided_at=p.decided_at,
            conflict_warning=p.conflict_warning,
            created_at=p.created_at,
        )


class AmendmentSetOut(BaseModel):
    id: uuid.UUID
    profile_version_id: uuid.UUID
    origin: VersionOrigin
    title: str | None
    created_by: str | None
    created_at: datetime
    proposals: list[ProposalOut]

    @classmethod
    def of(cls, s: ProfileAmendmentSet) -> "AmendmentSetOut":
        return cls(
            id=s.id,
            profile_version_id=s.profile_version_id,
            origin=s.origin,
            title=s.title,
            created_by=s.created_by,
            created_at=s.created_at,
            proposals=[ProposalOut.of(p) for p in s.proposals],
        )


# ---------------------------------------------------------------------------
# Patch / action bodies
# ---------------------------------------------------------------------------


class ProposalUpdate(BaseModel):
    status: AmendmentStatus | None = None
    proposed_text: str | None = None
    decided_by: str | None = None


class ApplySetRequest(BaseModel):
    confirmed_by: str | None = None
