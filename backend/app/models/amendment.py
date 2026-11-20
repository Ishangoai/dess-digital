"""Profile amendment proposal and review models."""

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import DateTime, ForeignKey, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.minutes.profile_content import Provenance, ProvisionKind
from app.models.profile import MinutesProfileVersion, VersionOrigin, str_enum, utcnow

# Re-export helpers so other modules can import from here if needed.
__all__ = [
    "AmendmentOperation",
    "AmendmentStatus",
    "AmendmentTargetType",
    "MinutesProfileVersion",
    "ProfileAmendmentProposal",
    "ProfileAmendmentSet",
    "Provenance",
    "ProvisionKind",
    "VersionOrigin",
    "str_enum",
    "utcnow",
]


class AmendmentTargetType(StrEnum):
    PROVISION = "provision"
    APPLICATION_NOTE = "application_note"


class AmendmentOperation(StrEnum):
    ADD = "add"
    REPLACE = "replace"
    REMOVE = "remove"


class AmendmentStatus(StrEnum):
    PROPOSED = "proposed"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    DEFERRED = "deferred"


class ProfileAmendmentSet(Base):
    """A batch of amendment proposals originating from one source."""

    __tablename__ = "profile_amendment_sets"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    profile_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("minutes_profile_versions.id"), nullable=False
    )
    origin: Mapped[VersionOrigin] = mapped_column(str_enum(VersionOrigin))
    title: Mapped[str | None] = mapped_column(String(255))
    created_by: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    proposals: Mapped[list["ProfileAmendmentProposal"]] = relationship(
        back_populates="amendment_set"
    )
    profile_version: Mapped[MinutesProfileVersion] = relationship()


class ProfileAmendmentProposal(Base):
    """A single proposed change to one provision or application note."""

    __tablename__ = "profile_amendment_proposals"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    amendment_set_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("profile_amendment_sets.id"), nullable=False
    )
    target_dimension: Mapped[str] = mapped_column(String(8))
    target_provision: Mapped[str | None] = mapped_column(String(255))
    target_type: Mapped[AmendmentTargetType] = mapped_column(str_enum(AmendmentTargetType))
    operation: Mapped[AmendmentOperation] = mapped_column(str_enum(AmendmentOperation))
    proposed_text: Mapped[str | None] = mapped_column(Text)
    kind: Mapped[ProvisionKind | None] = mapped_column(str_enum(ProvisionKind))
    provenance: Mapped[Provenance | None] = mapped_column(str_enum(Provenance))
    scope: Mapped[str | None] = mapped_column(String(255))
    reason: Mapped[str | None] = mapped_column(Text)
    evidence: Mapped[str | None] = mapped_column(Text)
    status: Mapped[AmendmentStatus] = mapped_column(
        str_enum(AmendmentStatus), default=AmendmentStatus.PROPOSED
    )
    decided_by: Mapped[str | None] = mapped_column(String(255))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    conflict_warning: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    amendment_set: Mapped[ProfileAmendmentSet] = relationship(back_populates="proposals")
